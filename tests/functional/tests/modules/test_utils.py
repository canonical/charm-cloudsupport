# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared test code."""

from subprocess import check_output


def gen_test_ssh_keys(tmpdir):
    """Create test ssh keys.

    No attempt at all is made to keep them confident, do _not_ use outside testing
    """
    priv_file = tmpdir / "test_id_rsa"
    pub_file = tmpdir / "test_id_rsa.pub"
    # use ed25519 key for testing since if RSA key is provided,
    # it is being treated as a DSA key due to fabric/paramiko connection issue
    # when providing ssh key with "key_filename" setting.
    # refer: https://github.com/fabric/fabric/issues/2182,
    # https://github.com/paramiko/paramiko/issues/1839
    check_output(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-P",
            "",
            "-f",
            str(priv_file),
        ]
    )
    return priv_file, pub_file


def get_priv_key(tmpdir):
    """Return the private key contents."""
    priv_file = tmpdir / "test_id_rsa"
    return priv_file.open().read()
