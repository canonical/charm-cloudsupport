"""Set up functional tests."""

import subprocess
import time
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_fixed

from tests.modules.test_utils import gen_test_ssh_keys

import zaza.utilities.deployment_env as deployment_env
from zaza.openstack.charm_tests.glance.setup import add_image

userdata_tmpl = """
cloudinit-userdata: |
  postruncmd:
    - |
      bash -c '
      cat >> /home/ubuntu/.ssh/authorized_keys <<EOF
      {}
      EOF
      '
"""


def model_config():
    """Set the model configuration."""
    tmp = Path(deployment_env.get_tmpdir())
    priv_file, pub_file = gen_test_ssh_keys(tmp)
    with pub_file.open() as f:
        ud = userdata_tmpl.format(f.read())
    ud_file = tmp / "cloudinit-userdata.yaml"
    with ud_file.open("w") as f:
        f.write(ud)
    subprocess.run("juju model-config {}".format(str(ud_file)), shell=True)


# Retry upto 3 minutes because sometimes vault is not ready,
# and it causes error on tls connection
@retry(stop=stop_after_attempt(18), wait=wait_fixed(10))
def add_test_image():
    """Add cirros image."""
    url = "http://download.cirros-cloud.net/0.5.2/cirros-0.5.2-x86_64-disk.img"
    add_image(url, image_name="cloudsupport-image")


def wait_for_overcloud():
    """Wait to ensure overcloud is ready."""
    time.sleep(120)
