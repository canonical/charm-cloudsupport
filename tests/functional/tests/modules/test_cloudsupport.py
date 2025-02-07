# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test deployment and functionality of the cloudsupport charm."""

import json
import logging
import os
import textwrap
import time
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_fixed

from tests.modules import test_utils

import zaza.openstack.charm_tests.test_utils as openstack_test_utils
import zaza.openstack.utilities.openstack as openstack_utils
import zaza.utilities.deployment_env as deployment_env
from zaza import model

logger = logging.getLogger(__name__)


def gen_clouds_yaml(creds_dict):
    """Generate and return the clouds.yaml content."""
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
        if len(cls.hypervisors) < 1:
            raise Exception("No hypervisors found in test cloud")

    def get_test_instances(self):
        """Get instances that look like our test instance."""
        return [
            vm for vm in self.nova_client.servers.list() if vm.name.startswith("cloudsupport-test")
        ]

    def delete_test_instances(self):
        """Delete all test instances."""
        for vm in self.get_test_instances():
            self.nova_client.servers.delete(vm)

    def run_action_on_unit(self, name, **params):
        """Run action on unit."""
        result = model.run_action(self.unit_name, name, action_params=params)
        logger.info(
            "action `%s` result: %s%s%s",
            name,
            str(result.status),
            os.linesep,
            json.dumps(result.results, indent=2),
        )
        return result

    def wait_for_server(self, server_id, status, timeout=300):
        """Wait for server status."""
        logger.info("waits for server %s to reach status %s", server_id, status)
        start_time = time.time()
        while time.time() - start_time < timeout:
            current_status = self.nova_client.servers.get(server_id).status
            logger.info("server %s is in %s status", server_id, current_status)
            if current_status == status:
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

    # Retry upto 5 minutes, because sometimes http server error occurs
    # while creating the instance.
    @retry(stop=stop_after_attempt(15), wait=wait_fixed(20))
    def test_20_create_instance(self):
        """Test: create an instance."""
        self.delete_test_instances()  # remove instances from the previous try
        result = self.run_action_on_unit(
            "create-test-instances",
            nodes=self.hypervisors[0].hypervisor_hostname,
            vcpus=1,
            vnfspecs=False,
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.results.get("return-code"), 0)
        self.assertEqual(result.results.get("create-results"), "success")
        details = result.results.get("create-details").replace("'", '"')
        _, server_id, _ = json.loads(details)[0]
        self.wait_for_server(server_id, "ACTIVE")

    # Retry upto 6 minutes because the network connection may fail in the beginning.
    @retry(stop=stop_after_attempt(18), wait=wait_fixed(20))
    def test_25_test_connectivity(self):
        """Test: connectivity of an instance."""
        # Workaround on CI environment that the DNS can not resolve the
        # hostname of the dhcp_agent/hypervisor machine.
        try:
            # Is OVS
            model.get_application("neutron-gateway")
            app = "neutron-gateway"
        except KeyError:
            # Is OVN
            app = "nova-compute"
        host_ip = model.get_app_ips(app)[0]
        host = model.run_on_unit(f"{app}/0", "hostname").get("Stdout").rstrip()
        cmd = f"""echo "{host_ip} {host}" >> /etc/hosts """
        model.run_on_unit(self.unit_name, cmd)

        result = self.run_action_on_unit("test-connectivity")
        self.assertEqual(result.status, "completed")

    def test_30_stop_vms_enabled_compute_node(self):
        """Test: stop all VMs on enabled compute-node."""
        host = self.hypervisors[0].hypervisor_hostname
        result = self.run_action_on_unit(
            "stop-vms",
            **{"i-really-mean-it": True, "compute-node": host},
        )
        self.assertEqual(result.status, "failed")
        self.assertIn(host, result.message)

    def test_35_stop_vms(self):
        """Test: stop all VMs on disabled compute-node."""
        model.run_action("nova-compute/0", "disable")  # disable compute node
        self.addCleanup(model.run_action, "nova-compute/0", "enable")  # clean up
        host = self.hypervisors[0].hypervisor_hostname
        result = self.run_action_on_unit(
            "stop-vms",
            **{"i-really-mean-it": True, "compute-node": host},
        )
        self.assertEqual(result.status, "completed")
        raw_stopped_vms = result.results.get("stopped-vms", "[]")
        stopped_vms = json.loads(raw_stopped_vms.replace("'", '"'))
        self.assertEqual(len(stopped_vms), 1)
        # Note (rgildein): ensure that test-vm is shut-off at the end of the test
        self.wait_for_server(stopped_vms[0], "SHUTOFF")

    def test_40_start_vms(self):
        """Test: start all stopped VMs."""
        host = self.hypervisors[0].hypervisor_hostname
        # test run action start-vms
        result = self.run_action_on_unit(
            "start-vms",
            **{"i-really-mean-it": True, "compute-node": host},
        )
        raw_started_vms = result.results.get("started-vms", "[]")
        started_vms = json.loads(raw_started_vms.replace("'", '"'))
        self.assertEqual(len(started_vms), 1)
        self.assertEqual(result.status, "completed")
        self.wait_for_server(started_vms[0], "ACTIVE")

    def test_50_test_get_ssh_cmd(self):
        """Verify get-ssh-cmd action complete successfully."""
        result = self.run_action_on_unit("get-ssh-cmd")
        self.assertEqual(result.status, "completed")

    def test_60_delete_instance_no_match(self):
        """Test: delete-instance action, non-matching pattern."""
        result = self.run_action_on_unit(
            "delete-test-instances",
            nodes=self.hypervisors[0].hypervisor_hostname,
            pattern="nomatchxxxx",
        )
        self.assertEqual(result.status, "completed")
        self.assertTrue(self.get_test_instances())

    def test_70_delete_instance(self):
        """Test: delete-instance action."""
        result = self.run_action_on_unit(
            "delete-test-instances",
            nodes=self.hypervisors[0].hypervisor_hostname,
        )
        self.assertEqual(result.status, "completed")

        try_count = 0
        while len(self.get_test_instances()) > 0 and try_count < 60:
            time.sleep(5)
            try_count += 1

        self.assertFalse(self.get_test_instances())  # test that the list is empty

    def test_75_nrpe_check(self):
        """Verify nrpe check exists."""
        nagios_plugin = "/usr/local/lib/nagios/plugins/stale_server_check.py"
        cloud_name = "cloud1"
        name_prefix = "cloudsupport-test"
        expected_nrpe_check = (
            "command[check_stale_server]={} --cloud-name {} --name-prefix {} "
            "--warn-days 7 --crit-days 14".format(nagios_plugin, cloud_name, name_prefix)
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
