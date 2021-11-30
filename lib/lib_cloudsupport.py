#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
# See LICENSE file for licensing details.

"""Cloud support library."""

import logging
import pathlib

from ops.model import ActiveStatus


class Paths:
    """Namespace for path constants."""

    CLOUDS_YAML = pathlib.Path("/etc/openstack/clouds.yaml")
    CA_FILE = pathlib.Path("ssl_ca.crt")
    SSH_KEY = pathlib.Path(".ssh/id_rsa_cloudsupport")


class CloudSupportHelper:
    """Cloud support helper object."""

    def __init__(self, model):
        """Construct the helper."""
        self.model = model
        self.charm_config = model.config

    def verify_config(self):
        """Verify configurations."""
        required = {
            "clouds-yaml",
            "ssl_ca",
        }
        logging.debug("verifying config: {}".format(self.charm_config))
        return required.issubset(self.charm_config)

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
