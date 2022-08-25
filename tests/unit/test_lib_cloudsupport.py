#!/usr/bin/env python3
# Copyright 2022 Canonical
# See LICENSE file for licensing details.
"""Unittests for lib-cloudsupport."""
import unittest
from unittest import mock
from unittest.mock import MagicMock, call

import lib_cloudsupport
from lib_cloudsupport import CloudSupportHelper

from openstack.exceptions import SDKException

from os_testing import CloudSupportError

import pytest


class TestCloudSupportHelper(unittest.TestCase):
    """TestCase for CloudSupportHelper."""

    def _mock_con(self, hypervisors=None, servers=None):
        """Mock openstack connection."""
        mocker_os_testing_con = mock.patch.object(lib_cloudsupport, "con")
        mock_con = mocker_os_testing_con.start()
        mock_openstack = mock_con.return_value = MagicMock()
        mock_openstack.compute.hypervisors.return_value = hypervisors or []
        mock_openstack.compute.servers.return_value = servers or []
        self.addCleanup(mocker_os_testing_con.stop)
        return mock_openstack

    def test_check_compute_node_no_services(self):
        """Check test of existing compute-node."""
        self._mock_con(hypervisors=[])
        self.assertFalse(
            CloudSupportHelper._check_compute_node("test-cloud", "test-node", "active")
        )

    def test_check_compute_node_exists(self):
        """Check test of existing compute-node."""
        service = MagicMock()  # name needs to be set with configure_mock
        service.configure_mock(name="test-node", status="active")
        self._mock_con(hypervisors=[service])
        self.assertTrue(
            CloudSupportHelper._check_compute_node("test-cloud", "test-node", "active")
        )

    def test_check_compute_node_not_exists(self):
        """Check test of non-existing compute-node."""
        service = MagicMock()  # name needs to be set with configure_mock
        service.configure_mock(name="different-test-node", status="active")
        self._mock_con(hypervisors=[service])
        self.assertFalse(
            CloudSupportHelper._check_compute_node("test-cloud", "test-node", "active")
        )

    def test_check_compute_node_different_status(self):
        """Check test of non-existing compute-node."""
        service = MagicMock()  # name needs to be set with configure_mock
        service.configure_mock(name="test-node", status="active")
        self._mock_con(hypervisors=[service])
        self.assertFalse(
            CloudSupportHelper._check_compute_node(
                "test-cloud", "test-node", "disabled"
            )
        )

    def test_stop_vms_compute_node_not_disabled(self):
        """Try to stop VMs on enabled compute-node."""
        helper = CloudSupportHelper(MagicMock(), MagicMock())
        with mock.patch.object(helper, "_check_compute_node", return_value=False):
            with pytest.raises(CloudSupportError):
                helper.stop_vms("test-node")

    def test_stop_vms_compute_node_no_vms(self):
        """No VMs on compute-node."""
        helper = CloudSupportHelper(MagicMock(), MagicMock())
        openstack = self._mock_con(servers=[])
        with mock.patch.object(helper, "_check_compute_node", return_value=True):
            stopped_vms, failed_to_stop = helper.stop_vms("test-node")

        openstack.compute.servers.assert_called_once_with(
            host="test-node", all_tenants=True, status="ACTIVE"
        )
        self.assertEqual(stopped_vms, [])
        self.assertEqual(failed_to_stop, [])

    def test_stop_vms(self):
        """Stop VMs without any error."""
        helper = CloudSupportHelper(MagicMock(), MagicMock())
        openstack = self._mock_con(
            servers=[
                MagicMock(id=1, name="vm-1"),
                MagicMock(id=2, name="vm-2"),
                MagicMock(id=3, name="vm-3"),
                MagicMock(id=4, name="vm-4"),
            ]
        )
        with mock.patch.object(helper, "_check_compute_node", return_value=True):
            stopped_vms, failed_to_stop = helper.stop_vms("test-node")

        openstack.compute.stop_server.assert_has_calls(
            [call(1), call(2), call(3), call(4)]
        )
        self.assertEqual(stopped_vms, [1, 2, 3, 4])
        self.assertEqual(failed_to_stop, [])

    def test_stop_vms_with_error(self):
        """Stop VMs with error."""
        helper = CloudSupportHelper(MagicMock(), MagicMock())
        openstack = self._mock_con(
            servers=[
                MagicMock(id=1, name="vm-1"),
                MagicMock(id=2, name="vm-2"),
            ]
        )
        openstack.compute.stop_server.side_effect = (None, SDKException)
        with mock.patch.object(helper, "_check_compute_node", return_value=True):
            stopped_vms, failed_to_stop = helper.stop_vms("test-node")

        openstack.compute.stop_server.assert_has_calls([call(1), call(2)])
        self.assertEqual(stopped_vms, [1])
        self.assertEqual(failed_to_stop, [2])

    def test_start_vms_no_vms(self):
        """No VMs on compute-node."""
        helper = CloudSupportHelper(MagicMock(), MagicMock())
        openstack = self._mock_con(servers=[])
        started_vms, failed_to_start = helper.start_vms("test-node", [1, 2])

        openstack.compute.servers.assert_called_once_with(
            host="test-node", all_tenants=True, status="SHUTOFF"
        )
        self.assertEqual(started_vms, [])
        self.assertEqual(failed_to_start, [])

    def test_start_vms(self):
        """Start VMs without any error."""
        helper = CloudSupportHelper(MagicMock(), MagicMock())
        openstack = self._mock_con(
            servers=[
                MagicMock(id=1, name="vm-1"),
                MagicMock(id=2, name="vm-2"),
                MagicMock(id=3, name="vm-3"),
                MagicMock(id=4, name="vm-4"),
            ]
        )
        started_vms, failed_to_start = helper.start_vms("test-node", [1, 2])
        openstack.compute.start_server.assert_has_calls([call(1), call(2)])
        self.assertEqual(started_vms, [1, 2])
        self.assertEqual(failed_to_start, [])

    def test_start_vms_with_error(self):
        """Start VMs without any error."""
        helper = CloudSupportHelper(MagicMock(), MagicMock())
        openstack = self._mock_con(
            servers=[
                MagicMock(id=1, name="vm-1"),
                MagicMock(id=2, name="vm-2"),
            ]
        )
        openstack.compute.start_server.side_effect = (None, SDKException)
        started_vms, failed_to_start = helper.start_vms("test-node", [1, 2])
        openstack.compute.start_server.assert_has_calls([call(1), call(2)])
        self.assertEqual(started_vms, [1])
        self.assertEqual(failed_to_start, [2])

    def test_start_vms_force_all(self):
        """Start all VMs on compute-node."""
        helper = CloudSupportHelper(MagicMock(), MagicMock())
        openstack = self._mock_con(
            servers=[
                MagicMock(id=1, name="vm-1"),
                MagicMock(id=2, name="vm-2"),
                MagicMock(id=3, name="vm-3"),
                MagicMock(id=4, name="vm-4"),
            ]
        )
        started_vms, failed_to_start = helper.start_vms(
            "test-node", [1, 2], force_all=True
        )
        openstack.compute.start_server.assert_has_calls(
            [call(1), call(2), call(3), call(4)]
        )
        self.assertEqual(started_vms, [1, 2, 3, 4])
        self.assertEqual(failed_to_start, [])
