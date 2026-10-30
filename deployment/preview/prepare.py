"""Prepare a private, fixture-only local judge preview. No server starts here."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
from urllib.parse import urlsplit


APP_DIR = Path(__file__).resolve().parents[2]
PREVIEW_DIR = Path(__file__).resolve().parent
CADDY_BASE_IMAGE = (
    "caddy:2.11.7-alpine@sha256:"
    "eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f"
)
CADDY_IMAGE = "patchproof-preview-caddy:2.11.7"
APP_IMAGE = "patchproof-judge-preview:local"
BUNDLED_EVIDENCE = APP_DIR / "docs/evidence/live-diagnostic-2026-10-29.json"
EVIDENCE_SHA256 = "62c3a207e069f516b2a0e84786c426a0a0471ad7e82790fd756cde7f1b3aaad6"


class PreviewError(ValueError):
    pass


def validate_origin(origin: str | None, port: int) -> tuple[str, str]:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise PreviewError("Local review port must be between 1024 and 65535.")
    origin = origin or f"http://127.0.0.1:{port}"
    if not isinstance(origin, str) or not origin.isascii() or any(c.isspace() for c in origin):
        raise PreviewError("Origin must be one ASCII HTTP(S) origin without whitespace.")
    try:
        value = urlsplit(origin)
        hostname, origin_port = value.hostname, value.port
    except ValueError:
        raise PreviewError("Origin has an invalid hostname or port.") from None
    if (
        value.scheme not in {"http", "https"}
        or not hostname
        or value.username is not None
        or value.password is not None
        or value.path not in {"", "/"}
        or value.query
        or value.fragment
        or not re.fullmatch(r"[A-Za-z0-9.:[\]-]+", value.netloc)
        or hostname.endswith(".")
    ):
        raise PreviewError("Origin must contain only a scheme, hostname and optional port.")
    loopback = hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname):
            raise PreviewError("Origin hostname is invalid.") from None
    if value.scheme == "http" and (
        not loopback or hostname not in {"127.0.0.1", "localhost"} or origin_port != port
    ):
        raise PreviewError("HTTP review origins must be loopback and match the published port.")
    if origin_port == 0:
        raise PreviewError("Origin port must be positive.")
    host = f"[{hostname}]" if ":" in hostname else hostname
    default = 80 if value.scheme == "http" else 443
    if origin_port is not None and origin_port != default:
        host += f":{origin_port}"
    return f"{value.scheme}://{host}", host


def private_write(path: Path, content: bytes | str) -> None:
    data = content.encode("utf-8") if isinstance(content, str) else content
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def hash_password(password: str) -> str:
    """Use the pinned Caddy helper with stdin; never a password argument or log."""
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm", "--pull=never", "--network=none",
                "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                "--user", f"{os.getuid()}:{os.getgid()}", "-i", "--entrypoint", "caddy",
                CADDY_IMAGE, "hash-password",
            ],
            input=password + "\n", text=True, capture_output=True, timeout=90, check=True,
        )
    except Exception:
        raise PreviewError(
            "Private Caddy password helper failed. Build its pinned derived image first."
        ) from None
    return result.stdout.strip()


def load_seed() -> tuple[dict, bytes]:
    raw = BUNDLED_EVIDENCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EVIDENCE_SHA256:
        raise PreviewError("The bundled historical evidence hash does not match.")
    evidence = json.loads(raw)
    if (
        evidence.get("status") != "completed"
        or evidence.get("execution_kind") != "Live inference"
        or evidence.get("verdict") != "rejected"
        or evidence.get("prior_exposure") is not False
        or len(evidence.get("dataset", {}).get("cases", [])) != 40
    ):
        raise PreviewError("The bundled historical evidence is not the expected completed run.")
    return evidence, raw


def seed_database(path: Path, evidence: dict) -> None:
    """Seed historical display and exposure; never read the canonical runtime."""
    sys.path.insert(0, str(APP_DIR / "backend"))
    from patchproof.store import Store

    store = Store(path)
    original = deepcopy(evidence)
    dataset = original["dataset"]
    with store.connect() as db:
        db.execute(
            "INSERT INTO datasets VALUES (?,?)",
            (dataset["dataset_id"], json.dumps(dataset, ensure_ascii=False, allow_nan=False)),
        )
    store.create_experiment(original)
    if store.get(original["id"]) != evidence:
        raise PreviewError("Historical seed did not preserve the exact saved result.")
    path.chmod(0o600)


def bind(source: Path, target: str, *, readonly: bool = True) -> dict:
    return {
        "type": "bind", "source": str(source), "target": target,
        "read_only": readonly, "bind": {"create_host_path": False},
    }


def compose_config(output: Path, port: int, project_name: str) -> dict:
    uid, gid = os.getuid(), os.getgid()
    security = {
        "user": f"{uid}:{gid}", "init": True, "read_only": True,
        "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
        "pids_limit": 128, "restart": "no",
    }
    return {
        "name": project_name,
        "services": {
            "app": {
                **security, "image": APP_IMAGE,
                "build": {"context": str(APP_DIR), "dockerfile": "deployment/preview/Dockerfile"},
                "command": [
                    "python", "-B", "-m", "patchproof", "--database", "/data/review.sqlite3",
                    "--port", "8770",
                ],
                "ports": [{"target": 8780, "published": str(port), "host_ip": "127.0.0.1"}],
                "volumes": [bind(output / "data", "/data", readonly=False)],
                "tmpfs": ["/tmp:rw,noexec,nosuid,size=32m,mode=1777"],
                "mem_limit": "512m", "cpus": 1.0,
                "healthcheck": {
                    "test": [
                        "CMD", "python", "-c",
                        "import urllib.request; "
                        "urllib.request.build_opener(urllib.request.ProxyHandler({})).open("
                        "'http://127.0.0.1:8770/api/status', timeout=2).read()",
                    ],
                    "interval": "2s", "timeout": "3s", "retries": 30, "start_period": "10s",
                },
            },
            "gateway": {
                **security, "image": CADDY_IMAGE, "pull_policy": "never",
                "build": {"context": str(APP_DIR), "dockerfile": "deployment/preview/Caddy.Dockerfile"},
                "network_mode": "service:app", "depends_on": {"app": {"condition": "service_healthy"}},
                "entrypoint": ["/usr/local/bin/patchproof-gateway"],
                "environment": {
                    "PATCHPROOF_EXPECTED_UID": str(uid),
                    "PATCHPROOF_EXPECTED_GID": str(gid),
                },
                "command": ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
                "volumes": [
                    bind(output / "Caddyfile", "/etc/caddy/Caddyfile"),
                    bind(output / "judge-users", "/run/secrets/judge-users"),
                    bind(output / "site", "/srv/preview"),
                ],
                "tmpfs": [
                    "/tmp:rw,noexec,nosuid,size=16m,mode=1777",
                    f"/data:rw,noexec,nosuid,size=16m,mode=0700,uid={uid},gid={gid}",
                    f"/config:rw,noexec,nosuid,size=4m,mode=0700,uid={uid},gid={gid}",
                ],
                "mem_limit": "256m", "cpus": 1.0,
            },
        },
    }


def prepare(
    output_dir: Path, *, port: int = 8780, origin: str | None = None, username: str = "judge",
    hasher=None, password_factory=None,
) -> dict:
    origin, host = validate_origin(origin, port)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", username) or username.casefold() == "import":
        raise PreviewError(
            "Username must use 1–64 ASCII letters, digits, underscores or hyphens, "
            "and must not be the reserved word import."
        )
    if os.getuid() == 0:
        raise PreviewError("Prepare the review as a non-root user to match private file ownership.")
    output_dir = Path(output_dir)
    if not output_dir.is_absolute() or output_dir.is_symlink():
        raise PreviewError("Output must be a new absolute private directory.")
    output = output_dir.resolve()
    if output == APP_DIR or APP_DIR in output.parents:
        raise PreviewError("Private review output must stay outside the application/source directory.")
    if output.exists():
        raise PreviewError("Output already exists. Do not overwrite review data or credentials.")
    if not output.parent.is_dir():
        raise PreviewError("The output parent directory must already exist.")
    evidence, raw_evidence = load_seed()
    password = (password_factory or (lambda: secrets.token_urlsafe(32)))()
    if not isinstance(password, str) or not 32 <= len(password) <= 256 or not password.isascii():
        raise PreviewError("Generated review password must be 32–256 ASCII characters.")
    if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in password):
        raise PreviewError("Generated review password has an invalid character.")
    try:
        hashed = (hasher or hash_password)(password)
    except PreviewError:
        raise
    except Exception:
        raise PreviewError("Password hashing failed; no credentials were printed.") from None
    if not isinstance(hashed, str) or not re.fullmatch(r"\$2[aby]\$(?:12|13|14|15|16)\$[./A-Za-z0-9]{53}", hashed):
        raise PreviewError("Password helper must return one bcrypt hash with cost 12–16.")
    output.mkdir(mode=0o700)
    info = output.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PreviewError("Private output must be owned by this user with mode 700.")
    for name in ("data", "site", "site/saved-evidence"):
        (output / name).mkdir(mode=0o700)
    private_write(output / "password.txt", password + "\n")
    private_write(output / "judge-users", f"{username} {hashed}\n")
    config = (PREVIEW_DIR / "Caddyfile.template").read_text()
    config = config.replace("__EXPECTED_HOST__", host).replace("__PUBLIC_ORIGIN__", origin)
    private_write(output / "Caddyfile", config)
    private_write(output / "site/index.html", (PREVIEW_DIR / "index.html").read_bytes())
    private_write(output / "site/saved-evidence/live-diagnostic.json", raw_evidence)
    report = APP_DIR / "docs/evidence/live-diagnostic-2026-10-29.md"
    private_write(output / "site/saved-evidence/live-diagnostic.md", report.read_bytes())
    seed_database(output / "data/review.sqlite3", evidence)
    project = "patchproof-review-" + hashlib.sha256(str(output).encode()).hexdigest()[:12]
    compose = compose_config(output, port, project)
    private_write(output / "compose.json", json.dumps(compose, indent=2) + "\n")
    result = {
        "url": origin, "username": username, "password_file": str(output / "password.txt"),
        "compose_file": str(output / "compose.json"), "output_dir": str(output),
        "project_name": project, "seeded_experiment_id": evidence["id"],
        "fixture_only": True, "app_image": APP_IMAGE, "caddy_image": CADDY_IMAGE,
        "caddy_base_image": CADDY_BASE_IMAGE,
        "published_host_binding": f"127.0.0.1:{port}",
        "promotion_warning": "Review data is disposable. Do not use it as a funded live ledger.",
    }
    private_write(output / "prepared.json", json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--origin")
    parser.add_argument("--username", default="judge")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.output_dir, port=args.port, origin=args.origin, username=args.username)
    except PreviewError as exc:
        parser.exit(2, f"Preview preparation stopped: {exc}\n")
    except (OSError, ValueError):
        parser.exit(2, "Preview preparation stopped: unable to create the private review package.\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
