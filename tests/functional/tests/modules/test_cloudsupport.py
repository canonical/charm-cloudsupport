"""Test deployment and functionality of the cloudsupport charm."""
import textwrap
import unittest
import urllib
from pathlib import Path

import tenacity

from tests.modules import test_utils

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


class TestBase(unittest.TestCase):
    """Base class for functional charm tests."""

    @classmethod
    def setUpClass(cls):
        """Run setup for tests."""
        cls.model_name = model.get_juju_model()
        cls.app_name = "cloudsupport"
        cls.unit_name = "cloudsupport/0"
        sess = openstack_utils.get_overcloud_keystone_session()
        cls.nova = openstack_utils.get_nova_session_client(sess)
        cls.glance = openstack_utils.get_glance_session_client(sess)
        cls.hypervisors = cls.nova.hypervisors.list()
        if len(cls.hypervisors) < 1:
            raise Exception("No hypervisors found in test cloud")
        image_attrs = {
            "name": "cloudsupport-image",
            "disk_format": "qcow2",
            "container_format": "bare",
            "visibility": "public",
        }
        cls.image = cls.glance.images.create(**image_attrs)
        uri = "http://download.cirros-cloud.net/0.5.2/cirros-0.5.2-x86_64-disk.img"
        with urllib.request.urlopen(uri) as f:
            cls.glance.images.upload(cls.image.id, f)

    @classmethod
    def tearDownClass(cls) -> None:
        """Clean up: delete test image."""
        cls.glance.images.delete(cls.image.id)


class CloudSupportTests(TestBase):
    """Test cloudsupport related functionality."""

    def test_10_configure(self):
        """Test: perform configuration."""
        clouds = gen_clouds_yaml(openstack_utils.get_overcloud_auth())
        keystone_ca_cert_path = openstack_utils.get_remote_ca_cert_file('keystone')
        with open(keystone_ca_cert_path) as f:
            keystone_ca_cert = f.read()
        priv_key = test_utils.get_priv_key(Path(deployment_env.get_tmpdir()))
        cfg = {
            "clouds-yaml": clouds,
            "ssh-key": priv_key,
            "ram": "1024",
            "disk": "2",
            "cidr": "192.168.77.0/26",
            "stale-server-check": "true",
            "ssl-ca": keystone_ca_cert
        }
        model.set_application_config(self.app_name, cfg)
        model.block_until_file_has_contents(
            self.app_name, "/etc/openstack/clouds.yaml", "auth_url"
        )
        model.block_until_file_has_contents(
            self.app_name, ".ssh/id_rsa_cloudsupport", "KEY"
        )

    def get_test_instances(self):
        """Get instances that look like our test instance."""
        return [
            s
            for s in self.nova.servers.list()
            if s.name.startswith("cloudsupport-test")
        ]

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
        self.assert_(self.get_test_instances())

    def test_25_test_connectivity(self):
        """Test: connectivity of an instance."""
        res = model.run_action(
            self.unit_name,
            "test-connectivity",
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
