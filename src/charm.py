#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
# See LICENSE file for licensing details.
"""Operator charm main library."""
import logging

from lib_cloudsupport import CloudSupportHelper

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus

from os_testing import (
    create_instance,
    delete_instance,
    get_ssh_cmd,
    test_connectivity,
)


class CloudSupportCharm(CharmBase):
    """Operator charm class."""

    state = StoredState()

    def __init__(self, *args):
        """Initialize charm and configure states and events to observe."""
        super().__init__(*args)
        self.framework.observe(self.on.install, self.on_install)
        self.framework.observe(self.on.config_changed, self.on_config_changed)
        self.framework.observe(self.on.upgrade_charm, self.on_install)
        self.framework.observe(
            self.on.create_test_instances_action, self.on_create_test_instances
        )
        self.framework.observe(
            self.on.delete_test_instances_action, self.on_delete_test_instances
        )
        self.framework.observe(
            self.on.test_connectivity_action, self.on_test_connectivity
        )
        self.framework.observe(self.on.get_ssh_cmd_action, self.on_get_ssh_cmd)
        self.framework.observe(
            self.on.nrpe_external_master_relation_joined,
            self.on_nrpe_external_master_relation_joined,
        )
        self.framework.observe(
            self.on.nrpe_external_master_relation_departed,
            self.on_nrpe_external_master_relation_departed,
        )
        self.state.set_default(installed=False)
        self.state.set_default(nrpe_configured=False)
        self.helper = CloudSupportHelper(self.model, self.charm_dir)
        self.unit.status = ActiveStatus("Unit is ready")

    def on_install(self, event):
        """Install charm and perform initial configuration."""
        self.helper.update_config()
        self.helper.install_dependencies()
        self.state.installed = True

    def on_config_changed(self, event):
        """Reconfigure charm."""
        if not self.state.installed:
            logging.info(
                "Config changed called before install complete, deferring event: "
                "{}".format(event.handle)
            )
            event.defer()
            return
        self.helper.update_config()
        self.unit.status = ActiveStatus("Unit is ready")

    def on_create_test_instances(self, event):
        """Run create-test-instance action."""
        cfg = self.model.config
        nodes = event.params["nodes"].split(",")
        physnet = event.params.get("physnet")
        vcpus = event.params.get("vcpus", cfg["vcpus"])
        ram = event.params.get("ram", cfg["ram"])
        disk = event.params.get("disk", cfg["disk"])
        vnfspecs = event.params.get("vnfspecs")
        key_name = event.params.get("key-name", cfg.get("key-name"))
        try:
            create_results = create_instance(
                nodes,
                vcpus,
                ram,
                disk,
                cfg["image"],
                cfg["name-prefix"],
                cfg["cidr"],
                physnet=physnet,
                vnfspecs=vnfspecs,
                key_name=key_name,
                cloud_name=self.helper.cloud_name,
            )
        except BaseException as err:
            event.set_results({"error": err})
            raise
        errs = any([a for a in create_results if a[0] == "error"])
        event.set_results(
            {
                "create-results": "success" if not errs else "error",
                "create-details": create_results,
            }
        )

    def on_delete_test_instances(self, event):
        """Run delete-test-instance action."""
        nodes = event.params["nodes"].split(",")
        pattern = event.params["pattern"]
        delete_results = delete_instance(
            nodes, pattern, cloud_name=self.helper.cloud_name
        )
        event.set_results({"delete-results": delete_results})

    def on_test_connectivity(self, event):
        """Run test-connectivity action."""
        try:
            # workaround for old juju
            # on 2.7.x params is None when nothing is passed.
            if not event.params:
                instance = None
            else:
                instance = event.params.get("instance")
            test_results = test_connectivity(
                instance, cloud_name=self.helper.cloud_name
            )
        except BaseException as err:
            event.set_results({"error": err})
            raise
        event.set_results(test_results)

    def on_get_ssh_cmd(self, event):
        """Run get-ssh-cmd action."""
        try:
            # workaround for old juju
            # on 2.7.x params is None when nothing is passed.
            if not event.params:
                instance = None
            else:
                instance = event.params.get("instance")
            results = get_ssh_cmd(instance, cloud_name=self.helper.cloud_name)
        except BaseException as err:
            event.set_results({"error": err})
            raise
        event.set_results(results)

    def on_nrpe_external_master_relation_joined(self, event):
        """Handle nrpe-external-master relation joined."""
        self.state.nrpe_configured = True

    def on_nrpe_external_master_relation_departed(self, event):
        """Handle nrpe-external-master relation departed."""
        self.state.nrpe_configured = False


if __name__ == "__main__":
    main(CloudSupportCharm)
