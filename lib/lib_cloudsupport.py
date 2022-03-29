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

from ops.model import ActiveStatus

import os_testing


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
        return self.charm_config.get("stale-server-check")

    @property
    def cloud_name(self):
        return self.charm_config.get("cloud-name")

    def install_dependencies(self):
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
