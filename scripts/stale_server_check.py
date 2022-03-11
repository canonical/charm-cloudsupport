#!/usr/bin/env python3

import argparse
import datetime
import re
import sys
from enum import IntEnum

import openstack


class NrpeStatus(IntEnum):
    OK = 0
    WARNING = 1
    CRITICAL = 2


def nrpe_check():
    args = parse_args()

    crit_servers, warn_servers = get_stale_servers(args.name_prefix, args.crit_days, args.warn_days)
    exit_code = NrpeStatus.OK
    if crit_servers:
        print('CRITICAL: {} test servers older than {} days'.format(len(crit_servers), args.crit_days))
        for server in crit_servers:
            print('- {}'.format(server.id))
        exit_code = max(exit_code, NrpeStatus.CRITICAL)
    if warn_servers:
        print('WARNING: {} test servers older than {} days'.format(len(warn_servers), args.warn_days))
        for server in warn_servers:
            print('- {}'.format(server.id))
        exit_code = max(exit_code, NrpeStatus.WARNING)
    if exit_code == 0:
        print('OK')
    sys.exit(exit_code)


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('name_prefix', type=str)
    ap.add_argument('warn_days', type=float)
    ap.add_argument('crit_days', type=float)
    return ap.parse_args()


def get_stale_servers(name_prefix, crit_days, warn_days):
    crit_servers = []
    warn_servers = []
    server_search_pattern = '^{}'.format(re.escape(name_prefix))
    con = openstack.connect()
    for s in con.compute.servers(name=server_search_pattern):
        if s.name.startswith(name_prefix):
            updated_at = datetime.datetime.strptime(s.updated_at, '%Y-%m-%dT%H:%M:%SZ')
            uptime = datetime.datetime.utcnow() - updated_at
            if uptime.days > crit_days:
                crit_servers.append(s)
            elif uptime.days > warn_days:
                warn_servers.append(s)
    return crit_servers, warn_servers


if __name__ == "__main__":
    nrpe_check()
