# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Configuration file for tests."""
from unittest import mock

from charm import CloudSupportCharm

import lib_cloudsupport

from ops.testing import Harness

import pytest


@pytest.fixture
def openstack():
    """Mock openstack connection."""
    mocker_os_testing_con = mock.patch.object(lib_cloudsupport, "con")
    mock_con = mocker_os_testing_con.start()
    mock_openstack = mock_con.return_value = mock.MagicMock()
    yield mock_openstack
    mocker_os_testing_con.stop()


@pytest.fixture
def harness():
    """Start Harness."""
    harness = Harness(CloudSupportCharm)
    harness.begin()
    harness.charm.helper = mock.MagicMock()
    harness._backend.action_get = mock.MagicMock()
    harness._backend.action_set = mock.MagicMock()
    harness._backend.action_fail = mock.MagicMock()
    yield harness
    harness.cleanup()


@pytest.fixture
def charm(harness):
    """Mock charm with Harness."""
    return harness.charm


@pytest.fixture
def action_get(harness):
    """Return mocked action_get object."""
    yield harness._backend.action_get


@pytest.fixture
def action_set(harness):
    """Return mocked action_set object."""
    yield harness._backend.action_set


@pytest.fixture
def action_fail(harness):
    """Return mocked action_fail object."""
    yield harness._backend.action_fail
