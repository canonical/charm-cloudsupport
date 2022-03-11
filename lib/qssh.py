#!/usr/bin/env python3

import argparse
import os

import openstack
import openstack.exceptions

# openstack.enable_logging(debug=True)


class QsshError(Exception):
    """An error occured getting info for qssh"""

    pass


_con = None


def con():
    """Return an OpenStack connection and cache it."""
    global _con
    if _con is None:
        _con = openstack.connect()
    return _con


def get_port(srv, network=None):
    """Get instance port. Either constrained by a network or just the first one."""
    ports = con().network.ports(device_id=srv.id)
    # print(srv)
    if network is None:
        port = next(ports)
    else:
        ports = [p for p in ports if p["network_id"] == network]
        if not ports:
            raise QsshError(
                "No ports for instance {} found on net {}".format(srv.id, network)
            )
        # If we have mult. ports for a network we're also just using the first one
        port = ports[0]
    return port


def get_ssh_command_line(ip, net):
    dhcp_agent = next(con().network.network_hosting_dhcp_agents(net))
    cmdline = (
        """ssh -o 'ProxyCommand=ssh -l ubuntu {} "sudo ip netns exec qdhcp-{} """
        """nc -q0 %h %p"' {}""".format(dhcp_agent.host, net.id, ip)
    )
    return cmdline


def main(instance, network=None):
    srv = con().compute.find_server(instance)
    if not srv:
        raise QsshError("Can't find {}".format(instance))
    port = get_port(srv, network)
    ip = port["fixed_ips"][0]["ip_address"]
    net = con().network.find_network(port["network_id"])
    cmdline = get_ssh_command_line(ip, net)
    print(cmdline)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Connect to an instance via qdhcp netns. Note, only works with OVS."
    )
    parser.add_argument("--qssh-net", help="connect to instance on this network")
    parser.add_argument("instance", help="instance to connect to")
    args = parser.parse_args()
    main(args.instance, network=args.qssh_net)
