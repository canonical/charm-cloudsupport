import logging
import os
import re
from datetime import datetime

import fabric
import openstack
import openstack.exceptions

# openstack.enable_logging(debug=True)

_con = None


def con(cloud="cloud1", reconnect=False):
    """Return an OpenStack connection and cache it."""
    global _con
    if reconnect and _con is not None:
        _con.close()
        _con = None
    if _con is None:
        _con = openstack.connect(
            cacert=os.environ.get("OS_CACERT", "ssl_ca.crt"), cloud=cloud
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


def ensure_net(netname, cidr):
    """Ensure net with name/cidr is present.

    Will attempt to delete a net if a cidr change is detected.

    :param netname: string network name
    :param cidr: string network cidr
    :return: tuple (ok, detail)
    """
    candidate = con().network.find_network(netname)
    if candidate:
        subnet = con().network.get_subnet(candidate.subnet_ids[0])
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
            con().network.delete_network(candidate.id)
        except openstack.exceptions.ConflictException as detail:
            msg = "Fault deleting net {}: {}".format(candidate.id, detail)
            logging.warning(msg)
            return False, msg
    try:
        net = con().network.create_network(name=netname)
        con().network.create_subnet(
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


def create_port(netname, physnet=None):
    """Create a port on a network.

    :param netname: network to create port in
    :param physnet: optionally make it a sr-iov port
    :return: the new port
    """
    logging.debug("Create port: %s %s", netname, physnet)
    net = con().network.find_network(netname)
    if not net:
        raise CloudSupportError("net not found: {}".format(netname))
    if physnet is None:
        port = con().network.create_port(
            network_id=net.id,
            name=netname,
        )
    else:
        port = con().network.create_port(
            network_id=net.id,
            name=netname,
            binding_profile={"physical_network": physnet},
            binding_vnic_type="direct",
        )
    logging.debug("Port created: %s", port)
    return port


def ensure_flavor(name, vcpus, vnfspecs=True):
    """Re-create test flavor.

    :param name: flavor name
    :param vcpus: number of vcpus
    :param vnfspecs: flag: create flavor with typical VNF specs if true
    :return: the flavor
    """
    flavor = con().compute.find_flavor(name)
    if flavor is not None:
        logging.info("Delete flavor %s", flavor)
        con().compute.delete_flavor(flavor)
    flavor_spec = DEFAULT_FLAVOR.copy()
    flavor_spec.update({"name": name, "flavorid": name, "vcpus": vcpus})
    flavor = con().compute.create_flavor(**flavor_spec)
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
    con().compute.create_flavor_extra_specs(flavor.id, extra_specs)
    logging.info("Created flavor %s", name)
    return flavor


def ensure_host_aggregate(agg_name, nodes):
    """Check if testing host agg exists, create it if not.

    :param agg_name: aggregate name
    :param nodes: nodes to put into aggregate
    :return: the testing aggregate
    """
    agg = con().compute.find_aggregate(agg_name)
    if not agg:
        agg = con().compute.create_aggregate(name=agg_name)
        con().compute.set_aggregate_metadata(agg.id, {"cloudsupport-test-agg": "true"})
        logging.info("Created %s", agg_name)
    if agg.hosts:
        for node in agg.hosts:
            con().compute.remove_host_from_aggregate(agg.id, node)
    for node in nodes:
        con().compute.add_host_to_aggregate(agg.id, node)
    return agg


def ensure_sg_rules(secgroup, tcp_ports=None):
    """Check if testing secgroup exists, create if not.

    Add rules for icmp and tcp ports to new secgroup

    :param secgroup: secgroup name
    :param tcp_ports: tcp ports to allow, defaults to 22,80
    :return: the secgroup
    """
    sg = con().network.find_security_group(secgroup)
    if sg is not None:
        logging.info("Secgroup %s already exists", secgroup)
        return sg
    sg = con().network.create_security_group(name=secgroup)
    con().network.create_security_group_rule(
        security_group_id=sg.id, direction="ingress", protocol="icmp"
    )
    if tcp_ports is None:
        tcp_ports = [22, 80]
    for p in tcp_ports:
        con().network.create_security_group_rule(
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
    image,
    name_prefix,
    cidr,
    network=TEST_NETWORK,
    physnet=None,
    num_instances=None,
    vnfspecs=True,
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
    :return: list of list with results
    """
    logging.debug("Creating instance on: %s", nodes)
    ensure_host_aggregate(TEST_AGGREGATE, nodes)
    ok, detail = ensure_net(network, cidr)
    if not ok:
        return [["error", None, detail]]
    flavor = ensure_flavor(DEFAULT_FLAVOR["name"], vcpus, vnfspecs)
    sg = ensure_sg_rules(TEST_SECGROUP)
    img = con().image.find_image(image)
    if not img:
        return ["error", "Image not found", image]
    ts = datetime.utcnow()
    name = "{}-{}".format(name_prefix, ts.strftime("%Y-%m-%dT%H%M"))
    if num_instances is None:
        num_instances = len(nodes)
    created = []
    for _ in range(num_instances):
        ports = [create_port(network)]
        if physnet:
            ports.append(create_port(network, physnet))
        server = con().compute.create_server(
            name=name,
            image_id=img.id,
            flavor_id=flavor.id,
            networks=[{"port": p.id} for p in ports],
            wait=True,
        )
        logging.debug("Spawn instance: %s", server)
        try:
            con().compute.wait_for_server(server)
        except openstack.exceptions.ResourceFailure as detail:
            logging.warning("Fault spawning test instance: %s: %s", server, detail)
            created.append(["error", server.id, detail])
        else:
            con().compute.add_security_group_to_server(server, sg)
            created.append(["success", server.id, "ok"])
    logging.info("Done create: %s", created)
    return created


def delete_instance(nodes, pattern):
    """Delete instances matching pattern on given nodes.

    :param nodes: list of node names
    :param pattern: instance name pattern
    :return: list of deletetion results
    """
    nodes = set(nodes)
    pat = re.compile(pattern)
    instances = [
        i.id
        for i in con().compute.servers()
        if i.compute_host in nodes and pat.match(i.name)
    ]
    results = []
    for i in instances:
        con().compute.delete_server(i)
        results.append(["success", i])
    logging.info("Deleted: %s", instances)
    return results


def test_connectivity(instance=None):
    """Test connectivity to instance(s).

    The test will ping and connect to tcp:22 and tcp:80 from the qdhcp netns towards the
    non-sriov ports

    :param instance: instance id. If missing, all instances whose names start with
    "cloudsupport-test-" will be tested

    :return: dictionary with test results, keyed on instance name
    """
    if not instance:
        instances = [
            i.id
            for i in con().compute.servers()
            if i.name.startswith("cloudsupport-test-")
        ]
        if not instances:
            logging.warning("No instances found")
            return {"warning": "No instances found"}
    else:
        instances = [instance]
    net = con().network.find_network(TEST_NETWORK)
    dhcp_agent = next(con().network.network_hosting_dhcp_agents(net))
    logging.debug("Testing conn from: %s", dhcp_agent.host)
    node = fabric.Connection(
        dhcp_agent.host,
        user="ubuntu",
        connect_kwargs={
            "key_filename": [TEST_SSH_KEY],
        },
    )
    results = {}
    for i in instances:
        srv = con().compute.get_server(i)
        addr = srv.addresses[TEST_NETWORK][0]["addr"]
        logging.debug("Pinging: %s", addr)
        ping_res = node.sudo(
            "sudo ip netns exec qdhcp-{} ping -c3 -q {}".format(net.id, addr), warn=True
        )
        logging.debug("Ping res: %s", ping_res)
        ssh_res = node.sudo(
            "sudo ip netns exec qdhcp-{} nc -vzw 3 {} 22".format(net.id, addr),
            warn=True,
        )
        logging.debug("Nc tcp:22 res: %s", ssh_res)
        results[i] = {
            "ping": "{}\n{}".format(ping_res.stdout, ping_res.stderr),
            "ssh": "{}\n{}".format(ssh_res.stdout, ssh_res.stderr),
        }
    return results


if __name__ == "__main__":
    import sys

    create_instance([sys.argv[1]])
    test_connectivity()
    delete_instance([sys.argv[1]])
