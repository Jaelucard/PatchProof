"""Render process supervisor and explicit, one-time state bootstrap.

Only deployment packaging lives here. The application, live-key reader, usage
ledger and gateway request boundary retain their existing behavior.
"""
from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import urllib.request

APP_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_ROOT / "backend"))
from patchproof.sqlite_inspection import inspect_database  # noqa: E402

STATE_NAMES = ("review.sqlite3", "provider-usage.sqlite3")
MAX_SEED_BYTES = 990_000
MAX_PAYLOAD_BYTES = 64 * 1024 * 1024
MAX_DATABASE_BYTES = 24 * 1024 * 1024
EXPECTED_UID, EXPECTED_GID = 10001, 1000
SCHEMAS = {
    "review.sqlite3": {
        "experiments": [("id", "TEXT", 0, 1), ("payload", "TEXT", 1, 0)],
        "datasets": [("id", "TEXT", 0, 1), ("payload", "TEXT", 1, 0)],
        "exposure": [("version_hash", "TEXT", 0, 1), ("count", "INTEGER", 1, 0)],
        "case_exposure": [("case_hash", "TEXT", 0, 1), ("count", "INTEGER", 1, 0)],
    },
    "provider-usage.sqlite3": {
        "usage": [("id", "TEXT", 0, 1), ("reserved", "INTEGER", 1, 0),
                  ("charged", "INTEGER", 0, 0), ("state", "TEXT", 1, 0)],
    },
}


class HostedError(ValueError):
    """Messages are fixed operational descriptions, never source/secret content."""


@dataclass(frozen=True)
class Configuration:
    origin: str
    host: str
    bootstrap: bool
    live: bool
    cap: str | None
    seed_sha256: str | None


def configuration(environ: dict[str, str]) -> Configuration:
    if environ.get("PORT", "8780") != "8780":
        raise HostedError("Set the Render public PORT to 8780.")
    raw = environ.get("RENDER_EXTERNAL_URL", "")
    if not raw.isascii() or any(c.isspace() for c in raw):
        raise HostedError("A valid public HTTPS origin is required.")
    try:
        url = urlsplit(raw)
        hostname, port = url.hostname, url.port
    except ValueError:
        raise HostedError("A valid public HTTPS origin is required.") from None
    if (
        url.scheme != "https" or not hostname or port not in (None, 443)
        or url.username is not None or url.password is not None
        or url.path not in ("", "/") or url.query or url.fragment
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+", hostname)
        or hostname == "localhost" or re.fullmatch(r"[0-9.]+", hostname)
    ):
        raise HostedError("A valid public HTTPS origin is required.")
    flags = []
    for name in ("PATCHPROOF_BOOTSTRAP", "PATCHPROOF_LIVE_ENABLED"):
        value = environ.get(name, "0")
        if value not in ("0", "1"):
            raise HostedError("Hosted activation flags must be exactly 0 or 1.")
        flags.append(value == "1")
    bootstrap, live = flags
    if bootstrap and live:
        raise HostedError("One-time bootstrap must finish with live inference disabled.")
    seed_sha = environ.get("PATCHPROOF_SEED_SHA256")
    if bootstrap and (not seed_sha or not re.fullmatch(r"[0-9a-f]{64}", seed_sha)):
        raise HostedError("Bootstrap requires the approved seed SHA-256.")
    cap = None
    if live:
        if environ.get("PATCHPROOF_CONFIRM_NEBIUS_ACCESS") != "1":
            raise HostedError("Confirm current Nebius credit access before live activation.")
        if environ.get("PATCHPROOF_CONFIRM_LIVE_CAP") != "1":
            raise HostedError("Confirm the cumulative inference cap before live activation.")
        try:
            amount = Decimal(environ.get("PATCHPROOF_LIVE_CAP_USD", ""))
        except InvalidOperation:
            raise HostedError("Hosted live cap must be positive and at most one USD.") from None
        if not amount.is_finite() or not Decimal(0) < amount <= Decimal(1):
            raise HostedError("Hosted live cap must be positive and at most one USD.")
        cap = str(amount)
    return Configuration("https://" + hostname, hostname, bootstrap, live, cap, seed_sha)


@contextmanager
def checked_regular_file(path: Path, *, limit: int | None = None, private: bool = False):
    """Validate file identity; transfer limits do not constrain persisted history."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size <= 0
                or (limit is not None and info.st_size > limit)):
                raise HostedError("A required hosted file has an invalid type or size.")
            if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise HostedError("Hosted private files must be owned by the service user and private.")
            yield stream
    except OSError:
        raise HostedError("A required hosted file is unavailable; startup was refused.") from None


def regular_file(path: Path, *, limit: int, private: bool = False) -> bytes:
    """Read a bounded transfer or credential file, without following symlinks."""
    with checked_regular_file(path, limit=limit, private=private) as stream:
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise HostedError("A required hosted file exceeds its size limit.")
        return data


def private_write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def private_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise HostedError("Hosted private directories must be owned by the service user with mode 700.")


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def owner_lock(path: Path, *, create: bool = True):
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise HostedError("State ownership lock is not a service-owned regular file.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HostedError("Another process owns this state; startup was refused.") from None
        yield
    finally:
        os.close(fd)


def database_summary(path: Path, name: str, *, private: bool = True) -> dict:
    # Normal history can grow beyond the bounded initial transfer. Validate
    # identity without reading the whole database into memory or applying the
    # seed size cap, then retain all schema, integrity and accounting checks.
    with checked_regular_file(path, private=private):
        pass
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            info = sidecar.lstat()
            if not stat.S_ISREG(info.st_mode) or (private and info.st_uid != os.getuid()):
                raise HostedError("Unsafe database sidecar; startup was refused.")
    try:
        with inspect_database(path) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            objects = {(kind, item) for kind, item in db.execute("SELECT type,name FROM sqlite_master")
                       if not item.startswith("sqlite_")}
            expected = SCHEMAS[name]
            if objects != {("table", item) for item in expected}:
                raise HostedError("Required hosted database schema does not match.")
            for table, columns in expected.items():
                actual = [(r[1], r[2].upper(), r[3], r[5])
                          for r in db.execute(f"PRAGMA table_info({table})")]
                if actual != columns:
                    raise HostedError("Required hosted database columns do not match.")
            if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise HostedError("Hosted database integrity check failed.")
            counts = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in expected}
            result = {"rows": counts}
            if name == "provider-usage.sqlite3":
                rows = db.execute("SELECT reserved,charged,state FROM usage").fetchall()
                if any(type(r) is not int or r < 0 or (c is not None and (type(c) is not int or c < 0))
                       or s not in ("reserved", "accounted", "usage_unknown", "usage_exceeded")
                       for r, c, s in rows):
                    raise HostedError("Hosted usage ledger contains invalid accounting values.")
                result["charged_or_reserved_nanodollars"] = sum(c if c is not None else r for r, c, _ in rows)
                result["accounted_nanodollars"] = sum(c for _, c, s in rows if s == "accounted" and c is not None)
            return result
    except (sqlite3.Error, OSError, ValueError) as exc:
        if isinstance(exc, HostedError):
            raise
        raise HostedError("Hosted database inspection failed; startup was refused.") from None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HostedError("Seed metadata contains duplicate fields.")
        result[key] = value
    return result


def decode_seed(encoded: bytes, expected_sha256: str) -> dict:
    if len(encoded) > MAX_SEED_BYTES or hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise HostedError("Seed size or approved SHA-256 does not match.")
    try:
        compressed = base64.b64decode(encoded.strip(), validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
            raw = stream.read(MAX_PAYLOAD_BYTES + 1)
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise HostedError("Seed decompressed content exceeds its limit.")
        data = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, OSError, EOFError, UnicodeError, binascii.Error):
        raise HostedError("Seed content is not valid bounded base64/gzip JSON.") from None
    if (
        not isinstance(data, dict) or set(data) != {"version", "files"}
        or type(data["version"]) is not int or data["version"] != 1
        or not isinstance(data["files"], dict) or set(data["files"]) != set(STATE_NAMES)
    ):
        raise HostedError("Seed must contain exactly the two approved version-one databases.")
    for name in STATE_NAMES:
        entry = data["files"][name]
        if (
            not isinstance(entry, dict) or set(entry) != {"base64", "bytes", "sha256", "summary"}
            or type(entry["bytes"]) is not int or not 0 < entry["bytes"] <= MAX_DATABASE_BYTES
            or not isinstance(entry["base64"], str) or len(entry["base64"]) > MAX_DATABASE_BYTES * 2
            or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            or not isinstance(entry["summary"], dict)
        ):
            raise HostedError("Seed database metadata is invalid.")
        try:
            content = base64.b64decode(entry["base64"], validate=True)
        except (ValueError, binascii.Error):
            raise HostedError("Seed database encoding is invalid.") from None
        if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise HostedError("Seed database size or digest does not match.")
        entry["content"] = content
    return data


def verify_state(state: Path) -> dict:
    private_directory(state)
    marker = regular_file(state / "bootstrap-receipt.json", limit=8192, private=True)
    try:
        receipt = json.loads(marker, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        raise HostedError("Hosted bootstrap receipt is invalid.") from None
    if (not isinstance(receipt, dict) or set(receipt) != {"version", "seed_sha256", "files"}
        or type(receipt["version"]) is not int or receipt["version"] != 1
        or not isinstance(receipt["seed_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", receipt["seed_sha256"])
        or not isinstance(receipt["files"], dict)
        or set(receipt["files"]) != set(STATE_NAMES)):
        raise HostedError("Hosted bootstrap receipt is incomplete.")
    current = {}
    for name in STATE_NAMES:
        summary = database_summary(state / name, name)
        baseline = receipt["files"][name]
        if not isinstance(baseline, dict) or set(baseline) != set(summary):
            raise HostedError("Hosted bootstrap receipt has invalid accounting metadata.")
        if not isinstance(baseline["rows"], dict) or set(baseline["rows"]) != set(summary["rows"]):
            raise HostedError("Hosted bootstrap receipt has invalid table counts.")
        for table, count in baseline["rows"].items():
            if type(count) is not int or count < 0 or summary["rows"][table] < count:
                raise HostedError("Hosted state lost rows since initialization; recovery is required.")
        if name == "provider-usage.sqlite3":
            for field in ("charged_or_reserved_nanodollars", "accounted_nanodollars"):
                if type(baseline[field]) is not int or baseline[field] < 0:
                    raise HostedError("Hosted bootstrap receipt has invalid usage values.")
            if summary["accounted_nanodollars"] < baseline["accounted_nanodollars"]:
                raise HostedError("Hosted ledger lost accounted usage; recovery is required.")
        current[name] = summary
    return current


def prepare_state(data_root: Path, config: Configuration, secrets_root: Path) -> dict:
    """Never restores a missing normal-mode ledger, even if an old seed is present."""
    state = data_root / "state"
    if state.exists() or state.is_symlink():
        return verify_state(state)
    if not config.bootstrap:
        raise HostedError("Persistent state is missing. Normal startup never restores an old ledger.")
    if any(p.name.startswith(".bootstrap-") for p in data_root.iterdir()):
        raise HostedError("An incomplete bootstrap exists; inspect it before retrying.")
    encoded = regular_file(secrets_root / "patchproof-state.b64", limit=MAX_SEED_BYTES)
    seed = decode_seed(encoded, config.seed_sha256)
    stage = Path(tempfile.mkdtemp(prefix=".bootstrap-", dir=data_root))
    try:
        summaries = {}
        for name in STATE_NAMES:
            entry = seed["files"][name]
            private_write(stage / name, entry["content"])
            summary = database_summary(stage / name, name)
            if summary != entry["summary"]:
                raise HostedError("Restored database counts differ from the approved seed metadata.")
            summaries[name] = summary
        receipt = {"version": 1, "seed_sha256": config.seed_sha256, "files": summaries}
        private_write(stage / "bootstrap-receipt.json", json.dumps(receipt, sort_keys=True).encode())
        sync_directory(stage)
        # The caller holds a persistent-volume ownership lock across initialization and serving.
        if state.exists() or state.is_symlink():
            raise HostedError("State appeared during initialization; refusing to replace it.")
        stage.rename(state)
        sync_directory(data_root)
        return verify_state(state)
    except Exception:
        # Keep an interrupted stage for explicit operator inspection. Never silently retry it.
        raise


def validate_auth(data: bytes) -> None:
    try:
        text = data.decode("ascii")
    except UnicodeError:
        raise HostedError("Judge authentication file is invalid.") from None
    match = re.fullmatch(r"([A-Za-z0-9_-]{1,64}) (\$2[aby]\$(?:12|13|14|15|16)\$[./A-Za-z0-9]{53})\n?", text)
    if not match or match[1].casefold() == "import":
        raise HostedError("Judge authentication file must contain one approved bcrypt entry.")


def prepare_runtime(config: Configuration, secrets_root: Path, runtime_root: Path) -> tuple[Path, Path]:
    """Private copies satisfy existing owner/mode checks; never print mounted secrets."""
    runtime_root.mkdir(mode=0o700)
    private_directory(runtime_root)
    auth = regular_file(secrets_root / "judge-users", limit=256)
    validate_auth(auth)
    private_write(runtime_root / "judge-users", auth)
    if config.live:
        key = regular_file(secrets_root / "nebius-tokenfactory.key", limit=8192)
        try:
            raw = key.decode("ascii").strip("\r\n")
        except UnicodeError:
            raise HostedError("Mounted provider key has invalid format.") from None
        if not raw or any(ord(c) < 33 or ord(c) > 126 for c in raw):
            raise HostedError("Mounted provider key must contain one raw key.")
        private_write(runtime_root / "nebius-tokenfactory.key", key)
    site = runtime_root / "site"
    site.mkdir(mode=0o700)
    (site / "saved-evidence").mkdir(mode=0o700)
    landing = (APP_ROOT / "deployment/hosted/index.html").read_text()
    status = ("Live NVIDIA-on-Nebius inference is available within a shared cumulative cap. "
              "New live runs spend the operator's promotional credits."
              if config.live else
              "Live inference is disabled during deployment verification. "
              "You can run fixtures and inspect the saved real-model result without provider spending.")
    private_write(site / "index.html", landing.replace("__LIVE_STATUS__", status).encode())
    evidence = APP_ROOT / "docs/evidence"
    for extension in ("json", "md"):
        private_write(site / "saved-evidence" / f"live-diagnostic.{extension}",
                      (evidence / f"live-diagnostic-2026-10-29.{extension}").read_bytes())
    template = (APP_ROOT / "deployment/preview/Caddyfile.template").read_text()
    caddy = (template.replace("__EXPECTED_HOST__", config.host)
             .replace("__PUBLIC_ORIGIN__", config.origin)
             .replace("/run/secrets/judge-users", str(runtime_root / "judge-users"))
             .replace("/srv/preview", str(site)))
    private_write(runtime_root / "Caddyfile", caddy.encode())
    guard = (APP_ROOT / "deployment/preview/gateway-entrypoint.sh").read_text()
    guard = guard.replace("AUTH_FILE=/run/secrets/judge-users",
                          "AUTH_FILE=" + shlex.quote(str(runtime_root / "judge-users")))
    private_write(runtime_root / "gateway-entrypoint.sh", guard.encode())
    return runtime_root / "Caddyfile", runtime_root / "nebius-tokenfactory.key"


def backend_command(state: Path, config: Configuration, key: Path) -> list[str]:
    command = [sys.executable, "-B", "-m", "patchproof", "--database", str(state / "review.sqlite3"),
               "--port", "8770"]
    if config.live:
        command.extend(["--live-key-file", str(key), "--live-cap-usd", config.cap,
                        "--confirm-nebius-access", "--confirm-live-cap"])
    return command


def wait_backend(child, *, stopped, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if stopped() or child.poll() is not None:
            raise HostedError("Backend exited before the gateway could start.")
        try:
            with opener.open("http://127.0.0.1:8770/api/status", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise HostedError("Backend readiness timed out; gateway was not started.")


def stop_children(children, *, grace: float = 12) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + grace
    for child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
    for child in children:
        child.wait()


def supervise(command: list[str], caddyfile: Path, *, popen=subprocess.Popen, readiness=wait_backend) -> int:
    children = []
    stopping = False

    def stop_requested(_signum, _frame):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, stop_requested) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        children.append(popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        readiness(children[0], stopped=lambda: stopping)
        if stopping:
            return 0
        # Both commands have file paths and non-secret flags only. Child output is suppressed:
        # Caddy parse errors can echo an authentication line, and startup must not expose it.
        environment = {**os.environ, "PATCHPROOF_EXPECTED_UID": str(EXPECTED_UID),
                       "PATCHPROOF_EXPECTED_GID": str(EXPECTED_GID)}
        children.append(popen(["/bin/sh", str(caddyfile.parent / "gateway-entrypoint.sh"),
                               "run", "--config", str(caddyfile), "--adapter", "caddyfile"],
                              env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        print("PatchProof hosted gateway is running.", flush=True)
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise HostedError("A required hosted process exited; shutting down the service.")
            time.sleep(0.2)
        return 0
    finally:
        stop_children(children)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> int:
    os.umask(0o077)
    runtime_root = None
    try:
        if (os.getuid(), os.getgid()) != (EXPECTED_UID, EXPECTED_GID):
            raise HostedError("Hosted service requires the configured non-root UID and GID.")
        config = configuration(dict(os.environ))
        data = Path("/data")
        info = data.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise HostedError("The persistent /data mount must be a real directory.")
        with owner_lock(data / ".hosted.lock"):
            prepare_state(data, config, Path("/etc/secrets"))
            runtime_root = Path(tempfile.mkdtemp(prefix="patchproof-hosted-"))
            # prepare_runtime exclusively creates its private subdirectory.
            runtime_root = runtime_root / "runtime"
            caddyfile, key = prepare_runtime(config, Path("/etc/secrets"), runtime_root)
            return supervise(backend_command(data / "state", config, key), caddyfile)
    except HostedError as exc:
        # HostedError messages are fixed descriptions, without supplied values or credentials.
        print("PatchProof hosted stopped: " + str(exc), file=sys.stderr)
        return 1
    except OSError:
        print("PatchProof hosted filesystem or process setup failed. Check mount permissions.", file=sys.stderr)
        return 1
    finally:
        if runtime_root is not None:
            shutil.rmtree(runtime_root.parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
