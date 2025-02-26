# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

# !/usr/bin/env python3
"""Check for stale servers with prefix."""

import argparse
import datetime
import os
import re
import sys
from enum import IntEnum

import openstack

import yaml


class NrpeStatus(IntEnum):
    """Nrpe class."""

    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3


def nrpe_check():
    """Perform the nrpe check."""
    args = parse_args()
    crit_servers, warn_servers = get_stale_servers(
        args.name_prefix, args.crit_days, args.warn_days, args.ignored_servers_uuids
    )
    exit_code = NrpeStatus.OK
    if crit_servers:
        print(
            "CRITICAL: {} test servers older than {} days. "
            "Check and delete the following instances: {}".format(
                len(crit_servers),
                args.crit_days,
                ",".join([server.id for server in crit_servers]),
            )
        )
        exit_code = max(exit_code, NrpeStatus.CRITICAL)
    if warn_servers:
        print(
            "WARNING: {} test servers older than {} days. "
            "Check and delete the following instances: {}".format(
                len(warn_servers),
                args.warn_days,
                ",".join([server.id for server in warn_servers]),
            )
        )
        exit_code = max(exit_code, NrpeStatus.WARNING)
    if exit_code == 0:
        print("OK: No stale instances found.")
    sys.exit(exit_code)


def parse_args():
    """Parse the command line arguments."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud-name", dest="cloud_name", type=str, required=True)
    ap.add_argument("--name-prefix", dest="name_prefix", type=str, required=True)
    ap.add_argument("--warn-days", dest="warn_days", type=int, default=7)
    ap.add_argument("--crit-days", dest="crit_days", type=int, default=14)
    ap.add_argument(
        "--ignored-servers-uuids",
        dest="ignored_servers_uuids",
        type=str,
        required=False,
        default=None,
        help="Comma separated list of servers uuids to ignore.",
    )
    return ap.parse_args()


def get_stale_servers(name_prefix, crit_days, warn_days, ignored_servers=None):
    """Get the stale servers."""
    crit_servers = []
    warn_servers = []
    server_search_pattern = "^{}".format(re.escape(name_prefix))
    con = openstack.connect(
        cloud="envvars", cacert=os.environ.get("OS_CACERT", "/etc/openstack/ssl_ca.crt")
    )
    servers = con.compute.servers(name=server_search_pattern)
    ignored_servers_uuids = []
    if ignored_servers:
        ignored_servers_uuids = ignored_servers.split(",")
    for s in servers:
        # skip ignored servers
        if s.id in ignored_servers_uuids:
            continue
        if s.name.startswith(name_prefix):
            updated_at = datetime.datetime.strptime(s.updated_at, "%Y-%m-%dT%H:%M:%SZ")
            uptime = datetime.datetime.utcnow() - updated_at
            if uptime.days > crit_days:
                crit_servers.append(s)
            elif uptime.days > warn_days:
                warn_servers.append(s)
    return crit_servers, warn_servers


if __name__ == "__main__":
    # source environment vars
    if not os.path.exists("/etc/openstack/clouds.yaml"):
        print("UNKNOWN: /etc/openstack/clouds.yaml not found")
        sys.exit(NrpeStatus.UNKNOWN)

    with open("/etc/openstack/clouds.yaml", "r") as cloud_config:
        config = yaml.safe_load(cloud_config)

    if "clouds" not in config:
        print("UNKNOWN: clouds.yaml unknown format")
        sys.exit(NrpeStatus.UNKNOWN)

    args = parse_args()
    cloud_name = args.cloud_name

    auth_info = config["clouds"].get(cloud_name)

    if not auth_info or "auth" not in auth_info:
        print("UNKNOWN: {} is missing auth info in clouds.yaml").format(cloud_name)
        sys.exit(NrpeStatus.UNKNOWN)

    auth = auth_info["auth"]
    for key in auth:
        os.environ["OS_" + key.upper()] = auth[key]
    nrpe_check()
