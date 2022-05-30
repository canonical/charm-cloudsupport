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
    CloudSupportError,
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
        self.framework.observe(self.on.stop_vms_action, self.on_stop_vms)
        self.framework.observe(self.on.start_vms_action, self.on_start_vms)
        self.framework.observe(
            self.on.nrpe_external_master_relation_joined,
            self.on_nrpe_external_master_relation_joined,
        )
        self.framework.observe(
            self.on.nrpe_external_master_relation_departed,
            self.on_nrpe_external_master_relation_departed,
        )
        self.state.set_default(installed=False, nrpe_configured=False, stopped_vms=[])
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

    def _verify_stop_start_event(self, event):
        """Verify requirements of stop-vms/start-vms action."""
        if not event.params.get("i-really-mean-it"):
            event.fail("i-really-mean-it is a required parameter")
            return False
        if not event.params.get("compute-node"):
            event.fail("parameter compute-node is missing")
            return False
        return True

    def on_stop_vms(self, event):
        """Run stop-vms action."""
        if not self._verify_stop_start_event(event):
            return
        cloud_name = event.params.get("cloud-name")
        compute_node = event.params.get("compute-node")
        try:
            stopped_vms, failed_to_stop = self.helper.stop_vms(compute_node, cloud_name)
        except CloudSupportError as error:
            event.fail(str(error))
            return
        self.state.stopped_vms = stopped_vms  # stored IDs of all stopped VMs
        event.set_results(
            {
                "stopped-vms": stopped_vms,
                "failed-to-stop": failed_to_stop,
            }
        )

    def on_start_vms(self, event):
        """Run start-vms action."""
        if not self._verify_stop_start_event(event):
            return
        cloud_name = event.params.get("cloud-name")
        compute_node = event.params.get("compute-node")
        force_all = event.params.get("force-all")
        started_vms, failed_to_start = self.helper.start_vms(
            compute_node, self.state.stopped_vms if not force_all else None, cloud_name
        )
        self.state.stopped_vms = []  # clear stored IDs
        event.set_results(
            {"started-vms": started_vms, "failed-to-start": failed_to_start}
        )

    def on_nrpe_external_master_relation_joined(self, event):
        """Handle nrpe-external-master relation joined."""
        self.state.nrpe_configured = True

    def on_nrpe_external_master_relation_departed(self, event):
        """Handle nrpe-external-master relation departed."""
        self.state.nrpe_configured = False


if __name__ == "__main__":
    main(CloudSupportCharm)
