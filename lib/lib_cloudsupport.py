#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
# See LICENSE file for licensing details.

"""Cloud support library."""

import logging
import os
import pathlib
import shutil

from charmhelpers import fetch
from charmhelpers.contrib.charmsupport.nrpe import NRPE

from openstack.exceptions import SDKException

from ops.model import ActiveStatus

import os_testing
from os_testing import CloudSupportError, con

NAGIOS_PLUGINS_DIR = "/usr/local/lib/nagios/plugins/"


class Paths:
    """Namespace for path constants."""

    CLOUDS_YAML = pathlib.Path("/etc/openstack/clouds.yaml")
    CA_FILE = pathlib.Path("/etc/openstack/ssl_ca.crt")
    SSH_KEY = pathlib.Path(os_testing.TEST_SSH_KEY)


class CloudSupportHelper:
    """Cloud support helper object."""

    def __init__(self, model, charm_dir):
        """Construct the helper."""
        self.model = model
        self.charm_config = model.config
        self.charm_dir = charm_dir

    @property
    def plugins_dir(self):
        """Get nagios plugins directory."""
        return NAGIOS_PLUGINS_DIR

    @property
    def check_stale_server(self):
        """Get the stale-server-check config option value."""
        return self.charm_config.get("stale-server-check")

    @property
    def cloud_name(self):
        """Get the cloud-name config option value."""
        return self.charm_config.get("cloud-name")

    def install_dependencies(self):
        """Install charm dependencies."""
        fetch.apt_install(["python3-openstackclient"], fatal=True)

    def verify_config(self):
        """Verify configurations."""
        logging.debug("verifying config: {}".format(self.charm_config))
        return bool(self.charm_config["clouds-yaml"])

    def write_configs(self):
        """Write out config files."""
        logging.debug("Writing configs: {}".format(self.charm_config))
        Paths.CLOUDS_YAML.parent.mkdir(exist_ok=True)
        Paths.CLOUDS_YAML.touch(exist_ok=True)
        # allow read to anyone for nagios check
        Paths.CLOUDS_YAML.chmod(0o604)
        Paths.CA_FILE.touch(exist_ok=True)
        # allow read to anyone for nagios check
        Paths.CA_FILE.chmod(0o604)

        with Paths.CLOUDS_YAML.open("w") as fp:
            fp.write(self.charm_config["clouds-yaml"])
        with Paths.CA_FILE.open("w") as fp:
            fp.write(self.charm_config["ssl-ca"])
        Paths.SSH_KEY.parent.mkdir(exist_ok=True)
        Paths.SSH_KEY.touch(mode=0o600, exist_ok=True)
        Paths.SSH_KEY.chmod(0o600)
        with Paths.SSH_KEY.open("w") as fp:
            fp.write(self.charm_config["ssh-key"])

    def update_config(self):
        """Update configuration."""
        if self.verify_config():
            self.write_configs()
            self.model.unit.status = ActiveStatus("Unit is ready")
        else:
            self.model.unit.status = ActiveStatus("Set config values")

        if self.check_stale_server:
            self.render_nrpe_checks()

    def update_plugins(self):
        """Copy nagios plugin into the unit."""
        charm_plugin_dir = os.path.join(self.charm_dir, "files", "plugins/")
        shutil.copy2(
            os.path.join(charm_plugin_dir, "stale_server_check.py"),
            os.path.join(self.plugins_dir, "stale_server_check.py"),
        )

    def render_nrpe_checks(self):
        """Render nrpe checks."""
        nrpe = NRPE()
        os.makedirs(self.plugins_dir, exist_ok=True)
        self.update_plugins()
        shortname = "stale_server"
        check_script = os.path.join(self.plugins_dir, "stale_server_check.py")

        if not self.check_stale_server:
            nrpe.remove_check(shortname=shortname)
            return

        stale_name_prefix = self.charm_config.get("name-prefix")
        warn_days = self.charm_config.get("stale-warn-days")
        crit_days = self.charm_config.get("stale-crit-days")
        check_cmd = (
            "{} --cloud-name {}  "
            "--name-prefix {}  "
            "--warn-days {} "
            "--crit-days {} ".format(
                check_script, self.cloud_name, stale_name_prefix, warn_days, crit_days
            )
        )

        ignored_servers = self.charm_config.get("stale-ignored-uuids")
        if ignored_servers:
            check_cmd += "--ignored-servers-uuids {}".format(ignored_servers)

        nrpe.add_check(
            shortname=shortname,
            description="Check for stale test servers",
            check_cmd=check_cmd,
        )
        nrpe.write()

    @staticmethod
    def _check_compute_node(cloud_name, compute_node, status):
        """Check if compute-node service exists."""
        for service in con(cloud_name).compute.hypervisors():
            if service.name == compute_node and service.status == status:
                return True

        return False

    def stop_vms(self, compute_node, cloud_name=None):
        """Stop all VMs on compute node.

        :param compute_node:  name of the compute node registered in cloud
        :type compute_node: str
        :param cloud_name: name of the cloud defined in `clouds-yaml` configuration
        :type cloud_name: Optional[str]
        """
        stopped_vms = []
        failed_to_stop = []
        cloud_name = cloud_name or self.cloud_name
        if not self._check_compute_node(cloud_name, compute_node, "disabled"):
            raise CloudSupportError(
                "Please disable host `{}` before stop vms".format(compute_node)
            )
        vms = con(cloud_name).compute.servers(
            host=compute_node, all_tenants=True, status="ACTIVE"
        )
        for vm in vms:
            try:
                logging.debug("stopping VM: %s(%s)", vm.name, vm.id)
                con(cloud_name).compute.stop_server(vm.id)
                stopped_vms.append(vm.id)
            except SDKException as error:
                logging.warning("failed to stop VM %s with error: %s", vm.id, error)
                failed_to_stop.append(vm.id)

        return stopped_vms, failed_to_stop

    def start_vms(self, compute_node, stopped_vms, force_all=False, cloud_name=None):
        """Start all VMs on compute node.

        :param compute_node:  name of the compute node registered in cloud
        :type compute_node: str
        :param stopped_vms: list of VM IDs that were stopped by the stop-vms action
        :type stopped_vms: List[str]
        :param force_all: force all VMs to start
        :type force_all: bool
        :param cloud_name: name of the cloud defined in `clouds-yaml` configuration
        :type cloud_name: Optional[str]
        """
        started_vms = []
        failed_to_start = []
        cloud_name = cloud_name or self.cloud_name
        vms = con(cloud_name).compute.servers(
            host=compute_node, all_tenants=True, status="SHUTOFF"
        )
        for vm in vms:
            if force_all is False and vm.id not in stopped_vms:
                # skip all VMs that have not been stopped
                continue
            try:
                logging.debug("starting VM: %s(%s)", vm.name, vm.id)
                con(cloud_name).compute.start_server(vm.id)
                started_vms.append(vm.id)
            except SDKException as error:
                logging.warning("failed to start VM %s with error: %s", vm.id, error)
                failed_to_start.append(vm.id)

        return started_vms, failed_to_start
