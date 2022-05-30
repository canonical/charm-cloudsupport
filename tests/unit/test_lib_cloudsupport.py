#!/usr/bin/env python3
# Copyright 2022 Canonical
# See LICENSE file for licensing details.
"""Unittests for lib-cloudsupport."""
import unittest
from unittest import mock
from unittest.mock import MagicMock, call

import charm

import lib_cloudsupport

from openstack.exceptions import SDKException

from ops.testing import Harness

from os_testing import CloudSupportError

import pytest


class TestCloudSupportLib(unittest.TestCase):
    """TestCase for cloudsupport lib script."""

    def setUp(self):
        harness = Harness(charm.CloudSupportCharm)
        harness.begin()
        harness.update_config(
            {"clouds-yaml": {"test-cloud": {"auth_url": "http://127.0.0.1:5000/v3"}}}
        )
        # mock openstack connection
        mocker_os_testing_con = mock.patch.object(lib_cloudsupport, "con")
        self.mock_con = mocker_os_testing_con.start()
        self.mock_con.return_value = self.openstack = MagicMock()
        self.addCleanup(mocker_os_testing_con.stop)
        self.helper = lib_cloudsupport.CloudSupportHelper(
            harness.model, harness.charm.charm_dir
        )

    def test_check_compute_node_service(self):
        """Test function to test compute node service."""
        # no services
        self.openstack.compute.services.return_value = []
        self.assertFalse(
            self.helper._check_compute_node_service("test-cloud", "test-node")
        )
        # no service with binary nova-compute
        self.openstack.compute.services.return_value = [
            MagicMock(binary="no-nova-compute", host="test-node")
        ]
        self.assertFalse(
            self.helper._check_compute_node_service("test-cloud", "test-node")
        )
        # no nova-compute service with name test-node
        self.openstack.compute.services.return_value = [
            MagicMock(binary="nova-compute", host="diff-node")
        ]
        self.assertFalse(
            self.helper._check_compute_node_service("test-cloud", "test-node")
        )
        # nova-compute service with right host
        self.openstack.compute.services.return_value = [
            MagicMock(binary="nova-compute", host="test-node")
        ]
        self.assertTrue(
            self.helper._check_compute_node_service("test-cloud", "test-node")
        )
        # nova-compute service with right host and wrong status
        self.openstack.compute.services.return_value = [
            MagicMock(binary="nova-compute", host="test-node", status="disabled")
        ]
        self.assertFalse(
            self.helper._check_compute_node_service(
                "test-cloud", "test-node", "enabled"
            )
        )
        # nova-compute service with right host and right status
        self.openstack.compute.services.return_value = [
            MagicMock(binary="nova-compute", host="test-node", status="enabled")
        ]
        self.assertTrue(
            self.helper._check_compute_node_service(
                "test-cloud", "test-node", "enabled"
            )
        )

    def test_stop_vms(self):
        """Test stop VMs."""
        self.openstack.compute.services.return_value = [
            MagicMock(binary="nova-compute", host="test-node", status="disabled")
        ]
        self.openstack.compute.servers.return_value = [
            MagicMock(id=i, name="test-{}".format(i)) for i in range(3)
        ]
        # test successful to stop VM
        result = self.helper.stop_vms("test-node", "test-cloud")
        self.assertTupleEqual(result, ([0, 1, 2], []))
        self.openstack.compute.stop_server.assert_has_calls([call(0), call(1), call(2)])
        self.openstack.compute.stop_server.reset_mock()
        # test failed to stop VM with ID == 1

        def stop_server(vm_id):
            if vm_id == 1:
                raise SDKException

        self.openstack.compute.stop_server.side_effect = stop_server
        result = self.helper.stop_vms("test-node", "test-cloud")
        self.assertTupleEqual(result, ([0, 2], [1]))
        self.openstack.compute.stop_server.assert_has_calls([call(0), call(1), call(2)])
        # test failed to stop VM with nova-compute not disabled
        self.openstack.compute.services.return_value = [
            MagicMock(binary="nova-compute", host="test-node", status="enabled")
        ]
        with pytest.raises(CloudSupportError):
            self.helper.stop_vms("test-node", "test-cloud")

    def test_start_vms(self):
        """Test start VMs."""
        self.openstack.compute.services.return_value = [
            MagicMock(binary="nova-compute", host="test-node", status="disabled")
        ]
        self.openstack.compute.servers.return_value = [
            MagicMock(id=i, name="test-{}".format(i)) for i in range(5)
        ]
        # start all VMs
        result = self.helper.start_vms("test-node", [0, 1, 2, 3, 4], "test-cloud")
        self.assertTupleEqual(result, ([0, 1, 2, 3, 4], []))
        self.openstack.compute.start_server.assert_has_calls(
            [call(i) for i in range(5)]
        )
        self.openstack.compute.start_server.reset_mock()
        # force all VMs
        result = self.helper.start_vms("test-node", None, "test-cloud")
        self.assertTupleEqual(result, ([0, 1, 2, 3, 4], []))
        self.openstack.compute.start_server.assert_has_calls(
            [call(i) for i in range(5)]
        )
        self.openstack.compute.start_server.reset_mock()
        # start only VM 0 and 2
        result = self.helper.start_vms("test-node", [0, 2], "test-cloud")
        self.assertTupleEqual(result, ([0, 2], []))
        self.openstack.compute.start_server.assert_has_calls([call(0), call(2)])
        self.openstack.compute.start_server.reset_mock()
        # start VM 0, 1, 2 and 1 failed to start

        def start_server(vm_id):
            if vm_id == 1:
                raise SDKException

        self.openstack.compute.start_server.side_effect = start_server
        result = self.helper.start_vms("test-node", [0, 1, 2], "test-cloud")
        self.assertTupleEqual(result, ([0, 2], [1]))
        self.openstack.compute.start_server.assert_has_calls(
            [call(0), call(1), call(2)]
        )
        self.openstack.compute.start_server.reset_mock()
