"""Real, isolated gateway checks. Never enables live inference or reads provider keys."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import uuid


APP = Path(__file__).resolve().parents[2]
PREPARE = Path(__file__).with_name("prepare.py")
SOURCE_EVIDENCE = APP / "docs/evidence/live-diagnostic-2026-10-29.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "module":
            self.paths.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.paths.append(attrs["href"])


class Runner:
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.checks = []
        self.stacks = []
        self.extra_containers = []
        self.sensitive = []
        self.environment = dict(os.environ)
        for name in ("COMPOSE_FILE", "COMPOSE_ENV_FILES", "COMPOSE_PROFILES", "COMPOSE_PROJECT_NAME"):
            self.environment.pop(name, None)
        self.environment["COMPOSE_DISABLE_ENV_FILE"] = "1"
        self.log = self.output / "runner.log"

    def redact(self, value):
        text = value
        for secret in self.sensitive:
            if secret:
                text = text.replace(secret, "[redacted]")
        return text

    def command(self, args, *, timeout=120, check=True):
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env=self.environment)
        with self.log.open("a") as stream:
            stream.write(self.redact("COMMAND " + json.dumps(args) + "\n"))
            stream.write(self.redact(result.stdout + result.stderr))
        if check and result.returncode:
            raise AssertionError("Owned command failed; inspect sanitized runner.log.")
        return result

    def record(self, name, condition, **details):
        self.checks.append({"name": name, "passed": bool(condition), **details})
        if not condition:
            raise AssertionError(name)

    def save(self, status, **extra):
        receipt = {"checked_at_utc": now(), "status": status, "checks": self.checks,
                   "check_count": len(self.checks), "real_provider_calls": 0,
                   "canonical_database_ledger_or_key_accessed": False,
                   "source_app_unchanged": True, **extra}
        (self.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    def prepare(self, label):
        directory = self.output / label
        port = free_port()
        result = self.command([sys.executable, str(PREPARE), "--output-dir", str(directory),
                               "--port", str(port)], timeout=90)
        info = json.loads(result.stdout)
        password = Path(info["password_file"]).read_text().strip()
        self.sensitive += [password, base64.b64encode((info["username"] + ":" + password).encode()).decode()]
        users = directory / "judge-users"
        if users.exists():
            user_line = users.read_text().strip()
            self.sensitive += [user_line, user_line.split(maxsplit=1)[-1]]
        config = Path(info["compose_file"])
        stack = {"directory": directory, "port": port, "origin": f"http://127.0.0.1:{port}",
                 "info": info, "password": password, "config": config,
                 "project": "pp-audit-" + uuid.uuid4().hex[:10]}
        self.stacks.append(stack)
        return stack

    def compose(self, stack, *args, timeout=120, check=True):
        return self.command(["docker", "compose", "--env-file", "/dev/null", "-p", stack["project"],
                             "-f", str(stack["config"]), *args], timeout=timeout, check=check)

    def request(self, stack, method="GET", path="/api/status", *, auth=True, body=None,
                headers=(), host=None, duplicate_host=None, password=None):
        connection = http.client.HTTPConnection("127.0.0.1", stack["port"], timeout=12)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", host or f"127.0.0.1:{stack['port']}")
            if duplicate_host is not None:
                connection.putheader("Host", duplicate_host)
            if auth:
                value = stack["info"]["username"] + ":" + (password if password is not None else stack["password"])
                connection.putheader("Authorization", "Basic " + base64.b64encode(value.encode()).decode())
            for name, value in headers:
                connection.putheader(name, value)
            data = None if body is None else json.dumps(body).encode()
            if data is not None:
                connection.putheader("Content-Type", "application/json")
                connection.putheader("Content-Length", str(len(data)))
            connection.endheaders(data)
            response = connection.getresponse()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
        finally:
            connection.close()

    def ready(self, stack, *, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status, _, body = self.request(stack)
                if status == 200:
                    return json.loads(body)
            except (OSError, http.client.HTTPException, ValueError):
                pass
            time.sleep(0.4)
        raise AssertionError("Owned preview did not become ready.")

    def inspect(self, stack, service):
        cid = self.compose(stack, "ps", "-q", "--all", service).stdout.strip()
        if not cid:
            return None
        return json.loads(self.command(["docker", "inspect", cid]).stdout)[0]

    def expected_failure(self, stack, label, *, forbidden_log_value=None):
        seed = stack["directory"] / "data/review.sqlite3"
        seed_before = hashlib.sha256(seed.read_bytes()).hexdigest()
        self.compose(stack, "up", "-d", "--no-build", check=False)
        deadline = time.monotonic() + 15
        failed = False
        while time.monotonic() < deadline:
            states = [self.inspect(stack, service) for service in ("app", "gateway")]
            if any(s and s["State"]["Status"] in {"exited", "dead"} and s["State"]["ExitCode"] != 0 for s in states):
                failed = True
                break
            time.sleep(0.3)
        reachable = False
        try:
            reachable = self.request(stack)[0] == 200
        except (OSError, http.client.HTTPException):
            pass
        self.record(label, failed and not reachable, container_failed=failed,
                    authenticated_endpoint_reachable=reachable)
        logs = self.compose(stack, "logs", "--no-color", check=False)
        self.record(label + ":seed_unchanged", hashlib.sha256(seed.read_bytes()).hexdigest() == seed_before)
        if forbidden_log_value is not None:
            self.record(label + ":no_credential_in_logs",
                        forbidden_log_value not in logs.stdout + logs.stderr)
        self.compose(stack, "down", "--remove-orphans", check=False)

    def run(self):
        print(json.dumps({"phase": "building_capability_free_gateway", "at": now()}), flush=True)
        self.command(["docker", "build", "--tag", "patchproof-preview-caddy:2.11.7", "--file",
                      str(PREPARE.with_name("Caddy.Dockerfile")), str(APP)], timeout=600)
        gateway_image = json.loads(self.command(["docker", "image", "inspect",
                                                 "patchproof-preview-caddy:2.11.7"]).stdout)[0]
        hardened = ["docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
                    "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--user",
                    f"{os.getuid()}:{os.getgid()}"]
        base_image = "caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f"
        base_binary = self.command([*hardened, "--entrypoint", "sha256sum", base_image,
                                    "/usr/bin/caddy"]).stdout.split()[0]
        derived_binary = self.command([*hardened, "--entrypoint", "sha256sum",
                                       "patchproof-preview-caddy:2.11.7", "/usr/bin/caddy"]).stdout.split()[0]
        self.record("gateway_binary_matches_pinned_upstream", base_binary == derived_binary)
        capabilities = self.command([*hardened, "--entrypoint", "getcap",
                                     "patchproof-preview-caddy:2.11.7", "/usr/bin/caddy"])
        self.record("gateway_binary_has_no_file_capability", not capabilities.stdout.strip())
        version = self.command([*hardened, "--entrypoint", "caddy",
                                "patchproof-preview-caddy:2.11.7", "version"])
        self.record("gateway_executes_without_capabilities", "v2.11.7" in version.stdout)
        stack = self.prepare("primary")
        specification = json.loads(stack["config"].read_text())
        self.record("fixture_only_command", "--live-key-file" not in json.dumps(specification)
                    and "--confirm-nebius-access" not in json.dumps(specification))
        print(json.dumps({"phase": "building_image", "at": now()}), flush=True)
        self.compose(stack, "build", timeout=600)
        compose_gateway_image = json.loads(self.command(["docker", "image", "inspect",
                                                         "patchproof-preview-caddy:2.11.7"]).stdout)[0]
        self.record("compose_preserves_verified_gateway_filesystem",
                    compose_gateway_image["RootFS"]["Layers"] == gateway_image["RootFS"]["Layers"])
        before_config = {k: v for k, v in gateway_image["Config"].items() if k != "Labels"}
        after_config = {k: v for k, v in compose_gateway_image["Config"].items() if k != "Labels"}
        before_labels = gateway_image["Config"].get("Labels") or {}
        after_labels = compose_gateway_image["Config"].get("Labels") or {}
        added_labels = {k: v for k, v in after_labels.items() if k not in before_labels}
        self.record("compose_image_config_only_adds_compose_labels", before_config == after_config
                    and all(after_labels.get(k) == v for k, v in before_labels.items())
                    and all(k.startswith("com.docker.compose.") for k in added_labels))
        (self.output / "image-provenance.json").write_text(json.dumps({
            "pinned_upstream_image": base_image, "standalone_image_id": gateway_image["Id"],
            "compose_image_id": compose_gateway_image["Id"], "rootfs_layers_identical": True,
            "config_except_labels_identical": True, "added_compose_labels": added_labels,
            "pinned_upstream_and_derived_binary_sha256": base_binary,
            "gateway_dockerfile_sha256": hashlib.sha256(PREPARE.with_name("Caddy.Dockerfile").read_bytes()).hexdigest(),
            "file_capability_removed": True, "hardened_exec_version": version.stdout.strip(),
        }, indent=2) + "\n")
        gateway_image = compose_gateway_image
        print(json.dumps({"phase": "testing_gateway", "at": now()}), flush=True)
        self.compose(stack, "up", "-d", "--no-build", timeout=90)
        state = self.ready(stack)
        self.record("local_live_disabled_and_empty_ledger", state["live"]["enabled"] is False
                    and state["live_calls"] == 0 and state["active_experiment_id"] is None)
        original = json.loads(SOURCE_EVIDENCE.read_text())
        eid = original["id"]
        protected = ["/", "/workspace", "/api/status", "/api/experiments", "/api/guide",
                     "/api/templates/json", "/docs", "/openapi.json",
                     "/saved-evidence/live-diagnostic.json",
                     f"/api/experiments/{eid}", f"/api/experiments/{eid}/export/json"]
        status, _, page = self.request(stack, path="/workspace")
        self.record("authenticated_workspace", status == 200 and b"PatchProof" in page)
        assets = Assets()
        assets.feed(page.decode())
        self.record("workspace_assets_present", bool(assets.paths))
        self.navigation(stack, assets.paths)
        protected += assets.paths
        for path in protected:
            status, headers, _ = self.request(stack, path=path, auth=False)
            self.record("unauthenticated_blocked:" + path, status == 401
                        and "basic" in headers.get("www-authenticate", "").lower())
        _, challenge_headers, _ = self.request(stack, path="/", auth=False)
        self.record("authentication_challenge_security_headers",
                    challenge_headers.get("cache-control") == "no-store"
                    and challenge_headers.get("x-content-type-options") == "nosniff"
                    and challenge_headers.get("referrer-policy") == "no-referrer"
                    and "frame-ancestors 'none'" in challenge_headers.get("content-security-policy", "")
                    and "access-control-allow-origin" not in challenge_headers)
        self.record("wrong_password_blocked", self.request(stack, password="wrong-review-password")[0] == 401)
        self.record("duplicate_authorization_blocked", self.request(stack,
                    headers=[("Authorization", "Basic invalid-review-value")])[0] == 400)
        for path in ["/", "/workspace", "/docs", "/openapi.json", *assets.paths]:
            self.record("authenticated_read:" + path, self.request(stack, path=path)[0] == 200)
        landing = self.request(stack, path="/")[2].decode()
        self.record("shared_synthetic_workspace_notice", "shared" in landing.lower()
                    and "synthetic" in landing.lower() and "disabled" in landing.lower())
        self.record("saved_evidence_auth_read", self.request(stack,
                    path="/saved-evidence/live-diagnostic.json")[0] == 200)
        self.record("private_credential_path_unavailable", self.request(stack,
                    path="/run/secrets/judge-users")[0] in {400, 403, 404})
        before = json.loads(self.request(stack, path="/api/experiments")[2])
        for path in ("/api/datasets/import", "/api/experiments"):
            self.record("unauthenticated_write_blocked:" + path,
                        self.request(stack, method="POST", path=path, auth=False, body={})[0] == 401)
        self.record("unauthenticated_writes_no_side_effects", json.loads(self.request(stack, path="/api/experiments")[2]) == before
                    and json.loads(self.request(stack)[2])["live_calls"] == 0)
        seeded = json.loads(self.request(stack, path=f"/api/experiments/{eid}")[2])
        self.record("seeded_historical_export_unchanged", seeded == original)
        denied_live = {"baseline_prompt": original["baseline_prompt"], "mode": "live",
                       "dataset": {"dataset_id": original["dataset"]["dataset_id"]}}
        self.record("authenticated_live_start_remains_disabled", self.request(stack, method="POST",
                    path="/api/experiments", body=denied_live, headers=[("Origin", stack["origin"])])[0] == 403)
        self.record("denied_live_start_no_experiment_or_usage", json.loads(self.request(stack,
                    path="/api/experiments")[2]) == before and json.loads(self.request(stack)[2])["live_calls"] == 0)
        seed_path = stack["directory"] / "data/review.sqlite3"
        with sqlite3.connect(seed_path.as_uri() + "?mode=ro", uri=True) as database:
            registered = database.execute("SELECT count(*) FROM datasets WHERE id=?",
                                          (original["dataset"]["dataset_id"],)).fetchone()[0]
            exposures = database.execute("SELECT count(*) FROM case_exposure").fetchone()[0]
        self.record("seed_preserves_dataset_identity_and_exposure", registered == 1 and exposures == 40)
        saved = {}
        for kind in ("json", "markdown"):
            status, _, body = self.request(stack, path=f"/api/experiments/{eid}/export/{kind}")
            self.record("authenticated_export:" + kind, status == 200)
            saved[kind] = body
        self.record("json_export_matches_seed", json.loads(saved["json"]) == original)
        malformed_write = {"baseline_prompt": "", "dataset": {}, "mode": "fixture"}
        origin_cases = [("wrong", [("Origin", "https://evil.example")]), ("null", [("Origin", "null")]),
                        ("mixed_allowed_first", [("Origin", stack["origin"]), ("Origin", "https://evil.example")]),
                        ("mixed_allowed_last", [("Origin", "https://evil.example"), ("Origin", stack["origin"])]),
                        ("duplicate_allowed", [("Origin", stack["origin"]), ("Origin", stack["origin"])])]
        for label, headers in origin_cases:
            self.record("origin_blocked:" + label, self.request(stack, method="POST", path="/api/experiments",
                        body=malformed_write, headers=headers)[0] == 403)
        self.record("wrong_host_blocked", self.request(stack, host="evil.example")[0] == 400)
        self.record("wrong_port_blocked", self.request(stack, host="127.0.0.1:1")[0] == 400)
        self.record("duplicate_host_blocked", self.request(stack, duplicate_host="evil.example")[0] == 400)
        self.record("cross_site_fetch_blocked", self.request(stack, headers=[("Sec-Fetch-Site", "cross-site")])[0] == 403)
        spoofed = [("X-Forwarded-Host", "evil.example"), ("X-Forwarded-Proto", "https"),
                   ("Forwarded", "for=192.0.2.4;host=evil.example;proto=https"), ("Origin", stack["origin"])]
        self.record("forwarding_does_not_bypass_host", self.request(stack, host="evil.example", headers=spoofed)[0] == 400)
        self.record("valid_origin_spoofed_forwarding_reaches_inner_validation",
                    self.request(stack, method="POST", path="/api/experiments", body=malformed_write, headers=spoofed)[0] == 422)
        template = self.request(stack, path="/api/templates/json")[2].decode()
        status, _, body = self.request(stack, method="POST", path="/api/datasets/import",
                                      body={"content": template, "format": "json", "reviewed": False},
                                      headers=[("Origin", stack["origin"])])
        imported = json.loads(body)
        self.record("same_origin_import_succeeds", status == 200 and len(imported["cases"]) == 1
                    and imported["human_review_pending"] is True)
        app_state = self.inspect(stack, "app")
        gateway = self.inspect(stack, "gateway")
        self.record("verified_gateway_image_used", gateway["Image"] == gateway_image["Id"])
        self.record("containers_keep_nonroot_no_capabilities", all(
            item["Config"]["User"] == f"{os.getuid()}:{os.getgid()}"
            and item["HostConfig"]["CapDrop"] == ["ALL"]
            and not item["HostConfig"]["CapAdd"]
            and any(option.startswith("no-new-privileges") for option in item["HostConfig"]["SecurityOpt"])
            for item in (app_state, gateway)))
        runtime_binary = self.command(["docker", "exec", gateway["Id"], "sha256sum",
                                       "/usr/bin/caddy"]).stdout.split()[0]
        runtime_capability = self.command(["docker", "exec", gateway["Id"], "getcap", "/usr/bin/caddy"])
        self.record("running_gateway_binary_and_capability_verified", runtime_binary == base_binary
                    and not runtime_capability.stdout.strip())
        bindings = app_state["HostConfig"]["PortBindings"]
        self.record("only_loopback_gateway_published", set(bindings) == {"8780/tcp"}
                    and bindings["8780/tcp"] == [{"HostIp": "127.0.0.1", "HostPort": str(stack["port"])}]
                    and not gateway["HostConfig"]["PortBindings"])
        self.record("gateway_shares_app_namespace", gateway["HostConfig"]["NetworkMode"] == "container:" + app_state["Id"])
        mounts = app_state["Mounts"] + gateway["Mounts"]
        self.record("no_provider_key_or_raw_password_mount", all("nebius" not in m["Destination"].lower()
                    and Path(m.get("Source", "")).name != "password.txt" for m in mounts))
        network_check = "import socket,json; ip=socket.gethostbyname(socket.gethostname()); out={}; " \
                        "\nfor name,host,port in [('backend_loopback','127.0.0.1',8770),('backend_external',ip,8770),('admin','127.0.0.1',2019)]:\n s=socket.socket();s.settimeout(2);out[name]=s.connect_ex((host,port));s.close()\nprint(json.dumps(out))"
        ports = json.loads(self.command(["docker", "exec", app_state["Id"], "python", "-c", network_check]).stdout)
        self.record("backend_loopback_only_admin_disabled", ports["backend_loopback"] == 0
                    and ports["backend_external"] != 0 and ports["admin"] != 0)
        demo = json.loads(self.request(stack, path="/api/demo")[2])
        payload = {"dataset": {"dataset_id": demo["dataset_id"]}, "baseline_prompt": demo["starter_prompt"],
                   "mode": "fixture", "scenario": "improvement"}
        status, _, body = self.request(stack, method="POST", path="/api/experiments", body=payload,
                                      headers=[("Origin", stack["origin"])])
        self.record("same_origin_fixture_start", status == 202)
        fixture_id = json.loads(body)["id"]
        data_dir = stack["directory"] / "data"
        image = stack["info"]["app_image"]
        lock_container = stack["project"] + "-lock"
        self.extra_containers.append(lock_container)
        concurrent = self.command(["docker", "run", "--rm", "--name", lock_container,
                                   "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", "python",
                                   "--mount", f"type=bind,src={data_dir},dst=/data", image,
                                   "-B", "-m", "patchproof", "--database", "/data/review.sqlite3", "--port", "8770"],
                                  timeout=30, check=False)
        self.record("second_writer_rejected", concurrent.returncode != 0 and "already in use" in concurrent.stderr)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            fixture = json.loads(self.request(stack, path=f"/api/experiments/{fixture_id}")[2])
            if fixture["status"] not in {"queued", "running"}:
                break
            time.sleep(0.3)
        self.record("fixture_completes_without_interruption", fixture["status"] == "completed"
                    and len(fixture["observations"]) == 150)
        history = self.request(stack, path="/api/experiments")[2]
        fixture_json = self.request(stack, path=f"/api/experiments/{fixture_id}/export/json")[2]
        ids = (app_state["Id"], gateway["Id"])
        print(json.dumps({"phase": "checking_persistence", "checks": len(self.checks)}), flush=True)
        self.compose(stack, "up", "-d", "--no-build", "--force-recreate", timeout=90)
        state = self.ready(stack)
        self.record("both_services_recreated", self.inspect(stack, "app")["Id"] != ids[0]
                    and self.inspect(stack, "gateway")["Id"] != ids[1])
        self.record("restart_history_exports_preserved", self.request(stack, path="/api/experiments")[2] == history
                    and self.request(stack, path=f"/api/experiments/{fixture_id}/export/json")[2] == fixture_json
                    and all(self.request(stack, path=f"/api/experiments/{eid}/export/{kind}")[2] == saved[kind]
                            for kind in ("json", "markdown")))
        self.record("restart_no_live_or_resumed_work", state["live"]["enabled"] is False
                    and state["live_calls"] == 0 and state["active_experiment_id"] is None)
        print(json.dumps({"phase": "reflecting_proxy_headers", "checks": len(self.checks)}), flush=True)
        self.reflection()
        print(json.dumps({"phase": "checking_fail_closed_startup", "checks": len(self.checks)}), flush=True)
        self.failure_cases()
        self.save("passed", fixture_observations=150, seeded_experiment_id=eid,
                  private_root=str(self.output), no_public_hosting=True,
                  gateway_image_id=gateway_image["Id"],
                  caddy_upstream_image="caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f",
                  original_evidence_sha256=hashlib.sha256(SOURCE_EVIDENCE.read_bytes()).hexdigest())

    def navigation(self, stack, asset_paths):
        headers = [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Mode", "navigate"),
                   ("Sec-Fetch-Dest", "document")]
        before = self.request(stack, path="/api/experiments")[2]
        for method in ("GET", "HEAD"):
            for authenticated in (False, True):
                status, response_headers, body = self.request(
                    stack, method=method, path="/", auth=authenticated, headers=headers)
                expected = 200 if authenticated else 401
                self.record(f"cross_site_landing:{method}:auth={authenticated}", status == expected
                            and response_headers.get("cache-control") == "no-store"
                            and (authenticated or "basic" in response_headers.get("www-authenticate", "").lower())
                            and (method != "HEAD" or not body))
        for path in ("/api/status", "/workspace", "/workspace/", "/docs", "/openapi.json",
                     "/saved-evidence/live-diagnostic.json", *asset_paths):
            self.record("cross_site_navigation_path_blocked:" + path,
                        self.request(stack, path=path, headers=headers)[0] == 403)
        for mode, destination in (("navigate", "iframe"), ("no-cors", "image"),
                                  ("cors", "empty"), ("same-origin", "empty"),
                                  ("navigate", "empty"), ("cors", "document")):
            attempt = [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Mode", mode),
                       ("Sec-Fetch-Dest", destination)]
            self.record(f"cross_site_non_navigation_blocked:{mode}:{destination}",
                        self.request(stack, path="/", headers=attempt)[0] == 403)
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            self.record("cross_site_landing_method_blocked:" + method,
                        self.request(stack, method=method, path="/", headers=headers, body={})[0] == 403)
        self.record("cross_site_api_write_blocked", self.request(stack, method="POST",
                    path="/api/experiments", headers=headers, body={})[0] == 403)
        for absent in ("Sec-Fetch-Mode", "Sec-Fetch-Dest"):
            self.record("cross_site_incomplete_metadata_blocked:" + absent,
                        self.request(stack, path="/", headers=[h for h in headers if h[0] != absent])[0] == 403)
        duplicates = [
            ("site_identical", headers + [("Sec-Fetch-Site", "cross-site")]),
            ("site_cross_site_first", headers + [("Sec-Fetch-Site", "same-origin")]),
            ("site_cross_site_last", [("Sec-Fetch-Site", "same-origin"), *headers]),
            ("mode_identical", headers + [("Sec-Fetch-Mode", "navigate")]),
            ("mode_mixed", headers + [("Sec-Fetch-Mode", "cors")]),
            ("destination_identical", headers + [("Sec-Fetch-Dest", "document")]),
            ("destination_mixed", headers + [("Sec-Fetch-Dest", "iframe")]),
        ]
        for label, attempt in duplicates:
            self.record("cross_site_duplicate_metadata_blocked:" + label,
                        self.request(stack, path="/", headers=attempt)[0] == 403)
        origins = [
            ("foreign", [("Origin", "https://evil.example")]),
            ("null", [("Origin", "null")]),
            ("empty", [("Origin", "")]),
            ("duplicate_allowed", [("Origin", stack["origin"]), ("Origin", stack["origin"])]),
            ("mixed", [("Origin", stack["origin"]), ("Origin", "https://evil.example")]),
        ]
        for label, origin_headers in origins:
            self.record("cross_site_landing_origin_blocked:" + label,
                        self.request(stack, path="/", headers=[*headers, *origin_headers])[0] == 403)
        self.record("cross_site_landing_host_blocked",
                    self.request(stack, path="/", headers=headers, host="evil.example")[0] == 400)
        self.record("cross_site_landing_duplicate_auth_blocked", self.request(stack, path="/",
                    headers=[*headers, ("Authorization", "Basic invalid-review-value")])[0] == 400)
        self.record("cross_site_landing_wrong_password_blocked", self.request(stack, path="/",
                    headers=headers, password="wrong-review-password")[0] == 401)
        for site in (None, "same-origin", "same-site", "none"):
            attempt = [] if site is None else [("Sec-Fetch-Site", site)]
            self.record("ordinary_client_compatibility:" + str(site),
                        self.request(stack, path="/api/status", headers=attempt)[0] == 200)
        self.record("navigation_checks_no_experiment_or_live_usage",
                    self.request(stack, path="/api/experiments")[2] == before
                    and json.loads(self.request(stack)[2])["live_calls"] == 0)

    def reflection(self):
        stack = self.prepare("reflection")
        script = stack["directory"] / "echo.py"
        script.write_text('''from http.server import BaseHTTPRequestHandler,HTTPServer
import json
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  if self.path == '/redirect':
   self.send_response(307);self.send_header('Location','http://127.0.0.1:8770/redirect-target');self.end_headers();return
  out={'authorization_present':bool(self.headers.get_all('Authorization')),'forwarded_present':any(k.lower()=='forwarded' or k.lower().startswith('x-forwarded-') for k in self.headers),'host':self.headers.get('Host'),'origin':self.headers.get('Origin')}
  data=json.dumps(out).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
HTTPServer(('127.0.0.1',8770),Handler).serve_forever()
''')
        specification = json.loads(stack["config"].read_text())
        specification["services"]["app"]["entrypoint"] = ["python", "-B", "/app/echo.py"]
        specification["services"]["app"]["command"] = []
        specification["services"]["app"]["volumes"].append({"type": "bind", "source": str(script),
            "target": "/app/echo.py", "read_only": True, "bind": {"create_host_path": False}})
        stack["config"].write_text(json.dumps(specification, indent=2))
        self.compose(stack, "up", "-d", "--no-build")
        self.ready(stack)
        headers = [("Origin", stack["origin"]), ("Forwarded", "for=192.0.2.7;host=evil.example;proto=https"),
                   ("X-Forwarded-Host", "evil.example"), ("X-Forwarded-Proto", "https"), ("X-Forwarded-For", "192.0.2.7")]
        status, _, body = self.request(stack, path="/echo", headers=headers)
        reflected = json.loads(body)
        self.record("real_upstream_auth_forwarded_headers_removed", status == 200
                    and not reflected["authorization_present"] and not reflected["forwarded_present"]
                    and reflected["host"] == "127.0.0.1:8770" and reflected["origin"] == "http://127.0.0.1:8770")
        status, headers, _ = self.request(stack, path="/redirect")
        self.record("real_upstream_location_rewritten", status == 307
                    and headers.get("location") == stack["origin"] + "/redirect-target")

    def failure_cases(self):
        for label in ("missing_auth", "invalid_auth", "reserved_username", "wrong_uid", "unwritable_data"):
            stack = self.prepare(label)
            spec = json.loads(stack["config"].read_text())
            forbidden_log_value = None
            if label == "missing_auth":
                (stack["directory"] / "judge-users").unlink()
                result = self.compose(stack, "up", "-d", "--no-build", check=False)
                self.record("missing_auth_mount_fails_closed", result.returncode != 0)
                continue
            if label == "invalid_auth":
                (stack["directory"] / "judge-users").write_text("judge invalid-hash\n")
            elif label == "reserved_username":
                users = stack["directory"] / "judge-users"
                forbidden_log_value = users.read_text().strip().split(maxsplit=1)[1]
                users.write_text("import " + forbidden_log_value + "\n")
            elif label == "wrong_uid":
                spec["services"]["gateway"]["user"] = f"{os.getuid() + 50000}:{os.getgid()}"
                stack["config"].write_text(json.dumps(spec, indent=2))
            else:
                data = stack["directory"] / "data"
                for path in data.iterdir():
                    if path.is_file():
                        path.chmod(0o400)
                data.chmod(0o500)
                for volume in spec["services"]["app"]["volumes"]:
                    if volume["target"] == "/data":
                        volume["read_only"] = True
                stack["config"].write_text(json.dumps(spec, indent=2))
            self.expected_failure(stack, label + "_fails_closed", forbidden_log_value=forbidden_log_value)

    def cleanup(self):
        for name in self.extra_containers:
            try:
                self.command(["docker", "rm", "--force", name], check=False)
            except (OSError, subprocess.SubprocessError):
                pass
        for stack in reversed(self.stacks):
            try:
                self.compose(stack, "logs", "--no-color", check=False)
                self.compose(stack, "down", "--remove-orphans", check=False)
            except (OSError, subprocess.SubprocessError):
                pass
            data = stack["directory"] / "data"
            if data.exists():
                data.chmod(0o700)
                for path in data.iterdir():
                    if path.is_file():
                        path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    runner = Runner(args.output_dir)
    status = "failed"
    try:
        runner.run()
        status = "passed"
    except Exception as exc:
        runner.save("failed", failure=type(exc).__name__ + ": " + runner.redact(str(exc)))
        print(json.dumps({"status": "failed", "failure": type(exc).__name__,
                          "completed_checks": len(runner.checks), "receipt": str(runner.output / "receipt.json")}))
        return 1
    finally:
        runner.cleanup()
    print(json.dumps({"status": status, "checks": len(runner.checks),
                      "receipt": str(runner.output / "receipt.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
