#!/usr/bin/env python3
# Copyright 2022 Canonical
# See LICENSE file for licensing details.
"""Unittests for charm-cloudsupport."""
import os
import unittest
from unittest.mock import MagicMock

import charm

from ops.testing import Harness

from os_testing import CloudSupportError


class TestCloudSupportCharm(unittest.TestCase):
    """Charm unittest TestCase."""

    def setUp(self):
        self.harness = Harness(charm.CloudSupportCharm)
        self.harness.begin()
        self.charm = self.harness.charm
        self.charm.helper = self.mock_helper = MagicMock()

    def test_init(self):
        """Test initialization of charm."""
        self.assertEqual(self.charm.unit.status.name, "active")
        self.assertEqual(self.charm.unit.status.message, "Unit is ready")

    def test_verify_stop_start_event(self):
        """Test verify_stop_start_event."""
        # test missing i-really-mean-it parameter
        mock_action_event = MagicMock(params={"compute-node": "test"})
        result = self.charm._verify_stop_start_event(mock_action_event)
        self.assertFalse(result)
        mock_action_event.fail.assert_called_once_with(
            "i-really-mean-it is a required parameter"
        )
        # test missing compute-node parameter
        mock_action_event = MagicMock(params={"i-really-mean-it": True})
        result = self.charm._verify_stop_start_event(mock_action_event)
        self.assertFalse(result)
        mock_action_event.fail.assert_called_once_with(
            "parameter compute-node is missing"
        )
        # test passing
        mock_action_event = MagicMock(
            params={"i-really-mean-it": True, "compute-node": "test"}
        )
        result = self.charm._verify_stop_start_event(mock_action_event)
        self.assertTrue(result)

    def test_on_stop_vms(self):
        """Test stop-vms actions."""
        os.environ["JUJU_ACTION_NAME"] = "stop-vms"
        self.mock_helper.stop_vms.return_value = ([1, 2, 3, 4], [5])
        self.charm.framework.model._backend.action_get = mock_action_get = MagicMock()
        self.charm.framework.model._backend.action_set = mock_action_set = MagicMock()
        self.charm.framework.model._backend.action_fail = mock_action_fail = MagicMock()
        mock_action_get.return_value = {
            "i-really-mean-it": False,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
        }
        # test missing i-really-mean-it parameter
        self.charm.on.stop_vms_action.emit()
        self.mock_helper.stop_vms.assert_not_called()
        mock_action_fail.assert_called_once_with(
            "i-really-mean-it is a required parameter"
        )
        mock_action_fail.reset_mock()
        # test base functionality
        mock_action_get.return_value = {
            "i-really-mean-it": True,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
        }
        self.charm.on.stop_vms_action.emit()
        self.mock_helper.stop_vms.assert_called_once_with("test-node", "test-cloud")
        assert self.charm.state.stopped_vms == [1, 2, 3, 4]
        mock_action_set.assert_called_once_with(
            {"stopped-vms": [1, 2, 3, 4], "failed-to-stop": [5]}
        )
        # test nova-compute not disabled
        self.mock_helper.stop_vms.side_effect = CloudSupportError("test-message")
        self.charm.on.stop_vms_action.emit()
        mock_action_fail.assert_called_once_with("test-message")

    def test_on_start_vms(self):
        """Test stop-vms actions."""
        os.environ["JUJU_ACTION_NAME"] = "start-vms"
        self.charm.state.stopped_vms = [1, 2, 3, 4, 5]
        self.mock_helper.start_vms.return_value = ([1, 2, 3, 4], [5])
        self.charm.framework.model._backend.action_get = mock_action_get = MagicMock()
        self.charm.framework.model._backend.action_set = mock_action_set = MagicMock()
        self.charm.framework.model._backend.action_fail = mock_action_fail = MagicMock()
        mock_action_get.return_value = {
            "i-really-mean-it": False,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
        }
        # test missing i-really-mean-it parameter
        self.charm.on.start_vms_action.emit()
        self.mock_helper.stop_vms.assert_not_called()
        mock_action_fail.assert_called_once_with(
            "i-really-mean-it is a required parameter"
        )
        # test base functionality
        mock_action_get.return_value = {
            "i-really-mean-it": True,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
        }
        self.charm.on.start_vms_action.emit()
        self.mock_helper.start_vms.assert_called_once_with(
            "test-node", [1, 2, 3, 4, 5], "test-cloud"
        )
        assert self.charm.state.stopped_vms == []
        mock_action_set.assert_called_once_with(
            {"started-vms": [1, 2, 3, 4], "failed-to-start": [5]}
        )
        self.mock_helper.reset_mock()
        # test force-all
        mock_action_get.return_value = {
            "i-really-mean-it": True,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
            "force-all": True,
        }
        self.charm.on.start_vms_action.emit()
        self.mock_helper.start_vms.assert_called_once_with(
            "test-node", None, "test-cloud"
        )
