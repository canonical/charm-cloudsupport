"""Shared test code."""

from subprocess import check_output


def gen_test_ssh_keys(tmpdir):
    """Create test ssh keys.

    No attempt at all is made to keep them confident, do _not_ use outside testing
    """
    priv_file = tmpdir / "test_id_rsa"
    pub_file = tmpdir / "test_id_rsa.pub"
    check_output(
        [
            "ssh-keygen",
            "-m",
            "PEM",
            "-t",
            "rsa",
            "-b",
            "1024",
            "-P",
            "",
            "-f",
            str(priv_file),
        ]
    )
    return priv_file, pub_file


def get_priv_key(tmpdir):
    priv_file = tmpdir / "test_id_rsa"
    return priv_file.open().read()
