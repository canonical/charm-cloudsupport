#!/usr/bin/env python3
# Copyright 2022 Canonical
# See LICENSE file for licensing details.
"""Unittests for charm-cloudsupport."""
import unittest
from unittest import mock
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

    def test_init(self):
        """Test initialization of charm."""
        self.assertEqual(self.charm.unit.status.name, "active")
        self.assertEqual(self.charm.unit.status.message, "Unit is ready")


class TestCloudSupportCharmActions(unittest.TestCase):
    """Charm actions unittest TestCase."""

    def setUp(self):
        self.harness = Harness(charm.CloudSupportCharm)
        self.harness.begin()
        self.charm = self.harness.charm
        self.helper = self.harness.charm.helper = MagicMock()
        self.action_get = self.harness._backend.action_get = MagicMock()
        self.action_set = self.harness._backend.action_set = MagicMock()
        self.action_fail = self.harness._backend.action_fail = MagicMock()

    def _mock_juju_action_name(self, name: str):
        """Mock environment variable JUJU_ACTION_NAME."""
        patcher = mock.patch("os.environ")
        mock_environ = patcher.start()
        mock_environ.get.return_value = name
        self.addCleanup(patcher.stop)

    def test_on_stop_vms(self):
        """Test stop-vms action."""
        self._mock_juju_action_name("stop-vms")
        self.action_get.return_value = {
            "i-really-mean-it": True,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
        }
        self.helper.stop_vms.return_value = ([1, 2, 3, 4], [5])

        # emit action
        self.charm.on.stop_vms_action.emit()
        self.helper.stop_vms.assert_called_once_with("test-node", "test-cloud")
        assert self.charm.state.stopped_vms == [1, 2, 3, 4]
        self.action_set.assert_called_once_with(
            {"stopped-vms": [1, 2, 3, 4], "failed-to-stop": [5]}
        )

    def test_on_stop_vms_without_disabled_compute_node(self):
        """Test stop-vms action, when compute node is not disabled."""
        self._mock_juju_action_name("stop-vms")
        self.action_get.return_value = {
            "i-really-mean-it": True,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
        }
        self.helper.stop_vms.side_effect = CloudSupportError("test-message")
        # emit action
        self.charm.on.stop_vms_action.emit()
        self.helper.stop_vms.assert_called_once_with("test-node", "test-cloud")
        self.action_fail.assert_called_once_with("test-message")

    def test_on_start_vms(self):
        """Test start-vms actions."""
        self._mock_juju_action_name("start-vms")
        self.charm.state.stopped_vms = [1, 2, 3, 4, 5]
        self.helper.start_vms.return_value = ([1, 2, 3, 4], [5])
        self.action_get.return_value = {
            "i-really-mean-it": True,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
        }
        # emit action
        self.charm.on.start_vms_action.emit()
        self.helper.start_vms.assert_called_once_with(
            "test-node", [1, 2, 3, 4, 5], False, "test-cloud"
        )
        assert self.charm.state.stopped_vms == []
        self.action_set.assert_called_once_with(
            {"started-vms": [1, 2, 3, 4], "failed-to-start": [5]}
        )

    def test_on_start_vms_with_force_all(self):
        """Test start-vms actions."""
        self._mock_juju_action_name("start-vms")
        self.charm.state.stopped_vms = [1, 2, 3, 4, 5]
        self.helper.start_vms.return_value = ([1, 2, 3, 4], [5])
        self.action_get.return_value = {
            "i-really-mean-it": True,
            "compute-node": "test-node",
            "cloud-name": "test-cloud",
            "force-all": True,
        }
        # emit action
        self.charm.on.start_vms_action.emit()
        self.helper.start_vms.assert_called_once_with(
            "test-node", [1, 2, 3, 4, 5], True, "test-cloud"
        )
        assert self.charm.state.stopped_vms == []
        self.action_set.assert_called_once_with(
            {"started-vms": [1, 2, 3, 4], "failed-to-start": [5]}
        )
