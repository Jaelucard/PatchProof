"""Offline preview preparation contracts; no Docker or credentials are needed."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys

import pytest


APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("preview_prepare", APP / "deployment/preview/prepare.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
PASSWORD = "synthetic-review-only-" + "X" * 32
BCRYPT = "$2a$14$" + "A" * 53


def prepare(tmp_path, **kwargs):
    return preview.prepare(
        tmp_path / "private-review", hasher=lambda _: BCRYPT,
        password_factory=lambda: PASSWORD, **kwargs,
    )


@pytest.mark.parametrize("origin,port,expected", [
    (None, 8780, ("http://127.0.0.1:8780", "127.0.0.1:8780")),
    ("http://localhost:9010/", 9010, ("http://localhost:9010", "localhost:9010")),
    ("https://preview.example.test:443", 8780,
     ("https://preview.example.test", "preview.example.test")),
    ("https://preview.example.test:8443", 8780,
     ("https://preview.example.test:8443", "preview.example.test:8443")),
])
def test_explicit_origin_contract(origin, port, expected):
    assert preview.validate_origin(origin, port) == expected


@pytest.mark.parametrize("origin,port", [
    ("http://public.example:8780", 8780),
    ("http://127.0.0.1:9000", 8780),
    ("http://127.0.0.2:8780", 8780),
    ("http://[::1]:8780", 8780),
    ("https://user:secret@preview.example", 8780),
    ("https://preview.example/path", 8780),
    ("https://preview.example?query=yes", 8780),
    ("https://preview.example#fragment", 8780),
    ("https://preview.example\nroute", 8780),
    ("https://preview.example\"{", 8780),
    ("https://preview.example.", 8780),
    ("ftp://preview.example", 8780),
    ("https://preview.example:0", 8780),
    (None, 80), (None, 65536),
])
def test_unsafe_or_incoherent_origin_rejected_before_output(tmp_path, origin, port):
    with pytest.raises(preview.PreviewError):
        prepare(tmp_path, origin=origin, port=port)
    assert not (tmp_path / "private-review").exists()


def test_private_preparation_seeds_exact_history_and_reserves_exposure(tmp_path):
    result = prepare(tmp_path)
    root = Path(result["output_dir"])
    assert result["fixture_only"] is True
    assert result["username"] == "judge"
    assert root.stat().st_mode & 0o777 == 0o700
    for name in ("password.txt", "judge-users", "Caddyfile", "compose.json", "prepared.json"):
        info = (root / name).lstat()
        assert stat.S_ISREG(info.st_mode)
        assert info.st_uid == os.getuid()
        assert info.st_mode & 0o777 == 0o600
    assert (root / "password.txt").read_text() == PASSWORD + "\n"
    assert (root / "judge-users").read_text() == "judge " + BCRYPT + "\n"
    expected, _ = preview.load_seed()
    from patchproof.store import Store

    store = Store(root / "data/review.sqlite3")
    assert store.get(expected["id"]) == expected
    assert store.dataset(expected["dataset"]["dataset_id"]) == expected["dataset"]
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM case_exposure").fetchone()[0] == 40
        assert db.execute("SELECT sum(count) FROM case_exposure").fetchone()[0] == 40
    assert not (root / "data/provider-usage.sqlite3").exists()
    assert json.loads((root / "site/saved-evidence/live-diagnostic.json").read_text()) == expected


def test_compose_keeps_key_password_backend_and_admin_out_of_network_and_mounts(tmp_path):
    result = prepare(tmp_path)
    config = json.loads(Path(result["compose_file"]).read_text())
    app, gateway = config["services"]["app"], config["services"]["gateway"]
    assert app["ports"] == [{"target": 8780, "published": "8780", "host_ip": "127.0.0.1"}]
    assert gateway["network_mode"] == "service:app"
    assert gateway["image"] == "patchproof-preview-caddy:2.11.7"
    assert gateway["build"]["dockerfile"] == "deployment/preview/Caddy.Dockerfile"
    assert "ports" not in gateway
    assert app["command"] == [
        "python", "-B", "-m", "patchproof", "--database", "/data/review.sqlite3",
        "--port", "8770",
    ]
    for service in (app, gateway):
        assert service["user"] == f"{os.getuid()}:{os.getgid()}"
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert "env_file" not in service
        for mount in service["volumes"]:
            assert mount["bind"]["create_host_path"] is False
            assert "password.txt" not in mount["source"]
            assert "nebius" not in mount["source"]
    assert len(app["volumes"]) == 1
    assert "environment" not in app
    assert gateway["environment"] == {
        "PATCHPROOF_EXPECTED_UID": str(os.getuid()),
        "PATCHPROOF_EXPECTED_GID": str(os.getgid()),
    }
    assert gateway["entrypoint"] == ["/usr/local/bin/patchproof-gateway"]
    assert app["volumes"][0]["read_only"] is False
    assert all(m["read_only"] for m in gateway["volumes"])
    serialized = json.dumps(config)
    assert PASSWORD not in serialized and BCRYPT not in serialized
    assert "live-key" not in serialized and "confirm-live" not in serialized


def test_gateway_order_and_header_translation_contract(tmp_path):
    result = prepare(tmp_path)
    caddy = (Path(result["output_dir"]) / "Caddyfile").read_text()
    assert "__EXPECTED" not in caddy and "__PUBLIC" not in caddy
    order = [caddy.index(s) for s in (
        "respond @badHost", "respond @badOrigin", "respond @crossSite",
        "respond @badAuthorization", "basic_auth", "reverse_proxy",
    )]
    assert order == sorted(order)
    assert '@badHost expression {hostport} != "127.0.0.1:8780"' in caddy
    assert 'expression {http.request.header.Origin} != "http://127.0.0.1:8780"' in caddy
    cross_site = caddy.split("@crossSite expression <<CEL\n", 1)[1].split("\n\t\tCEL", 1)[0]
    assert '{http.request.header.Sec-Fetch-Site}.contains(",")' in cross_site
    assert '&& !(\n' in cross_site
    assert '{http.request.header.Sec-Fetch-Site} == "cross-site"' in cross_site
    for condition in (
        '&& ({method} == "GET" || {method} == "HEAD")',
        '&& {path} == "/"',
        '&& {http.request.header.Sec-Fetch-Mode} == "navigate"',
        '&& {http.request.header.Sec-Fetch-Dest} == "document"',
    ):
        assert condition in cross_site
    assert "Sec-Fetch-User" not in cross_site
    assert "header_up -Authorization" in caddy
    assert "header_up -Forwarded" in caddy
    assert "header_up -X-Forwarded-*" in caddy
    assert "admin off" in caddy and "persist_config off" in caddy
    assert "rewrite @workspace /" in caddy
    assert "import /run/secrets/judge-users" in caddy


def test_output_cannot_overwrite_source_existing_files_or_symlinks(tmp_path):
    with pytest.raises(preview.PreviewError):
        preview.prepare(APP / "private-preview", hasher=lambda _: BCRYPT)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(preview.PreviewError):
        preview.prepare(existing, hasher=lambda _: BCRYPT)
    target = tmp_path / "link"
    target.symlink_to(existing, target_is_directory=True)
    with pytest.raises(preview.PreviewError):
        preview.prepare(target, hasher=lambda _: BCRYPT)
    with pytest.raises(preview.PreviewError):
        preview.prepare(Path("relative-output"), hasher=lambda _: BCRYPT)


@pytest.mark.parametrize("username", [
    "", "judge\nadmin", "judge pass", "judge:pass", "x" * 65, "import", "IMPORT", "Import",
])
def test_credential_file_injection_rejected(tmp_path, username):
    with pytest.raises(preview.PreviewError):
        prepare(tmp_path, username=username)


def test_bcrypt_validation_and_hasher_error_never_reveal_password(tmp_path, capsys):
    with pytest.raises(preview.PreviewError):
        preview.prepare(tmp_path / "bad", hasher=lambda _: "not-bcrypt",
                        password_factory=lambda: PASSWORD)
    def bad_hasher(password):
        raise RuntimeError(password)
    with pytest.raises(preview.PreviewError) as caught:
        preview.prepare(tmp_path / "error", hasher=bad_hasher,
                        password_factory=lambda: PASSWORD)
    assert PASSWORD not in str(caught.value)
    assert PASSWORD not in capsys.readouterr().out
    assert not (tmp_path / "bad").exists()
    assert not (tmp_path / "error").exists()


def test_seed_identity_changes_fail_before_hasher_or_output(tmp_path, monkeypatch):
    monkeypatch.setattr(preview, "EVIDENCE_SHA256", "0" * 64)
    def forbidden(_):
        raise AssertionError("Hasher must not run")
    with pytest.raises(preview.PreviewError, match="evidence hash"):
        preview.prepare(tmp_path / "private", hasher=forbidden)
    assert not (tmp_path / "private").exists()


def test_seed_exposure_conflict_is_not_silently_rewritten(tmp_path):
    expected, _ = preview.load_seed()
    modified = deepcopy(expected)
    modified["prior_exposure"] = True
    with pytest.raises(preview.PreviewError, match="exact saved result"):
        preview.seed_database(tmp_path / "review.sqlite3", modified)


def test_caddy_helper_secret_uses_stdin_not_argv(monkeypatch):
    seen = {}
    def run(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        class Result:
            stdout = BCRYPT + "\n"
        return Result()
    monkeypatch.setattr(preview.subprocess, "run", run)
    assert preview.hash_password(PASSWORD) == BCRYPT
    assert PASSWORD not in " ".join(seen["argv"])
    assert seen["kwargs"]["input"] == PASSWORD + "\n"
    assert "--plaintext" not in seen["argv"]
    assert "--pull=never" in seen["argv"]


def test_cli_output_contains_paths_but_no_credential_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(preview, "hash_password", lambda _: BCRYPT)
    monkeypatch.setattr(preview.secrets, "token_urlsafe", lambda _: PASSWORD)
    preview.main(["--output-dir", str(tmp_path / "private"), "--port", "8990"])
    output = capsys.readouterr().out
    assert PASSWORD not in output and BCRYPT not in output
    assert json.loads(output)["url"] == "http://127.0.0.1:8990"


def run_gateway_guard(
    tmp_path, *, content=None, mode=0o600, uid="501", gid="20", kind="regular",
):
    """Exercise the shell guard with a fake Caddy and portable stat/id commands.

    Real container identity and bind behavior are separately integration-tested.
    """
    bind = tmp_path / "judge-users"
    if kind != "missing":
        bind.write_text("judge " + BCRYPT + "\n" if content is None else content)
        bind.chmod(mode)
        if kind == "symlink":
            target = tmp_path / "real-users"
            bind.rename(target)
            bind.symlink_to(target)
        elif kind == "directory":
            bind.unlink()
            bind.mkdir()
    commands = tmp_path / "bin"
    commands.mkdir()
    identity = commands / "id"
    identity.write_text("#!/bin/sh\ncase \"$1\" in -u) echo 501;; -g) echo 20;; *) exit 1;; esac\n")
    identity.chmod(0o700)
    metadata = commands / "stat"
    metadata.write_text(
        f"#!{sys.executable}\n"
        "import os,sys\n"
        "try:\n"
        " info=os.stat(sys.argv[3])\n"
        " print(format(info.st_mode & 0o7777,'o') if sys.argv[2]=='%a' else info.st_size)\n"
        "except OSError: sys.exit(1)\n"
    )
    metadata.chmod(0o700)
    marker = tmp_path / "caddy-started"
    fake = commands / "caddy"
    fake.write_text('#!/bin/sh\nprintf started > "$TEST_CADDY_MARKER"\n')
    fake.chmod(0o700)
    source = (APP / "deployment/preview/gateway-entrypoint.sh").read_text()
    source = source.replace("AUTH_FILE=/run/secrets/judge-users", "AUTH_FILE=" + shlex.quote(str(bind)))
    guard = tmp_path / "gateway.sh"
    guard.write_text(source)
    env = {"PATH": str(commands) + ":/usr/bin:/bin", "TEST_CADDY_MARKER": str(marker)}
    if uid is not None:
        env["PATCHPROOF_EXPECTED_UID"] = uid
    if gid is not None:
        env["PATCHPROOF_EXPECTED_GID"] = gid
    result = subprocess.run(["sh", str(guard), "run"], env=env, text=True, capture_output=True)
    return result, marker


@pytest.mark.parametrize("mode", [0o400, 0o600])
def test_gateway_guard_accepts_matching_nonroot_identity_and_private_one_line_hash(tmp_path, mode):
    result, marker = run_gateway_guard(tmp_path, mode=mode)
    assert result.returncode == 0
    assert marker.read_text() == "started"
    assert result.stdout == result.stderr == ""


@pytest.mark.parametrize("uid,gid", [
    (None, "20"), ("501", None), ("0", "20"), ("00", "20"),
    ("0501", "20"), ("501", "020"), ("50501", "20"), ("501", "21"),
    ("not-a-number", "20"), ("501\n", "20"), ("9" * 50, "20"),
])
def test_gateway_guard_rejects_invalid_or_changed_runtime_identity(tmp_path, uid, gid):
    result, marker = run_gateway_guard(tmp_path, uid=uid, gid=gid)
    assert result.returncode != 0
    assert not marker.exists()
    assert result.stdout == ""
    assert result.stderr == "PatchProof gateway refused unsafe startup.\n"


@pytest.mark.parametrize("kind,mode,content", [
    ("missing", 0o600, None), ("symlink", 0o600, None), ("directory", 0o600, None),
    ("regular", 0o644, None), ("regular", 0o660, None), ("regular", 0o700, None),
    ("regular", 0o600, ""), ("regular", 0o600, "do-not-log-this-credential" * 20),
    ("regular", 0o600, "judge " + BCRYPT + "\nsecond " + BCRYPT + "\n"),
    ("regular", 0o600, "judge " + BCRYPT + "\n\n"),
    ("regular", 0o600, "judge:inject " + BCRYPT + "\n"),
    ("regular", 0o600, "judge  " + BCRYPT + "\n"),
    ("regular", 0o600, "import " + BCRYPT + "\n"),
    ("regular", 0o600, "IMPORT " + BCRYPT + "\n"),
    ("regular", 0o600, "judge $2a$99$" + "A" * 53 + "\n"),
    ("regular", 0o600, "judge $2a$14$" + ":" * 53 + "\n"),
])
def test_gateway_guard_rejects_unsafe_hash_file_before_parser_without_content_leak(
    tmp_path, kind, mode, content,
):
    result, marker = run_gateway_guard(tmp_path, kind=kind, mode=mode, content=content)
    assert result.returncode != 0
    assert not marker.exists()
    assert result.stdout == ""
    assert result.stderr == "PatchProof gateway refused unsafe startup.\n"
    assert BCRYPT not in result.stderr
    assert "do-not-log-this-credential" not in result.stderr


def test_gateway_errors_have_separate_controlled_security_headers_without_error_details(tmp_path):
    result = prepare(tmp_path)
    caddy = (Path(result["output_dir"]) / "Caddyfile").read_text()
    error_route = caddy.split("handle_errors {", 1)[1].split("\n\troute {", 1)[0]
    assert 'Cache-Control "no-store"' in error_route
    assert 'X-Content-Type-Options "nosniff"' in error_route
    assert "Content-Security-Policy" in error_route
    assert '?WWW-Authenticate "Basic realm=\\"PatchProof\\""' in error_route
    assert 'respond "{err.status_text}" {err.status_code}' in error_route
    assert "err.message" not in caddy and "err.trace" not in caddy
