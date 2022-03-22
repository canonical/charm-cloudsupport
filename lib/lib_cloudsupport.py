#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
# See LICENSE file for licensing details.

"""Cloud support library."""

import logging
import pathlib

from charmhelpers.contrib.charmsupport.nrpe import NRPE

from ops.model import ActiveStatus

import os
import os_testing


NAGIOS_PLUGINS_DIR = "/usr/local/lib/nagios/plugins/"


class Paths:
    """Namespace for path constants."""

    CLOUDS_YAML = pathlib.Path("/etc/openstack/clouds.yaml")
    CA_FILE = pathlib.Path("ssl_ca.crt")
    SSH_KEY = pathlib.Path(os_testing.TEST_SSH_KEY)


class CloudSupportHelper:
    """Cloud support helper object."""

    def __init__(self, model):
        """Construct the helper."""
        self.model = model
        self.charm_config = model.config

    @property
    def plugins_dir(self):
        """Get nagios plugins directory."""
        return NAGIOS_PLUGINS_DIR

    @property
    def check_stale_server(self):
        return self.charm_config.get("stale_server_check")

    def verify_config(self):
        """Verify configurations."""
        logging.debug("verifying config: {}".format(self.charm_config))
        return bool(self.charm_config["clouds-yaml"])

    def write_configs(self):
        """Write out config files."""
        logging.debug("Writing configs: {}".format(self.charm_config))
        Paths.CLOUDS_YAML.parent.mkdir(exist_ok=True)
        Paths.CLOUDS_YAML.touch(mode=0o600, exist_ok=True)
        Paths.CLOUDS_YAML.chmod(0o600)
        with Paths.CLOUDS_YAML.open("w") as fp:
            fp.write(self.charm_config["clouds-yaml"])
        with Paths.CA_FILE.open("w") as fp:
            fp.write(self.charm_config["ssl_ca"])
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
        charm_plugin_dir = os.path.join(hookenv.charm_dir(), "files", "plugins/")
        host.rsync(charm_plugin_dir, self.plugins_dir, options=["--executability"])

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

        name_prefix = self.charm_config.get("name-prefix")
        stale_name_prefix = self.charm_config.get("stale_name_prefix")
        if stale_name_prefix:
            name_prefix = stale_name_prefix
        warn_days = self.charm_config.get("stale_warn_days")
        crit_days = self.charm_config.get("stale_crit_days")
        project_uuids = self.charm_config.get("stale_project_uuids")

        check_cmd = (
            "{} --name-prefix {} --warn_days {} --crit_days {}".format(  # NOQA: E501
                check_script, name_prefix, warn_days, crit_days
            )
        )

        if project_uuids:
            check_cmd = "{} --project_uuids{}".format(check_cmd, project_uuids)

        nrpe.add_check(
            shortname=shortname,
            description="Check for stale test servers",
            check_cmd=check_cmd,
        )
        nrpe.write()
