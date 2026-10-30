"""Deployment boundaries, using synthetic state and fake child processes only."""
from dataclasses import replace
import base64
import builtins
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runtime", ROOT / "deployment/hosted/runtime.py")
hosted = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hosted
SPEC.loader.exec_module(hosted)
SEED_SPEC = importlib.util.spec_from_file_location("hosted_seed", ROOT / "deployment/hosted/create_seed.py")
seed_tool = importlib.util.module_from_spec(SEED_SPEC)
SEED_SPEC.loader.exec_module(seed_tool)
AUTH = b"judge $2a$14$" + b"A" * 53 + b"\n"
KEY = b"synthetic-test-provider-key-never-valid"


def config(**changes):
    result = hosted.configuration({"RENDER_EXTERNAL_URL": "https://patchproof.example.test"})
    return replace(result, **changes)


def make_sources(tmp_path):
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    app = source / "review.sqlite3"
    with sqlite3.connect(app) as db:
        db.executescript("""
            CREATE TABLE experiments (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE datasets (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE exposure (version_hash TEXT PRIMARY KEY, count INTEGER NOT NULL);
            CREATE TABLE case_exposure (case_hash TEXT PRIMARY KEY, count INTEGER NOT NULL);
            INSERT INTO experiments VALUES ('saved', '{"id":"saved","status":"completed"}');
            INSERT INTO datasets VALUES ('dataset','{}');
            INSERT INTO exposure VALUES ('version',2);
            INSERT INTO case_exposure VALUES ('case',3);
        """)
    ledger = source / "provider-usage.sqlite3"
    with sqlite3.connect(ledger) as db:
        db.executescript("""
            CREATE TABLE usage (id TEXT PRIMARY KEY, reserved INTEGER NOT NULL, charged INTEGER, state TEXT NOT NULL);
            INSERT INTO usage VALUES ('first',100,60,'accounted');
            INSERT INTO usage VALUES ('unknown',200,NULL,'usage_unknown');
        """)
    app.chmod(0o600)
    ledger.chmod(0o600)
    app.with_name(app.name + ".lock").touch(mode=0o600)
    return app


@pytest.fixture
def seeded(tmp_path):
    app = make_sources(tmp_path)
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    seed = secrets / "patchproof-state.b64"
    receipt = seed_tool.create_seed(app, seed, source_stopped=True)
    data = tmp_path / "volume"
    data.mkdir(mode=0o700)
    cfg = config(bootstrap=True, seed_sha256=receipt["seed_sha256"])
    return data, secrets, cfg, receipt


@pytest.mark.parametrize("env", [
    {}, {"RENDER_EXTERNAL_URL": "http://example.test"},
    {"RENDER_EXTERNAL_URL": "https://user:private@example.test"},
    {"RENDER_EXTERNAL_URL": "https://example.test/path"},
    {"RENDER_EXTERNAL_URL": "https://example.test?query=1"},
    {"RENDER_EXTERNAL_URL": "https://example.test#fragment"},
    {"RENDER_EXTERNAL_URL": "https://127.0.0.1"},
    {"RENDER_EXTERNAL_URL": "https://example.test."},
    {"RENDER_EXTERNAL_URL": "https://example.test\n"},
    {"RENDER_EXTERNAL_URL": "https://example.test:8780"},
    {"RENDER_EXTERNAL_URL": "https://example.test", "PORT": "8770"},
    {"RENDER_EXTERNAL_URL": "https://example.test", "PATCHPROOF_BOOTSTRAP": "true"},
    {"RENDER_EXTERNAL_URL": "https://example.test", "PATCHPROOF_BOOTSTRAP": "1"},
    {"RENDER_EXTERNAL_URL": "https://example.test", "PATCHPROOF_LIVE_ENABLED": "1"},
    {"RENDER_EXTERNAL_URL": "https://example.test", "PATCHPROOF_LIVE_ENABLED": "1", "PATCHPROOF_BOOTSTRAP": "1"},
])
def test_unsafe_or_incomplete_activation_fails(env):
    with pytest.raises(hosted.HostedError):
        hosted.configuration(env)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "0", "1.00001", "not-a-number", ""])
def test_live_cap_cannot_exceed_existing_subcap(amount):
    with pytest.raises(hosted.HostedError):
        hosted.configuration({"RENDER_EXTERNAL_URL": "https://example.test", "PATCHPROOF_LIVE_ENABLED": "1",
                              "PATCHPROOF_CONFIRM_NEBIUS_ACCESS": "1", "PATCHPROOF_CONFIRM_LIVE_CAP": "1",
                              "PATCHPROOF_LIVE_CAP_USD": amount})


def test_live_flags_explicit_and_key_is_only_a_file_path():
    cfg = hosted.configuration({"RENDER_EXTERNAL_URL": "https://example.test:443/", "PATCHPROOF_LIVE_ENABLED": "1",
                                "PATCHPROOF_CONFIRM_NEBIUS_ACCESS": "1", "PATCHPROOF_CONFIRM_LIVE_CAP": "1",
                                "PATCHPROOF_LIVE_CAP_USD": "0.5"})
    assert cfg.origin == "https://example.test"
    command = hosted.backend_command(Path("/data/state"), cfg, Path("/private/nebius-tokenfactory.key"))
    assert command[-4:] == ["--live-cap-usd", "0.5", "--confirm-nebius-access", "--confirm-live-cap"]
    assert "--live-key-file" in command
    assert KEY.decode() not in " ".join(command)
    assert "--live-key-file" not in hosted.backend_command(Path("/data/state"), config(), Path("unused"))


def test_bootstrap_preserves_both_databases_full_tables_and_unresolved_usage(seeded):
    data, secrets, cfg, receipt = seeded
    summaries = hosted.prepare_state(data, cfg, secrets)
    assert summaries == {name: metadata["summary"] for name, metadata in receipt["files"].items()}
    assert summaries["review.sqlite3"]["rows"] == {"experiments": 1, "datasets": 1, "exposure": 1, "case_exposure": 1}
    assert summaries["provider-usage.sqlite3"]["charged_or_reserved_nanodollars"] == 260
    for name in hosted.STATE_NAMES:
        path = data / "state" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["files"][name]["sha256"]
        assert path.stat().st_mode & 0o777 == 0o600
    assert (data / "state").stat().st_mode & 0o777 == 0o700
    assert not list(data.glob(".bootstrap-*"))


def test_normal_restart_keeps_new_ledger_entries_and_does_not_need_seed(seeded):
    data, secrets, cfg, _ = seeded
    hosted.prepare_state(data, cfg, secrets)
    ledger = data / "state/provider-usage.sqlite3"
    with sqlite3.connect(ledger) as db:
        db.execute("INSERT INTO usage VALUES ('later',500,400,'accounted')")
    (secrets / "patchproof-state.b64").unlink()
    summary = hosted.prepare_state(data, replace(cfg, bootstrap=False), secrets)
    assert summary["provider-usage.sqlite3"]["rows"]["usage"] == 3
    assert summary["provider-usage.sqlite3"]["charged_or_reserved_nanodollars"] == 660


def test_normal_history_can_grow_past_transfer_limit_but_cannot_be_reseeded(seeded, monkeypatch):
    data, secrets, cfg, _ = seeded
    hosted.prepare_state(data, cfg, secrets)
    database = data / "state/review.sqlite3"
    payload = json.dumps({"synthetic_history": "x" * (1024 * 1024)})
    with sqlite3.connect(database) as db:
        db.executemany("INSERT INTO datasets VALUES (?,?)",
                       (("growth-" + str(i), payload) for i in range(25)))
    assert database.stat().st_size > hosted.MAX_DATABASE_BYTES

    class BoundedReads:
        """Reject whole-file Python buffering while allowing streamed snapshots."""
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size=-1):
            assert 0 <= size <= 1024 * 1024, "normal validation tried to buffer a large file"
            return self.stream.read(size)

    def bounded_open(original):
        def opened(*args, **kwargs):
            stream = original(*args, **kwargs)
            if os.fstat(stream.fileno()).st_size > hosted.MAX_DATABASE_BYTES:
                return BoundedReads(stream)
            return stream
        return opened

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", bounded_open(builtins.open))
        guard.setattr(io, "open", bounded_open(io.open))
        summary = hosted.prepare_state(data, replace(cfg, bootstrap=False), secrets)
    assert summary["review.sqlite3"]["rows"]["datasets"] == 26
    assert summary["provider-usage.sqlite3"]["charged_or_reserved_nanodollars"] == 260
    with pytest.raises(hosted.HostedError, match="invalid type or size"):
        seed_tool.create_seed(database, secrets / "oversized-transfer.b64", source_stopped=True)
    assert not (secrets / "oversized-transfer.b64").exists()


@pytest.mark.parametrize("name", ["review.sqlite3", "provider-usage.sqlite3", "bootstrap-receipt.json"])
def test_missing_state_part_never_restores_old_seed(seeded, name):
    data, secrets, cfg, _ = seeded
    hosted.prepare_state(data, cfg, secrets)
    (data / "state" / name).unlink()
    for mode in (replace(cfg, bootstrap=False), cfg):
        with pytest.raises(hosted.HostedError):
            hosted.prepare_state(data, mode, secrets)
    assert not (data / "state" / name).exists()


def test_empty_replaced_volume_in_normal_mode_never_bootstraps(seeded):
    data, secrets, cfg, _ = seeded
    with pytest.raises(hosted.HostedError, match="never restores"):
        hosted.prepare_state(data, replace(cfg, bootstrap=False), secrets)
    assert not (data / "state").exists()


def test_partial_bootstrap_requires_operator_inspection(seeded):
    data, secrets, cfg, _ = seeded
    (data / ".bootstrap-interrupted").mkdir()
    with pytest.raises(hosted.HostedError, match="incomplete bootstrap"):
        hosted.prepare_state(data, cfg, secrets)
    assert not (data / "state").exists()


def test_state_symlink_is_rejected_without_mutating_target(seeded, tmp_path):
    data, secrets, cfg, _ = seeded
    target = tmp_path / "unrelated"
    target.mkdir(mode=0o700)
    (data / "state").symlink_to(target, target_is_directory=True)
    with pytest.raises(hosted.HostedError):
        hosted.prepare_state(data, cfg, secrets)
    assert not list(target.iterdir())


def test_database_symlink_and_ledger_loss_rejected(seeded):
    data, secrets, cfg, _ = seeded
    hosted.prepare_state(data, cfg, secrets)
    ledger = data / "state/provider-usage.sqlite3"
    original = ledger.with_name("original.sqlite3")
    ledger.rename(original)
    ledger.symlink_to(original)
    with pytest.raises(hosted.HostedError):
        hosted.verify_state(data / "state")
    ledger.unlink()
    original.rename(ledger)
    with sqlite3.connect(ledger) as db:
        db.execute("DELETE FROM usage WHERE id='first'")
    with pytest.raises(hosted.HostedError, match="lost rows"):
        hosted.verify_state(data / "state")


def test_ledger_accounted_cost_cannot_disappear(seeded):
    data, secrets, cfg, _ = seeded
    hosted.prepare_state(data, cfg, secrets)
    with sqlite3.connect(data / "state/provider-usage.sqlite3") as db:
        db.execute("UPDATE usage SET charged=0 WHERE id='first'")
    with pytest.raises(hosted.HostedError, match="lost accounted usage"):
        hosted.verify_state(data / "state")


def mutate_seed(secrets, mutate):
    path = secrets / "patchproof-state.b64"
    seed = json.loads(gzip.decompress(base64.b64decode(path.read_bytes())))
    mutate(seed)
    content = base64.b64encode(gzip.compress(json.dumps(seed).encode())) + b"\n"
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize("mutation", [
    lambda seed: seed["files"].update({"../outside.sqlite3": seed["files"]["review.sqlite3"]}),
    lambda seed: seed["files"]["review.sqlite3"].update(sha256="0" * 64),
    lambda seed: seed["files"]["review.sqlite3"].update(bytes=1),
    lambda seed: seed["files"]["review.sqlite3"].update(bytes=hosted.MAX_DATABASE_BYTES + 1),
    lambda seed: seed["files"]["review.sqlite3"].update(base64="not base64!"),
    lambda seed: seed.update(version=True),
])
def test_seed_rejects_wrong_names_digests_sizes_and_version(seeded, mutation):
    data, secrets, cfg, _ = seeded
    digest = mutate_seed(secrets, mutation)
    with pytest.raises(hosted.HostedError):
        hosted.prepare_state(data, replace(cfg, seed_sha256=digest), secrets)
    assert not (data / "state").exists()


def test_seed_metadata_row_counts_checked_after_restore(seeded):
    data, secrets, cfg, _ = seeded
    digest = mutate_seed(secrets, lambda seed: seed["files"]["review.sqlite3"]["summary"]["rows"].update(experiments=99))
    with pytest.raises(hosted.HostedError, match="counts differ"):
        hosted.prepare_state(data, replace(cfg, seed_sha256=digest), secrets)
    assert not (data / "state").exists()
    assert list(data.glob(".bootstrap-*"))


def test_seed_hash_and_decompression_limit(seeded, monkeypatch):
    _, secrets, cfg, _ = seeded
    content = (secrets / "patchproof-state.b64").read_bytes()
    with pytest.raises(hosted.HostedError, match="SHA-256"):
        hosted.decode_seed(content, "0" * 64)
    monkeypatch.setattr(hosted, "MAX_PAYLOAD_BYTES", 128)
    with pytest.raises(hosted.HostedError):
        hosted.decode_seed(content, cfg.seed_sha256)


def test_invalid_database_schema_and_trigger_rejected(seeded):
    data, secrets, cfg, _ = seeded
    hosted.prepare_state(data, cfg, secrets)
    with sqlite3.connect(data / "state/review.sqlite3") as db:
        db.execute("CREATE TRIGGER surprise AFTER INSERT ON datasets BEGIN DELETE FROM case_exposure; END")
    with pytest.raises(hosted.HostedError, match="schema"):
        hosted.verify_state(data / "state")


def test_seed_helper_requires_stopped_source_and_existing_owner_lock(tmp_path):
    app = make_sources(tmp_path)
    destination = tmp_path / "private"
    destination.mkdir(mode=0o700)
    with pytest.raises(hosted.HostedError):
        seed_tool.create_seed(app, destination / "state.b64", source_stopped=False)
    with hosted.owner_lock(app.with_name(app.name + ".lock")):
        with pytest.raises(hosted.HostedError, match="Another process"):
            seed_tool.create_seed(app, destination / "state.b64", source_stopped=True)
    assert not (destination / "state.b64").exists()


def test_runtime_keeps_secrets_outside_served_roots_and_reuses_gateway_guard(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "judge-users").write_bytes(AUTH)
    (secrets / "nebius-tokenfactory.key").write_bytes(KEY)
    runtime = tmp_path / "runtime"
    cfg = config(live=True, cap="1")
    caddyfile, key = hosted.prepare_runtime(cfg, secrets, runtime)
    for path in (runtime / "judge-users", key):
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent == runtime
        assert not path.is_relative_to(runtime / "site")
    caddy = caddyfile.read_text()
    template = (ROOT / "deployment/preview/Caddyfile.template").read_text()
    expected = (template.replace("__EXPECTED_HOST__", cfg.host).replace("__PUBLIC_ORIGIN__", cfg.origin)
                .replace("/run/secrets/judge-users", str(runtime / "judge-users"))
                .replace("/srv/preview", str(runtime / "site")))
    assert caddy == expected
    assert "respond @badHost" in caddy and "header_up -Authorization" in caddy
    guard = (runtime / "gateway-entrypoint.sh").read_text()
    assert guard.replace(str(runtime / "judge-users"), "/run/secrets/judge-users") == (ROOT / "deployment/preview/gateway-entrypoint.sh").read_text()
    for path in (runtime / "site").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_bytes() and AUTH.strip() not in path.read_bytes()
    assert "Live NVIDIA-on-Nebius inference is available" in (runtime / "site/index.html").read_text()
    landing = (runtime / "site/index.html").read_text()
    assert "ba2420e6-2691-47a2-b993-18c35e1c1955" in landing
    assert "browser's local timezone" in landing
    assert "29 October at 01:38" not in landing


def test_fixture_runtime_does_not_read_provider_key(tmp_path):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "judge-users").write_bytes(AUTH)
    (secrets / "nebius-tokenfactory.key").symlink_to(tmp_path / "missing")
    _, key = hosted.prepare_runtime(config(), secrets, tmp_path / "runtime")
    assert not key.exists()
    assert "Live inference is disabled" in (tmp_path / "runtime/site/index.html").read_text()


@pytest.mark.parametrize("content", [b"import /private/file", AUTH + AUTH, b"judge secret", AUTH.replace(b"$14$", b"$04$")])
def test_invalid_auth_never_echoes_credential(content):
    with pytest.raises(hosted.HostedError) as caught:
        hosted.validate_auth(content)
    assert "secret" not in str(caught.value) and content.decode() not in str(caught.value)


def test_symlink_secret_and_world_readable_private_copy_rejected(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(KEY)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(hosted.HostedError):
        hosted.regular_file(link, limit=8192)
    target.chmod(0o644)
    with pytest.raises(hosted.HostedError):
        hosted.regular_file(target, limit=8192, private=True)


class Child:
    def __init__(self, running=True, stubborn=False):
        self.running, self.stubborn = running, stubborn
        self.terminated = self.killed = False

    def poll(self):
        return None if self.running else 17

    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self.running = False

    def kill(self):
        self.killed = True
        self.running = False

    def wait(self, timeout=None):
        if self.running:
            raise subprocess.TimeoutExpired("synthetic", timeout)
        return 17


def test_backend_readiness_failure_never_starts_gateway():
    children = []

    def popen(*args, **kwargs):
        child = Child()
        children.append(child)
        return child

    def failed(*args, **kwargs):
        raise hosted.HostedError("synthetic readiness failure")

    with pytest.raises(hosted.HostedError):
        hosted.supervise(["synthetic-backend"], Path("/private/Caddyfile"), popen=popen, readiness=failed)
    assert len(children) == 1 and children[0].terminated


def test_child_failure_stops_both_and_suppresses_child_output():
    children, calls = [], []

    def popen(command, **kwargs):
        child = Child(running=len(children) == 0)
        children.append(child)
        calls.append((command, kwargs))
        return child

    with pytest.raises(hosted.HostedError, match="required hosted process"):
        hosted.supervise(["synthetic-backend"], Path("/private/Caddyfile"), popen=popen, readiness=lambda *a, **k: None)
    assert children[0].terminated
    assert calls[1][0][0:2] == ["/bin/sh", "/private/gateway-entrypoint.sh"]
    assert all(call[1]["stderr"] == subprocess.DEVNULL for call in calls)


def test_signal_during_readiness_stops_backend_without_gateway():
    children = []

    def popen(*args, **kwargs):
        child = Child()
        children.append(child)
        return child

    def ready(*args, **kwargs):
        os.kill(os.getpid(), signal.SIGTERM)

    original = signal.getsignal(signal.SIGTERM)
    assert hosted.supervise(["synthetic"], Path("/private/Caddyfile"), popen=popen, readiness=ready) == 0
    assert len(children) == 1 and children[0].terminated
    assert signal.getsignal(signal.SIGTERM) == original


def test_stubborn_child_is_killed_after_grace():
    child = Child(stubborn=True)
    hosted.stop_children([child], grace=0)
    assert child.terminated and child.killed


def test_build_inputs_explicitly_exclude_render_secret_filenames():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    for name in ("nebius-tokenfactory.key", "judge-users", "patchproof-state.b64", "password.txt"):
        assert "**/" + name in ignore
    dockerfile = (ROOT / "deployment/hosted/Dockerfile").read_text()
    assert "COPY . " not in dockerfile and "COPY . ." not in dockerfile
    assert "USER 10001:1000" in dockerfile
    assert "secret" not in "\n".join(line for line in dockerfile.splitlines() if line.startswith("COPY "))
    blueprint = (ROOT / "deployment/hosted/render.yaml").read_text()
    assert "autoDeployTrigger: off" in blueprint
    assert not any(line.lstrip().startswith("healthCheckPath:") for line in blueprint.splitlines())
