# !/usr/bin/env python3

# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unittests for charm-cloudsupport."""
from contextlib import contextmanager
from unittest import mock

import pytest
from os_testing import CloudSupportError


@contextmanager
def mock_juju_action(name):
    """Mock JUJU_ACTION_NAME environment variable."""
    patcher = mock.patch("os.environ")
    mock_environ = patcher.start()
    mock_environ.get.return_value = name
    try:
        yield name
    finally:
        patcher.stop()


def test_init_charm(charm):
    """Test initialization of charm."""
    assert charm.unit.status.name == "active"
    assert charm.unit.status.message == "Unit is ready"


@pytest.mark.parametrize("exp_result", [([1, 2, 3, 4], [5])])
def test_on_stop_vms(charm, action_set, action_get, exp_result):
    """Test stop-vms action."""
    action_get.return_value = {
        "i-really-mean-it": True,
        "compute-node": "test-node",
        "cloud-name": "test-cloud",
    }
    stopped_vms, failed_to_stop = exp_result
    charm.helper.stop_vms.return_value = exp_result
    with mock_juju_action("stop-vms"):
        charm.on.stop_vms_action.emit()  # emit action

    charm.helper.stop_vms.assert_called_once_with("test-node", "test-cloud")
    assert charm.state.stopped_vms == stopped_vms
    action_set.assert_called_once_with(
        {"stopped-vms": stopped_vms, "failed-to-stop": failed_to_stop}
    )


def test_on_stop_vms_without_disabled_compute_node(charm, action_fail, action_get):
    """Test stop-vms action, when compute node is not disabled."""
    action_get.return_value = {
        "i-really-mean-it": True,
        "compute-node": "test-node",
        "cloud-name": "test-cloud",
    }
    charm.helper.stop_vms.side_effect = CloudSupportError("test-message")
    with mock_juju_action("stop-vms"):
        charm.on.stop_vms_action.emit()  # emit action

    charm.helper.stop_vms.assert_called_once_with("test-node", "test-cloud")
    action_fail.assert_called_once_with("test-message")


@pytest.mark.parametrize(
    "stopped_vms, force_all, started_vms, failed_to_start",
    [([1, 2, 3, 4, 5], False, [1, 2, 3, 4], [5]), ([1, 2], True, [1, 2, 3, 4], [5])],
)
def test_on_start_vms(
    charm, action_set, action_get, stopped_vms, force_all, started_vms, failed_to_start
):
    """Test start-vms actions."""
    action_get.return_value = {
        "force-all": force_all,
        "i-really-mean-it": True,
        "compute-node": "test-node",
        "cloud-name": "test-cloud",
    }
    charm.state.stopped_vms = stopped_vms
    charm.helper.start_vms.return_value = (started_vms, failed_to_start)
    with mock_juju_action("start-vms"):
        charm.on.start_vms_action.emit()  # emit action

    charm.helper.start_vms.assert_called_once_with(
        "test-node", stopped_vms, force_all, "test-cloud"
    )
    assert charm.state.stopped_vms == []
    action_set.assert_called_once_with(
        {"started-vms": started_vms, "failed-to-start": failed_to_start}
    )
