"""Test deployment and functionality of the cloudsupport charm."""
import textwrap
import time
from pathlib import Path

import tenacity

from tests.modules import test_utils

import zaza.openstack.charm_tests.test_utils as openstack_test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.utilities.deployment_env as deployment_env
from zaza import model


def gen_clouds_yaml(creds_dict):
    template = textwrap.dedent(
        """
    clouds:
      cloud1:
        region_name: {region_name}
        auth:
          auth_url: {auth_url}
          username: admin
          password: {password}
          user_domain_name: {user_domain_name}
          project_name: {project_name}
          domain_name: {domain_name}
    """
    )
    kw = {}
    for var in creds_dict.keys():
        if not var.startswith("OS_"):
            continue
        kw[var[3:].lower()] = creds_dict[var]
    return template.format(**kw)


class CloudSupportBaseTest(openstack_test_utils.OpenStackBaseTest):
    """Base tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for tests."""
        super(CloudSupportBaseTest, cls).setUpClass()
        cls.unit_name = model.get_units(cls.application_name, cls.model_name)[0].name
        cls.hypervisors = cls.nova_client.hypervisors.list()

    def get_test_instances(self):
        """Get instances that look like our test instance."""
        return [
            vm
            for vm in self.nova_client.servers.list()
            if vm.name.startswith("cloudsupport-test")
        ]

    def wait_for_server(self, server_id, status, timeout=360):
        """Wait for server status."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.nova_client.servers.get(server_id).status == status:
                break

            time.sleep(5)
        else:
            self.fail("VM `{}` did not reach status {}".format(server_id, status))


class CloudSupportTests(CloudSupportBaseTest):
    """Test cloudsupport related functionality."""

    def test_10_configure(self):
        """Test: perform configuration."""
        clouds = gen_clouds_yaml(openstack_utils.get_overcloud_auth())
        priv_key = test_utils.get_priv_key(Path(deployment_env.get_tmpdir()))
        with open(self.cacert) as f:
            keystone_ca_cert = f.read()

        cfg = {
            "clouds-yaml": clouds,
            "ssh-key": priv_key,
            "ram": "1024",
            "disk": "2",
            "cidr": "192.168.77.0/26",
            "stale-server-check": "true",
            "ssl-ca": keystone_ca_cert,
        }
        model.set_application_config(self.application_name, cfg)
        model.block_until_file_has_contents(
            self.application_name, "/etc/openstack/clouds.yaml", "auth_url"
        )
        model.block_until_file_has_contents(
            self.application_name, ".ssh/id_rsa_cloudsupport", "KEY"
        )

    def test_20_create_instance(self):
        """Test: create an instance."""
        res = model.run_action(
            self.unit_name,
            "create-test-instances",
            action_params={
                "nodes": self.hypervisors[0].hypervisor_hostname,
                "vcpus": 1,
                "vnfspecs": False,
            },
        )

        self.assertEqual(res.status, "completed")
        self.assertEqual(res.results["Code"], "0")
        self.assertNotIn("error", res.results["create-results"])
        test_instances = self.get_test_instances()
        self.assert_(test_instances)
        for instance in test_instances:
            self.wait_for_server(instance.id, "ACTIVE")

    def test_25_test_connectivity(self):
        """Test: connectivity of an instance."""
        res = model.run_action(
            self.unit_name,
            "test-connectivity",
        )
        self.assertEqual(res.status, "completed")

    def test_35_test_get_ssh_cmd(self):
        """Verify get-ssh-cmd action complete successfully."""
        res = model.run_action(
            self.unit_name,
            "get-ssh-cmd",
        )
        self.assertEqual(res.status, "completed")

    def test_45_delete_instance_no_match(self):
        """Test: delete-instance action, non-matching pattern."""
        res = model.run_action(
            self.unit_name,
            "delete-test-instances",
            action_params={
                "nodes": self.hypervisors[0].hypervisor_hostname,
                "pattern": "nomatchxxxx",
            },
        )
        self.assertEqual(res.status, "completed")
        self.assert_(self.get_test_instances())

    def test_50_delete_instance(self):
        """Test: delete-instance action."""
        res = model.run_action(
            self.unit_name,
            "delete-test-instances",
            action_params={"nodes": self.hypervisors[0].hypervisor_hostname},
        )
        self.assertEqual(res.status, "completed")

        @tenacity.retry(
            stop=tenacity.stop_after_attempt(10),
            wait=tenacity.wait_fixed(1),
            retry=tenacity.retry_if_result(bool),
        )
        def testfunc():
            test_inst = self.get_test_instances()
            return test_inst

        self.assertFalse(testfunc())

    def test_55_nrpe_check(self):
        """Verify nrpe check exists."""
        nagios_plugin = "/usr/local/lib/nagios/plugins/stale_server_check.py"
        cloud_name = "cloud1"
        name_prefix = "cloudsupport-test"
        expected_nrpe_check = (
            "command[check_stale_server]={} --cloud-name {} --name-prefix {} "
            "--warn-days 7 --crit-days 14".format(
                nagios_plugin, cloud_name, name_prefix
            )
        )

        cmd = "cat /etc/nagios/nrpe.d/check_stale_server.cfg"
        result = model.run_on_unit(self.unit_name, cmd)
        code = result.get("Code")
        if code != "0":
            raise model.CommandRunFailed(cmd, result)
        content = result.get("Stdout")
        self.assertTrue(expected_nrpe_check in content)

        # Verify it returns ok.
        cmd = "{} --cloud-name {} --name-prefix {} --warn-days 7 --crit-days 14".format(
            nagios_plugin, cloud_name, name_prefix
        )
        result = model.run_on_unit(self.unit_name, cmd)
        code = result.get("Code")
        if code != "0":
            raise model.CommandRunFailed(cmd, result)
