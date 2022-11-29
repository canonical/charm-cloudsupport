"""This module contains methods to run OpenStack commands."""
import logging
import os
import re
import warnings
from datetime import datetime

from cryptography.utils import CryptographyDeprecationWarning

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

import fabric  # noqa: E402

import openstack  # noqa: E402
import openstack.exceptions  # noqa: E402

_con = None


def con(cloud_name, reconnect=False):
    """Return an OpenStack connection and cache it."""
    global _con
    if reconnect and _con is not None:
        _con.close()
        _con = None
    if _con is None:
        _con = openstack.connect(
            cacert=os.environ.get("OS_CACERT", "/etc/openstack/ssl_ca.crt"),
            cloud=cloud_name,
        )
    return _con


class CloudSupportError(Exception):
    """Error during a cloud support operation."""

    pass


# Some defaults

DEFAULT_FLAVOR = {
    "name": "cloudsupport-test-flavor",
    "flavorid": "cloudsupport-test-flavor",
    "vcpus": 24,
    "ram": 4096,
    "disk": 4,
}

TEST_NETWORK = "cloudsupport-test-net"
TEST_CIDR = "192.168.99.0/24"
TEST_AGGREGATE = "cloudsupport-test-agg"
TEST_SECGROUP = "cloudsupport-test-secgroup"
TEST_SSH_KEY = ".ssh/id_rsa_cloudsupport"
OVS_NET_NS = "qdhcp"
OVN_NET_NS = "ovnmeta"


def ensure_net(netname, cidr, cloud_name="cloud1"):
    """Ensure net with name/cidr is present.

    Will attempt to delete a net if a cidr change is detected.

    :param netname: string network name
    :param cidr: string network cidr
    :param cloud_name: string cloud name to select auth info in clouds.yaml
    :return: tuple (ok, detail)
    """
    candidate = con(cloud_name).network.find_network(netname)
    if candidate:
        subnet = con(cloud_name).network.get_subnet(candidate.subnet_ids[0])
        if subnet.cidr == cidr:
            logging.info("Network %s (%s) already present", netname, cidr)
            return True, candidate
        logging.info(
            "Found net %s (%s), but want cidr %s, attempt to delete",
            netname,
            subnet.cidr,
            cidr,
        )
        try:
            con(cloud_name).network.delete_network(candidate.id)
        except openstack.exceptions.ConflictException as detail:
            msg = "Fault deleting net {}: {}".format(candidate.id, detail)
            logging.warning(msg)
            return False, msg
    try:
        net = con(cloud_name).network.create_network(name=netname)
        con(cloud_name).network.create_subnet(
            name=netname,
            network_id=net.id,
            ip_version="4",
            cidr=cidr,
        )
    except openstack.exceptions.ResourceFailure as detail:
        msg = "Fault creating net or subnet {}: {}".format(netname, detail)
        logging.warning(msg)
        return False, msg
    logging.info("Created network %s %s", netname, cidr)
    return True, net


def create_port(netname, physnet=None, cloud_name="cloud1"):
    """Create a port on a network.

    :param netname: network to create port in
    :param physnet: optionally make it a sr-iov port
    :param cloud_name: string cloud name to select auth info in clouds.yaml
    :return: the new port
    """
    logging.debug("Create port: %s %s", netname, physnet)
    net = con(cloud_name).network.find_network(netname)
    if not net:
        raise CloudSupportError("net not found: {}".format(netname))
    if physnet is None:
        port = con(cloud_name).network.create_port(
            network_id=net.id,
            name=netname,
        )
    else:
        port = con(cloud_name).network.create_port(
            network_id=net.id,
            name=netname,
            binding_profile={"physical_network": physnet},
            binding_vnic_type="direct",
        )
    logging.debug("Port created: %s", port)
    return port


def ensure_flavor(name, vcpus, ram, disk, vnfspecs=True, cloud_name="cloud1"):
    """Re-create test flavor.

    :param name: flavor name
    :param vcpus: number of vcpus
    :param ram: size of ram in MB
    :param disk: size of disk in GB
    :param vnfspecs: flag: create flavor with typical VNF specs if true
    :param cloud_name: string cloud name to select auth info in clouds.yaml
    :return: the flavor
    """
    flavor = con(cloud_name).compute.find_flavor(name)
    if flavor is not None:
        logging.info("Delete flavor %s", flavor)
        con(cloud_name).compute.delete_flavor(flavor)
    flavor_spec = DEFAULT_FLAVOR.copy()
    flavor_spec.update(
        {"name": name, "flavorid": name, "vcpus": vcpus, "ram": ram, "disk": disk}
    )
    flavor = con(cloud_name).compute.create_flavor(**flavor_spec)
    extra_specs = {
        "aggregate_instance_extra_specs:cloudsupport-test-agg": "true",
    }
    if vnfspecs:
        extra_specs.update(
            {
                "hw:cpu_policy": "dedicated",
                "hw:cpu_thread_policy": "require",
                "hw:mem_page_size": "1048576",
            }
        )
    con(cloud_name).compute.create_flavor_extra_specs(flavor.id, extra_specs)
    logging.info("Created flavor %s", name)
    return flavor


def ensure_host_aggregate(agg_name, nodes, cloud_name="cloud1"):
    """Check if testing host agg exists, create it if not.

    :param agg_name: aggregate name
    :param nodes: nodes to put into aggregate
    :param cloud_name: string cloud name to select auth info in clouds.yaml
    :return: the testing aggregate
    """
    agg = con(cloud_name).compute.find_aggregate(agg_name)
    if not agg:
        agg = con(cloud_name).compute.create_aggregate(name=agg_name)
        con(cloud_name).compute.set_aggregate_metadata(
            agg.id, {"cloudsupport-test-agg": "true"}
        )
        logging.info("Created %s", agg_name)
    if agg.hosts:
        for node in agg.hosts:
            con(cloud_name).compute.remove_host_from_aggregate(agg.id, node)
    for node in nodes:
        con(cloud_name).compute.add_host_to_aggregate(agg.id, node)
    return agg


def ensure_sg_rules(secgroup, tcp_ports=None, cloud_name="cloud1"):
    """Check if testing secgroup exists, create if not.

    Add rules for icmp and tcp ports to new secgroup

    :param secgroup: secgroup name
    :param tcp_ports: tcp ports to allow, defaults to 22,80
    :param cloud_name: string cloud name to select auth info in clouds.yaml
    :return: the secgroup
    """
    sg = con(cloud_name).network.find_security_group(secgroup)
    if sg is not None:
        logging.info("Secgroup %s already exists", secgroup)
        return sg
    sg = con(cloud_name).network.create_security_group(name=secgroup)
    con(cloud_name).network.create_security_group_rule(
        security_group_id=sg.id, direction="ingress", protocol="icmp"
    )
    if tcp_ports is None:
        tcp_ports = [22, 80]
    for p in tcp_ports:
        con(cloud_name).network.create_security_group_rule(
            security_group_id=sg.id,
            direction="ingress",
            protocol="tcp",
            port_range_min=p,
            port_range_max=p,
        )
    logging.debug("SG created: %s", sg)
    return sg


def create_instance(
    nodes,
    vcpus,
    ram,
    disk,
    image,
    name_prefix,
    cidr,
    network=TEST_NETWORK,
    physnet=None,
    num_instances=None,
    vnfspecs=True,
    key_name=None,
    cloud_name="cloud1",
):
    """Create test instances.

    The instances are created in the test aggregate, either the number specified or one
    per node given

    :param nodes: comma-separated list of nodes to put into the test aggregate
    :param vcpus: create a flavor with this many vcpus
    :param image: name of image to use, this image must already exist and be usable
    :param name_prefix: instance name prefix
    :param network: name of network, will be created if missing
    :param cidr: network cidr, a default one will be used if missing
    :param physnet: optional: create an sr-iov port on given physnet
    :param num_instances: number of instances, defaults to 1 per given node
    :param vnfspecs: flag, use typical VNF specs if given
    :param key_name: string keypair name to pass to instance creation
    :param cloud_name: string cloud name to select auth info in clouds.yaml
    :return: list of list with results
    """
    logging.debug("Creating instance on: %s", nodes)
    ensure_host_aggregate(TEST_AGGREGATE, nodes, cloud_name=cloud_name)
    ok, detail = ensure_net(network, cidr, cloud_name=cloud_name)
    if not ok:
        return [["error", None, detail]]
    flavor = ensure_flavor(
        DEFAULT_FLAVOR["name"], vcpus, ram, disk, vnfspecs, cloud_name=cloud_name
    )
    sg = ensure_sg_rules(TEST_SECGROUP, cloud_name=cloud_name)
    img = con(cloud_name).image.find_image(image)
    if not img:
        return ["error", "Image not found", image]
    ts = datetime.utcnow()
    name = "{}-{}".format(name_prefix, ts.strftime("%Y-%m-%dT%H%M"))
    if num_instances is None:
        num_instances = len(nodes)
    created = []
    for _ in range(num_instances):
        ports = [create_port(network, cloud_name=cloud_name)]
        if physnet:
            ports.append(create_port(network, physnet, cloud_name=cloud_name))

        optional_params = {}
        if key_name:
            optional_params["key_name"] = key_name

        server = con(cloud_name).compute.create_server(
            name=name,
            image_id=img.id,
            flavor_id=flavor.id,
            networks=[{"port": p.id} for p in ports],
            wait=True,
            **optional_params
        )
        logging.debug("Spawn instance: %s", server)
        try:
            con(cloud_name).compute.wait_for_server(server)
        except openstack.exceptions.ResourceFailure as detail:
            logging.warning("Fault spawning test instance: %s: %s", server, detail)
            created.append(["error", server.id, detail])
        else:
            con(cloud_name).compute.add_security_group_to_server(server, sg)
            created.append(["success", server.id, "ok"])
    logging.info("Done create: %s", created)
    return created


def delete_instance(nodes, pattern, cloud_name="cloud1"):
    """Delete instances matching pattern on given nodes.

    :param nodes: list of node names
    :param pattern: instance name pattern
    :param cloud_name: string cloud name to select auth info in clouds.yaml
    :return: list of deletion results
    """
    nodes = set(nodes)
    pat = re.compile(pattern)
    instances = [
        i.id
        for i in con(cloud_name).compute.servers()
        if i.compute_host in nodes and pat.match(i.name)
    ]
    results = []
    for i in instances:
        con(cloud_name).compute.delete_server(i)
        results.append(["success", i])
    logging.info("Deleted: %s", instances)
    return results


def get_instances(instance=None, cloud_name="cloud1"):
    """Get the list of instance ids from the cloud.

    :param instance: get particular instance if specified
    :param cloud_name: the cloud name to get the instances from
    :return: list of instances
    """
    if not instance:
        instances = [
            i.id
            for i in con(cloud_name).compute.servers()
            if i.name.startswith("cloudsupport-test-")
        ]
        if not instances:
            logging.warning("No instances found")
            return {"warning": "No instances found"}
    else:
        instances = [instance]
    return instances


def is_ovn_used(hypervisor_hostname, cloud_name="cloud1"):
    """Check is OVN used in a particular cloud.

    :param hypervisor_hostname: the hostname of the hypervisor machine
    :param cloud_name: the cloud name the check is performed on
    :return: boolean value for the condition
    """
    if (
        len(
            list(
                con(cloud_name).network.agents(
                    host=hypervisor_hostname, binary="ovn-controller"
                )
            )
        )
        > 0
    ):
        return True

    return False


def test_connectivity(instance=None, cloud_name="cloud1"):
    """Test connectivity to instance(s).

    The test will ping and connect to tcp:22 and tcp:80 from the qdhcp netns towards the
    non-sriov ports

    :param instance: instance id. If missing, all instances whose names start with
    :param cloud_name: string cloud name to select auth info in clouds.yaml
    "cloudsupport-test-" will be tested

    :return: dictionary with test results, keyed on instances' UUIDs
    """
    instances = get_instances(instance=instance, cloud_name=cloud_name)

    results = {}
    for i in instances:
        srv = con(cloud_name).compute.get_server(i)
        hypervisor_hostname = srv.hypervisor_hostname
        net = con(cloud_name).network.find_network(TEST_NETWORK)
        is_ovn = is_ovn_used(hypervisor_hostname, cloud_name=cloud_name)

        if is_ovn:
            host = hypervisor_hostname
            net_ns = OVN_NET_NS
        else:
            # is OVS
            dhcp_agent = next(con(cloud_name).network.network_hosting_dhcp_agents(net))
            host = dhcp_agent.host
            net_ns = OVS_NET_NS

        node = fabric.Connection(
            host,
            user="ubuntu",
            connect_kwargs={
                "key_filename": [TEST_SSH_KEY],
            },
        )
        logging.debug("Testing conn from: %s", host)

        addr = srv.addresses[TEST_NETWORK][0]["addr"]
        logging.debug("Pinging: %s", addr)

        ping_res = node.sudo(
            "sudo ip netns exec {}-{} ping -c3 -q {}".format(net_ns, net.id, addr),
            warn=True,
            hide=True,
        )
        logging.debug("Ping res: %s", ping_res)
        ssh_res = node.sudo(
            "sudo ip netns exec {}-{} nc -vzw 3 {} 22".format(net_ns, net.id, addr),
            warn=True,
            hide=True,
        )
        logging.debug("Nc tcp:22 res: %s", ssh_res)
        results[i] = {
            "ping": "{}\n{}".format(ping_res.stdout, ping_res.stderr),
            "ssh": "{}\n{}".format(ssh_res.stdout, ssh_res.stderr),
        }
    return results


def get_ssh_cmd(instance=None, cloud_name="cloud1"):
    """Get ssh cmd to connect to the instance.

    :param instance: instance id. If missing, all instances whose names start with
    "cloudsupport-test-" will be tested
    :param cloud_name: string cloud name to select auth info in clouds.yaml

    :return: dictionary with ssh cmds, keyed on instances' UUIDs
    """
    instances = get_instances(instance=instance, cloud_name=cloud_name)
    connection_string = (
        "ssh ubuntu@{vm_ip} "
        '-o ProxyCommand="juju ssh {host} '
        'sudo ip netns exec {net_ns}-{net_id} nc %h %p"'
    )
    results = {}
    for i in instances:
        srv = con(cloud_name).compute.get_server(i)
        hypervisor_hostname = srv.hypervisor_hostname
        net = con(cloud_name).network.find_network(TEST_NETWORK)
        addr = srv.addresses[TEST_NETWORK][0]["addr"]

        is_ovn = is_ovn_used(hypervisor_hostname, cloud_name=cloud_name)

        if is_ovn:
            host = hypervisor_hostname
            net_ns = OVN_NET_NS
        else:
            host = next(con(cloud_name).network.network_hosting_dhcp_agents(net)).host
            net_ns = OVS_NET_NS

        results[i] = "\n" + connection_string.format(
            vm_ip=addr, host=host, net_ns=net_ns, net_id=net.id
        )

    return results


if __name__ == "__main__":
    import sys

    create_instance([sys.argv[1]])
    test_connectivity()
    delete_instance([sys.argv[1]])
