> [!NOTE]
> This charm is under maintenance mode. Only critical bug will be handled.

# Overview

Support charm for OpenStack operations. It's main purpose is to package common tasks into easy-to-use actions. 

Typically it will be deployed into a container on an infrastructure node.

The charm requires OpenStack credentials to operate, and some actions require administrative access to cloud computes via ssh. 


## Action: Test Instance Creation

Spawn test instances on the given compute node(s). This requires a pre-existing test image (by default: cloudsupport-image) to be present in the cloud. 

Example:

```sh
juju run-action --wait cloudsupport/0 create-test-instances nodes=compute1.maas,compute2.maas vcpus=2 vnfspecs=true physnet=physnet1
```


## Action: Instance connectivity check

Run a connectivity test against instances. The connectivity test does not require a floating ip address -- it will be run from an appropriate net namespace. The test will be run against the first port bound to the test instance. The test will ping the port and attempt a connection to tcp:22 and tcp:80 (note the cloudsupport-image should launch services listening on those). 

This action supports both OVS and OVN deployments.

Example:

```sh
juju run-action --wait cloudsupport/0 test-connectivity 
```

## Action: Test Instance Deletion

Will delete instances on nodes. Instance names will be matched against the given pattern (by default: ^cloudsupport-test-.*). DANGER! This _will_ wipe your instances without asking for confirmation!

Example - delete instances named 'cloudsupport-test-.*' on compute1 and compute2:
```sh
juju run-action --wait cloudsupport/0 delete-test-instances nodes=compute1.maas,compute2.maas

```

## Action: Get ssh cmd

Get ssh cmd to connect to test instances. 
If you have specified a `key-name` when creating the instances, you should have passwordless ssh using the printed cmds.

```sh
juju run-action --wait cloudsupport/0 get-ssh-cmd --wait
```

Optionally you can pass an instance UUID in this case the action will get the ssh cmd only for the given instance:
```sh
juju run-action --wait cloudsupport/0 get-ssh-cmd instance="3be0c29e-0299-44bb-9b0f-f9f35cab39ee" --wait
```


# Deploy and Configure

Deploy this charm with:
```sh
juju deploy cloudsupport
```
Set up OpenStack connection params by providing yaml-formatted string with one cloud named `cloud1`. For safety it is **strongly** advised to utilize an administrative project, separate from production workload projects.

```sh
cat clouds.yaml
clouds:
  cloud1:
    region_name: {region_name}
    auth:
      auth_url: {auth_url}
      username: {username}
      password: {password}
      user_domain_name: {user_domain_name}
      project_name: {project_name}
      domain_name: {domain_name}

juju config cloudsupport clouds-yaml=@clouds.yaml
```
Also ensure that the config param `cloud-name` match the name of the cloud in the `clouds-yaml`

i.e. (in this case you won't need this as clouds-yaml is using the default cloud name "cloud1")
```sh
juju config cloudsupport cloud-name="cloud1"
```

The test-connectivity action needs credentials to connect to compute nodes. Those can be configured by passing in a ssh key:

```sh
juju config cloudsupport ssh-key=@~/.local/share/juju/ssh/juju_id_rsa'
```

If a CA certificate is required to connect to the OpenStack API it can be provided thusly:

```sh
juju config cloudsupport ssl-ca='
-----BEGIN CERTIFICATE-----
<certificate body>
-----END CERTIFICATE-----
'
```

## Add nrpe check
This charm provides an nrpe check to ensure that the VMs deployed with it are not left running on the cloud for more than 
`stale-warn-days` (this generates a warning) or more than `stale-crit-days` (this generates a critical alert).

To configure it, relate the charm with nrpe 

```sh
juju add-relation cloudsupport nrpe
```

and enable the check that is disabled by default

```sh
juju config cloudsupport stale-server-check=true
```

Use juju config to tune the `stale-warn-days` (default 7) and the `stale-crit-days` (default 14)

Specific VMs can be ignored when checking for stale servers, adding their uuid to the config param `stale-ignored-uuids`
