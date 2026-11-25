"""The test stack's shell scripts that run before Docker: test-stack/nginx/build-conf.sh finds the
README's nginx blocks by their markers, test-stack/make-certs.sh always ends with a certificate for
every hostname. The full stacks are checked by scripts/stack-on-vm.sh (needs Docker)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD_CONF = ROOT / "test-stack" / "nginx" / "build-conf.sh"
MAKE_CERTS = ROOT / "test-stack" / "make-certs.sh"
HOSTS = ["erp.example.com", "sso.example.com", "mcp.example.com", "chat.example.com", "apps.example.com"]

needs_sh = pytest.mark.skipif(shutil.which("sh") is None or shutil.which("awk") is None,
                              reason="needs sh and awk")
needs_openssl = pytest.mark.skipif(shutil.which("sh") is None or shutil.which("openssl") is None,
                                   reason="needs sh and openssl")


def _extract(readme: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(BUILD_CONF), "--extract-only", str(readme)],
                          capture_output=True, text=True, timeout=30)


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_marks_each_nginx_block_of_the_test_stack_once():
    readme = _readme()
    for name in ("mcp-server", "mcp-prefix"):
        assert readme.count(f"<!-- test-stack nginx block: {name}.") == 1


@needs_sh
def test_extract_only_finds_both_marked_blocks_of_the_readme():
    out = _extract(ROOT / "README.md")
    assert out.returncode == 0, out.stderr
    server, prefix = out.stdout.split("# ---- mcp-prefix ----\n")
    assert server.startswith("# ---- mcp-server ----\nserver {")
    assert "proxy_pass http://127.0.0.1:8131;" in server
    assert prefix.startswith("location = /dolibarr/mcp {")
    assert "```" not in out.stdout and "<!--" not in out.stdout


@needs_sh
def test_rewording_the_readme_around_the_blocks_keeps_them(tmp_path: Path):
    reworded = _readme().replace("server_name mcp.example.com;", "server_name mcp.example.org;")
    reworded = reworded.replace("location = /dolibarr/mcp {", "location = /erp/mcp {")
    (tmp_path / "README.md").write_text(reworded, encoding="utf-8")
    out = _extract(tmp_path / "README.md")
    assert out.returncode == 0, out.stderr
    assert "server_name mcp.example.org;" in out.stdout and "location = /erp/mcp {" in out.stdout


@needs_sh
@pytest.mark.parametrize(("change", "message"), [
    (lambda s: s.replace("<!-- test-stack nginx block: mcp-prefix.", "<!-- prefix."),
     "no nginx block marked '<!-- test-stack nginx block: mcp-prefix -->'"),
    (lambda s: s.replace("block: mcp-server. The test stack's nginx variant (test-stack/nginx/build-conf.sh)"
                         " builds its configuration from the next code block. Keep this line directly above"
                         " it. -->\n", "block: mcp-server -->\n\n", 1),
     'the marker for "mcp-server" is not directly followed by a ```nginx block'),
    (lambda s: s.replace("block: mcp-prefix.", "block: mcp-server."),
     'the block "mcp-server" is marked twice'),
], ids=["marker-missing", "marker-not-above-block", "marked-twice"])
def test_a_broken_marker_stops_with_a_clear_message(tmp_path: Path, change, message):
    broken = change(_readme())
    assert broken != _readme()
    (tmp_path / "README.md").write_text(broken, encoding="utf-8")
    out = _extract(tmp_path / "README.md")
    assert out.returncode != 0
    assert message in out.stderr
    assert out.stdout == ""


def _openssl(*args: str, cwd: Path) -> str:
    return subprocess.run(["openssl", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _sans(certs: Path) -> set[str]:
    text = _openssl("x509", "-in", "site.crt", "-noout", "-text", cwd=certs)
    line = text.split("Subject Alternative Name", 1)[1].splitlines()[1]
    return {part.strip().removeprefix("DNS:") for part in line.split(",")}


def _make_certs(stack: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", str(stack / "make-certs.sh")], capture_output=True, text=True, timeout=60)


def _issue_site_without_apps(certs: Path) -> None:
    """A site.crt as make-certs.sh wrote it before apps.example.com was added, signed by a CA of its own."""
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-subj", "/CN=old",
             "-keyout", "old-ca.key", "-out", "old-ca.crt", cwd=certs)
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=example.com",
             "-keyout", "site.key", "-out", "site.csr", cwd=certs)
    (certs / "ext.cnf").write_text("subjectAltName=" + ",".join(f"DNS:{h}" for h in HOSTS[:4]) + "\n")
    _openssl("x509", "-req", "-in", "site.csr", "-CA", "old-ca.crt", "-CAkey", "old-ca.key",
             "-CAcreateserial", "-days", "30", "-extfile", "ext.cnf", "-out", "site.crt", cwd=certs)
    for name in ("site.csr", "ext.cnf", "old-ca.key", "old-ca.crt", "old-ca.srl"):
        (certs / name).unlink(missing_ok=True)


@needs_openssl
def test_make_certs_creates_a_certificate_for_every_hostname(tmp_path: Path):
    shutil.copy(MAKE_CERTS, tmp_path)
    out = _make_certs(tmp_path)
    assert out.returncode == 0, out.stderr
    assert _sans(tmp_path / "certs") == set(HOSTS)
    again = _make_certs(tmp_path)
    assert again.returncode == 0 and "keeping it" in again.stdout


@needs_openssl
def test_make_certs_reissues_a_site_certificate_that_lacks_a_hostname_with_the_same_ca(tmp_path: Path):
    shutil.copy(MAKE_CERTS, tmp_path)
    assert _make_certs(tmp_path).returncode == 0
    certs = tmp_path / "certs"
    ca = (certs / "ca.crt").read_bytes()
    _issue_site_without_apps(certs)
    assert "apps.example.com" not in _sans(certs)
    out = _make_certs(tmp_path)
    assert out.returncode == 0, out.stderr
    assert "lacks apps.example.com" in out.stdout
    assert _sans(certs) == set(HOSTS)
    assert (certs / "ca.crt").read_bytes() == ca
    _openssl("verify", "-CAfile", "ca.crt", "site.crt", cwd=certs)


@needs_openssl
def test_make_certs_makes_the_folder_again_without_the_ca_key(tmp_path: Path):
    shutil.copy(MAKE_CERTS, tmp_path)
    certs = tmp_path / "certs"
    certs.mkdir()
    _issue_site_without_apps(certs)
    shutil.copy(certs / "site.crt", certs / "ca.crt")   # some ca.crt, but no ca.key
    out = _make_certs(tmp_path)
    assert out.returncode == 0, out.stderr
    assert "made certs/ again" in out.stdout
    assert _sans(certs) == set(HOSTS)
    _openssl("verify", "-CAfile", "ca.crt", "site.crt", cwd=certs)


DISCOVERY_BLOCK = r"""location ~ ^/\.well-known/(oauth-authorization-server|openid-configuration)/custom/restoauth/?$ {
    rewrite ^ /custom/restoauth/metadata.php last;
}
"""


def _discovery(tmp_path: Path, restoauth_readme: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "restoauth.md").write_text(restoauth_readme, encoding="utf-8")
    return subprocess.run(["sh", str(BUILD_CONF), "--extract-only", str(ROOT / "README.md"),
                           str(tmp_path / "restoauth.md")],
                          capture_output=True, text=True, timeout=30)


@needs_sh
def test_discovery_block_is_found_by_its_marker(tmp_path: Path):
    other = "```nginx\nlocation /other/custom/restoauth/metadata.php { }\n```\n\n"
    marked = ("<!-- test-stack nginx block: restoauth-discovery. text -->\n```nginx\n"
              + DISCOVERY_BLOCK + "```\n")
    out = _discovery(tmp_path, other + marked)
    assert out.returncode == 0, out.stderr
    assert "restoauth discovery block: found by marker" in out.stderr
    assert "# ---- restoauth-discovery (found by marker) ----\n" + DISCOVERY_BLOCK in out.stdout


@needs_sh
def test_discovery_block_falls_back_to_its_text_without_marker(tmp_path: Path):
    out = _discovery(tmp_path, "```nginx\n" + DISCOVERY_BLOCK + "```\n")
    assert out.returncode == 0, out.stderr
    assert "restoauth discovery block: found by text (fallback" in out.stderr
    assert DISCOVERY_BLOCK in out.stdout


@needs_sh
def test_discovery_block_missing_stops(tmp_path: Path):
    out = _discovery(tmp_path, "```nginx\nserver { }\n```\n")
    assert out.returncode != 0
    assert "no nginx block with '/custom/restoauth/metadata.php'" in out.stderr
