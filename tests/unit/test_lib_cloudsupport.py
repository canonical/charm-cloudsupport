#!/usr/bin/env python3
# Copyright 2022 Canonical
# See LICENSE file for licensing details.
"""Unittests for lib-cloudsupport."""
from unittest import mock
from unittest.mock import MagicMock, call

from lib_cloudsupport import CloudSupportHelper

from openstack.exceptions import SDKException

from os_testing import CloudSupportError

import pytest


def mock_service(name, status):
    """Return mocked service object."""
    service = MagicMock()  # name needs to be set with configure_mock
    service.configure_mock(name=name, status=status)
    return service


def mock_vm(id_, name=None):
    """Return mocked VM object."""
    name = name or "vm-{}".format(id_)
    vm = MagicMock()  # name needs to be set with configure_mock
    vm.configure_mock(name=name, id=id_)
    return vm


@pytest.mark.parametrize(
    "name, status, hypervisors, exp_result",
    [
        ("node", "active", [], False),
        ("node", "disabled", [], False),
        ("node", "active", [mock_service("diff-node", "active")], False),
        ("node", "disabled", [mock_service("node", "active")], False),
        ("node", "active", [mock_service("node", "active")], True),
        ("node", "disabled", [mock_service("node", "disabled")], True),
        (
            "node",
            "active",
            [mock_service("diff-node", "disabled"), mock_service("node", "active")],
            True,
        ),
    ],
)
def test_check_compute_node_no_services(
    openstack, name, status, hypervisors, exp_result
):
    """Check test of existing compute-node."""
    openstack.compute.hypervisors.return_value = hypervisors
    result = CloudSupportHelper._check_compute_node("test-cloud", name, status)
    assert result == exp_result


def test_stop_vms_compute_node_not_disabled():
    """Try to stop VMs on enabled compute-node."""
    helper = CloudSupportHelper(MagicMock(), MagicMock())
    with mock.patch.object(helper, "_check_compute_node", return_value=False):
        with pytest.raises(CloudSupportError):
            helper.stop_vms("test-node")


@pytest.mark.parametrize(
    "servers, servers_side_effects, exp_stopped, exp_failed",
    [
        ((), (None, None), [], []),
        ((mock_vm(1), mock_vm(2)), (None, None), [1, 2], []),
        ((mock_vm(1), mock_vm(2)), (None, SDKException), [1], [2]),
        ((mock_vm(1), mock_vm(2)), (SDKException, SDKException), [], [1, 2]),
    ],
)
def test_stop_vms(openstack, servers, servers_side_effects, exp_stopped, exp_failed):
    """Test stop-vms helper function."""
    helper = CloudSupportHelper(MagicMock(), MagicMock())
    openstack.compute.servers.return_value = servers
    openstack.compute.stop_server.side_effect = servers_side_effects
    with mock.patch.object(helper, "_check_compute_node", return_value=True):
        stopped_vms, failed_to_stop = helper.stop_vms("test-node")

    openstack.compute.servers.assert_called_once_with(
        host="test-node", all_tenants=True, status="ACTIVE"
    )
    openstack.compute.stop_server.assert_has_calls(
        [call(server.id) for server in servers]
    )

    assert stopped_vms == exp_stopped
    assert failed_to_stop == exp_failed


@pytest.mark.parametrize(
    "servers, servers_side_effects, stopped_vms, force_all, exp_started, exp_failed",
    [
        ((mock_vm(1), mock_vm(2)), (None, None), [], False, [], []),
        ((mock_vm(1), mock_vm(2)), (None, None), [1], False, [1], []),
        ((mock_vm(1), mock_vm(2)), (None, SDKException), [1, 2], False, [1], [2]),
        ((mock_vm(1), mock_vm(2)), (None, None), [1], True, [1, 2], []),
        ((mock_vm(1), mock_vm(2)), (None, SDKException), [1], True, [1], [2]),
        (
            (mock_vm(1), mock_vm(2)),
            (SDKException, SDKException),
            [1, 2],
            False,
            [],
            [1, 2],
        ),
    ],
)
def test_start_vms(
    openstack,
    servers,
    stopped_vms,
    force_all,
    servers_side_effects,
    exp_started,
    exp_failed,
):
    """Test start-vms helper function."""
    helper = CloudSupportHelper(MagicMock(), MagicMock())
    openstack.compute.servers.return_value = servers
    openstack.compute.start_server.side_effect = servers_side_effects
    started_vms, failed_to_start = helper.start_vms("test-node", stopped_vms, force_all)

    openstack.compute.servers.assert_called_once_with(
        host="test-node", all_tenants=True, status="SHUTOFF"
    )
    if force_all:
        openstack.compute.start_server.assert_has_calls(
            [call(server.id) for server in servers]
        )
    else:
        openstack.compute.start_server.assert_has_calls(
            [call(server) for server in stopped_vms]
        )

    assert started_vms == exp_started
    assert failed_to_start == exp_failed
