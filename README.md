# Overview

Support charm for OpenStack operations. It's main purpose is to package common tasks into easy-to-use actions. 

Typically it will be deployed into a container on an infrastructure node.

The charm requires OpenStack credentials to operate, and some actions require administrative access to cloud computes via ssh. 


## Action: Test Instance Creation

Spawn instances named "bootstack-test-instance-*" on the given compute node(s). This requires a pre-existing "bootstack-test-image" to be present in the cloud. 

Example:

```sh
juju run-action --wait cloudsupport/0 create-test-instance nodes=compute1.maas,compute2.maas vcpus=2 vnfspecs=true physnet=physnet1
```


## Action: Instance connectivity check

Run a connectivity test against instances. The connectivity test does not require a floating ip address -- it will be run from the net namespace of the qdhcp agent. The test will be run against the first port bound to the test instance. The test will ping the port and attempt a connection to tcp:22 and tcp:80 (note the bootstack-test-image will launch services listening on those).

Example:

```sh
juju run-action --wait cloudsupport/0 test-connectivity 
```


## Action: Test Instance Deletion

Will delete instances named "bootstack-test-instance-*" on the given nodes. 

```sh
juju run-action --wait cloudsupport/0 delete-test-instance nodes=compute1.maas,compute2.maas

```



# Deploy and Configure

Deploy this charm with:
```sh
juju deploy charm-cloudsupport cloudsupport
```
Set up OpenStack connection params by providing yaml-formatted string with one cloud named `cloud`:

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

juju config cloudsupport clouds-yaml="$( cat clouds.yaml )"
```

The test-connectivity action needs credentials to connect to compute nodes. Those can be configured by passing in a ssh key:

```sh
juju config cloudsupport ssh-key='ssh-rsa ...'
```

If a CA certificate is required to connect to the OpenStack API it can be provided thusly:

```sh
juju config cloudsupport ssl_ca='
-----BEGIN CERTIFICATE-----
<certificate body>
-----END CERTIFICATE-----
'
```






