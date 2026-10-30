"""Disposable Docker/HTTP checks with public saved evidence and synthetic accounting.

Never reads private operator credentials or canonical runtime databases.
"""
from __future__ import annotations

import argparse
import base64
from decimal import Decimal
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import tempfile
import time

from create_seed import create_seed
from runtime import APP_ROOT


def command(*args, input=None, check=True, timeout=90):
    result = subprocess.run(args, input=input, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"Test command failed: {args[0]} {args[1]}; {result.stderr[:300]}")
    return result


def run(image: str, output: Path) -> dict:
    suffix = secrets.token_hex(5)
    prefix = "patchproof-hosted-test-" + suffix
    network, volume, secret_volume = prefix + "-net", prefix + "-state", prefix + "-secrets"
    containers, volumes, checks = [], [], []
    current = None
    password = "synthetic-local-test-" + secrets.token_urlsafe(24)
    basic = "Basic " + base64.b64encode(("judge:" + password).encode()).decode()

    def record(name, valid):
        if not valid:
            raise AssertionError(name)
        checks.append(name)

    def helper(script, *, chosen_volume=volume, payload=None):
        return command("docker", "run", "--rm", "-i", "--network=none", "--user=0:0",
                       "--mount", f"type=volume,source={chosen_volume},target=/data",
                       "--mount", f"type=volume,source={secret_volume},target=/etc/secrets",
                       "--entrypoint", "python", image, "-c", script, input=payload).stdout

    def stop():
        nonlocal current
        if current:
            command("docker", "stop", "--time", "15", current)
            current = None

    def start(*, bootstrap=False, seed_sha=None, chosen_volume=volume, extra=(), isolated=False):
        nonlocal current
        name = prefix + "-" + str(len(containers))
        args = ["docker", "run", "-d", "--name", name, "--network", "none" if isolated else network,
                "--cap-drop=ALL", "--security-opt=no-new-privileges:true", "--read-only",
                "--pids-limit=128", "--memory=512m", "--cpus=0.5",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=128m,mode=1777",
                "--mount", f"type=volume,source={chosen_volume},target=/data",
                "--mount", f"type=volume,source={secret_volume},target=/etc/secrets,readonly",
                "-e", "RENDER_EXTERNAL_URL=https://judge.example.test",
                "-e", "PATCHPROOF_BOOTSTRAP=" + ("1" if bootstrap else "0")]
        if not isolated:
            args += ["-p", "127.0.0.1::8780"]
        if seed_sha:
            args += ["-e", "PATCHPROOF_SEED_SHA256=" + seed_sha]
        args += list(extra) + [image]
        command(*args)
        containers.append(name)
        current = name
        return name

    def ready():
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = json.loads(command("docker", "inspect", current, "--format", "{{json .State}}").stdout)
            if not state["Running"]:
                logs = command("docker", "logs", current).stdout
                raise AssertionError("Container failed before readiness: " + logs[:300])
            port = command("docker", "port", current, "8780/tcp", check=False).stdout.strip()
            if port:
                try:
                    value = int(port.rsplit(":", 1)[1])
                    status, _, _ = request(value, "/", authorized=False)
                    if status == 401:
                        return value
                except OSError:
                    pass
            time.sleep(0.2)
        raise AssertionError("Hosted listener readiness timed out")

    def request(port, path, *, authorized=True, method="GET", headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        values = {"Host": "judge.example.test"}
        if authorized:
            values["Authorization"] = basic
        values.update(headers or {})
        connection.request(method, path, body=body, headers=values)
        response = connection.getresponse()
        status, response_headers, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, data

    def exit_code():
        value = command("docker", "wait", current, timeout=30).stdout.strip()
        return int(value)

    try:
        command("docker", "network", "create", network)
        for item in (volume, secret_volume):
            command("docker", "volume", "create", item)
            volumes.append(item)
        with tempfile.TemporaryDirectory(prefix="patchproof-hosted-fixture-") as temporary:
            root = Path(temporary)
            preview_spec = importlib.util.spec_from_file_location("preview_seed", APP_ROOT / "deployment/preview/prepare.py")
            preview = importlib.util.module_from_spec(preview_spec)
            preview_spec.loader.exec_module(preview)
            source = root / "review.sqlite3"
            evidence, _ = preview.load_seed()
            preview.seed_database(source, evidence)
            source.with_name(source.name + ".lock").touch(mode=0o600)
            ledger = root / "provider-usage.sqlite3"
            with sqlite3.connect(ledger) as db:
                db.executescript("""
                    CREATE TABLE usage (id TEXT PRIMARY KEY, reserved INTEGER NOT NULL, charged INTEGER, state TEXT NOT NULL);
                    INSERT INTO usage VALUES ('synthetic-accounted',100,60,'accounted');
                    INSERT INTO usage VALUES ('synthetic-unknown',200,NULL,'usage_unknown');
                """)
            ledger.chmod(0o600)
            receipt = create_seed(source, root / "patchproof-state.b64", source_stopped=True)
            hashed = command("docker", "run", "--rm", "--network=none", "-i", "--entrypoint", "caddy",
                             image, "hash-password", input=password + "\n").stdout.strip()
            files = {"patchproof-state.b64": (root / "patchproof-state.b64").read_text(),
                     "judge-users": "judge " + hashed + "\n"}
            helper("""import json,os,sys
from pathlib import Path
os.chown('/data',10001,1000);os.chmod('/data',0o700)
os.chown('/etc/secrets',0,1000);os.chmod('/etc/secrets',0o750)
for name,content in json.load(sys.stdin).items():
 p=Path('/etc/secrets')/name;p.write_text(content);os.chown(p,0,1000);p.chmod(0o640)
""", payload=json.dumps(files))
            start(bootstrap=True, seed_sha=receipt["seed_sha256"])
            port = ready()
            record("bootstrap starts without a provider key", True)
            uid = command("docker", "exec", current, "python", "-c", "import os;print(os.getuid(),os.getgid())").stdout.strip()
            record("non-root UID 10001 and GID 1000", uid == "10001 1000")
            record("unauthenticated landing is gated", request(port, "/", authorized=False)[0] == 401)
            record("unauthenticated API is gated", request(port, "/api/status", authorized=False)[0] == 401)
            status, headers, body = request(port, "/")
            record("authenticated landing accurately says live disabled", status == 200 and b"Live inference is disabled" in body)
            record("historical result is identified without a timezone assumption",
                   b"ba2420e6-2691-47a2-b993-18c35e1c1955" in body
                   and b"browser's local timezone" in body and b"29 October at 01:38" not in body)
            record("security response headers are retained", headers.get("X-Frame-Options") == "DENY" and "no-store" in headers.get("Cache-Control", ""))
            record("authenticated workspace serves", request(port, "/workspace")[0] == 200)
            status, _, body = request(port, "/api/status")
            api = json.loads(body)
            record("original synthetic ledger count survives bootstrap", status == 200 and api["live_calls"] == 2 and api["live"]["enabled"] is False)
            record("wrong host blocked before rewrite", request(port, "/api/status", headers={"Host": "evil.example.test"})[0] == 400)
            record("cross-origin API blocked", request(port, "/api/status", headers={"Origin": "https://evil.example.test"})[0] == 403)
            record("cross-site API blocked", request(port, "/api/status", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403)
            record("safe cross-site landing navigation allowed", request(port, "/", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})[0] == 200)
            record("cross-site writes blocked", request(port, "/api/experiments", method="POST", headers={"Sec-Fetch-Site": "cross-site"}, body=b"{}")[0] == 403)
            record("ambiguous authorization blocked", request(port, "/", headers={"Authorization": basic + ", " + basic})[0] == 400)
            record("spoofed forwarding metadata does not change host routing", request(port, "/api/status", headers={"X-Forwarded-Host": "evil.example.test", "X-Forwarded-Proto": "http", "Forwarded": "host=evil.example.test;proto=http"})[0] == 200)
            status, _, body = request(port, "/saved-evidence/live-diagnostic.json")
            record("saved evidence preserves exact public export", status == 200 and hashlib.sha256(body).hexdigest() == preview.EVIDENCE_SHA256)
            record("secret path is not served", request(port, "/saved-evidence/../judge-users")[0] != 200)
            _, _, body = request(port, "/api/demo")
            dataset = json.loads(body)
            content = json.dumps({"baseline_prompt": dataset["starter_prompt"], "dataset": {"dataset_id": dataset["dataset_id"]}, "mode": "live", "scenario": "improvement"}).encode()
            record("live API refuses before any provider call", request(port, "/api/experiments", method="POST", headers={"Content-Type": "application/json"}, body=content)[0] == 403)
            payload = json.loads(content)
            payload["mode"] = "fixture"
            status, _, body = request(port, "/api/experiments", method="POST", headers={"Content-Type": "application/json"}, body=json.dumps(payload).encode())
            record("fixture run accepted", status == 202)
            run_id = json.loads(body)["id"]
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                _, _, body = request(port, "/api/experiments/" + run_id)
                experiment = json.loads(body)
                if experiment["status"] not in ("queued", "running"):
                    break
                time.sleep(0.2)
            record("fixture completes with saved observations", experiment["status"] == "completed" and len(experiment["observations"]) == 150)
            record("fixture leaves cumulative model usage unchanged", json.loads(request(port, "/api/status")[2])["live_calls"] == 2)
            stop()
            grown = json.loads(helper("""import json,sqlite3
from pathlib import Path
p=Path('/data/state/review.sqlite3')
db=sqlite3.connect(p)
dataset=json.loads(db.execute('SELECT payload FROM datasets LIMIT 1').fetchone()[0])
page_size=db.execute('PRAGMA page_size').fetchone()[0]
index=0
while db.execute('PRAGMA page_count').fetchone()[0]*page_size <= 24*1024*1024:
 identifier='synthetic-growth-'+str(index)
 dataset['dataset_id']=identifier
 db.execute('INSERT INTO datasets VALUES (?,?)',(identifier,json.dumps(dataset)))
 index+=1
db.commit()
db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
db.close()
print(json.dumps({'bytes':p.stat().st_size,'added_datasets':index}))
"""))
            record("valid persisted history exceeds the initial transfer limit", grown["bytes"] > 24 * 1024 * 1024)
            helper("from pathlib import Path;Path('/etc/secrets/patchproof-state.b64').unlink()")
            start()
            port = ready()
            record("normal restart works after seed removal", True)
            record("normal restart accepts history larger than the transfer limit", request(port, "/api/status")[0] == 200)
            record("normal restart keeps later experiment", json.loads(request(port, "/api/experiments/" + run_id)[2])["status"] == "completed")
            summary = json.loads(helper("import sqlite3,json;db=sqlite3.connect('/data/state/provider-usage.sqlite3');print(json.dumps(db.execute('SELECT count(*),sum(coalesce(charged,reserved)) FROM usage').fetchone()));db.close()"))
            record("normal restart keeps accounted and unresolved amounts", summary == [2, 260])
            command("docker", "exec", current, "python", "-c", "from pathlib import Path;import os,signal;[os.kill(int(p.parent.name),signal.SIGTERM) for p in Path('/proc').glob('[0-9]*/cmdline') if p.read_bytes().split(b'\\0')[0]==b'caddy']")
            record("gateway death stops the entire container", exit_code() == 1)
            current = None
            start()
            port = ready()
            command("docker", "exec", current, "python", "-c", "from pathlib import Path;import os,signal;[os.kill(int(p.parent.name),signal.SIGTERM) for p in Path('/proc').glob('[0-9]*/cmdline') if b'patchproof' in p.read_bytes().split(b'\\0')]")
            record("backend death stops the entire container", exit_code() == 1)
            current = None
            synthetic_key = "synthetic-not-a-provider-key-" + secrets.token_urlsafe(24)
            helper("""import os,sys
from pathlib import Path
p=Path('/etc/secrets/nebius-tokenfactory.key')
p.write_text(sys.stdin.read());os.chown(p,0,1000);p.chmod(0o640)
""", payload=synthetic_key)
            start(isolated=True, extra=("-e", "PATCHPROOF_LIVE_ENABLED=1",
                                        "-e", "PATCHPROOF_CONFIRM_NEBIUS_ACCESS=1",
                                        "-e", "PATCHPROOF_CONFIRM_LIVE_CAP=1",
                                        "-e", "PATCHPROOF_LIVE_CAP_USD=1"))
            live_check = json.loads(command("docker", "exec", "-i", current, "python", "-c", """import json,sys,time,stat,urllib.request
from pathlib import Path
inputs=json.load(sys.stdin)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
deadline=time.monotonic()+45
while True:
 try:
  request=urllib.request.Request('http://127.0.0.1:8780/api/status',headers={'Host':'judge.example.test','Authorization':inputs['authorization']})
  with opener.open(request,timeout=2) as response:
   body=response.read()
  break
 except OSError:
  if time.monotonic()>=deadline: raise RuntimeError('Synthetic live startup timed out')
  time.sleep(0.2)
keys=list(Path('/tmp').glob('patchproof-hosted-*/runtime/nebius-tokenfactory.key'))
assert len(keys)==1
key=keys[0]
metadata={}
for name in ('nebius-tokenfactory.key','judge-users'):
 p=key.parent/name;info=p.lstat()
 metadata[name]={'uid':info.st_uid,'gid':info.st_gid,'mode':info.st_mode&0o777,'regular':stat.S_ISREG(info.st_mode),'outside_site':not p.is_relative_to(key.parent/'site')}
print(json.dumps({'status':json.loads(body),'private_files':metadata,'key_copy_matches':key.read_text()==inputs['expected_key'],'key_absent_from_response':inputs['expected_key'].encode() not in body}))
""", input=json.dumps({"authorization": basic, "expected_key": synthetic_key})).stdout)
            record("normal live-enabled startup succeeds with synthetic key", live_check["status"]["live"]["enabled"] is True)
            record("live CLI keeps the approved one-dollar cumulative cap", live_check["status"]["live"]["cap_usd"] == "1")
            record("live startup copies private files with final service ownership",
                   all(info == {"uid": 10001, "gid": 1000, "mode": 0o600, "regular": True, "outside_site": True}
                       for info in live_check["private_files"].values()))
            record("live startup preserves raw synthetic key without exposing it", live_check["key_copy_matches"] and live_check["key_absent_from_response"])
            record("GET-only live startup preserves existing usage and reservations",
                   live_check["status"]["live_calls"] == 2
                   and Decimal(live_check["status"]["live"]["charged_or_reserved_usd"]) == Decimal("0.00000026"))
            network_mode = command("docker", "inspect", current, "--format", "{{.HostConfig.NetworkMode}}").stdout.strip()
            record("synthetic live startup has no external network", network_mode == "none")
            stop()
            helper("from pathlib import Path;Path('/data/state/provider-usage.sqlite3').unlink()")
            start()
            record("missing ledger stops normal startup", exit_code() == 1)
            current = None
            remains = helper("from pathlib import Path;print(Path('/data/state/provider-usage.sqlite3').exists())").strip()
            record("missing ledger is not recreated", remains == "False")
            empty = prefix + "-empty"
            command("docker", "volume", "create", empty)
            volumes.append(empty)
            helper("import os;os.chown('/data',10001,1000);os.chmod('/data',0o700)", chosen_volume=empty)
            start(chosen_volume=empty)
            record("empty replacement volume stops normal startup", exit_code() == 1)
            current = None
            helper("import os;os.chown('/data',0,0);os.chmod('/data',0o700)", chosen_volume=empty)
            start(chosen_volume=empty)
            record("unwritable platform disk fails closed", exit_code() == 1)
            current = None
            ownership = helper("import os;print(os.stat('/data').st_uid)", chosen_volume=empty).strip()
            record("runtime never escalates to repair disk ownership", ownership == "0")
            start(bootstrap=True, seed_sha=receipt["seed_sha256"], extra=("-e", "PATCHPROOF_LIVE_ENABLED=1"))
            record("bootstrap and live flags cannot be combined", exit_code() == 1)
            current = None
            logs = "".join(command("docker", "logs", name).stdout + command("docker", "logs", name).stderr for name in containers)
            record("logs contain no judge password, hash or synthetic provider key",
                   password not in logs and hashed not in logs and synthetic_key not in logs)
        image_id = command("docker", "image", "inspect", image, "--format", "{{.Id}}").stdout.strip()
        result = {"image": image, "image_id": image_id,
                  "container_limits": {"memory_mb": 512, "cpus": 0.5},
                  "runtime_sha256": hashlib.sha256((APP_ROOT / "deployment/hosted/runtime.py").read_bytes()).hexdigest(),
                  "checks_passed": len(checks), "checks": checks,
                  "provider_calls": 0, "state_kind": "public historical evidence plus synthetic ledger",
                  "public_render_verification": False}
    finally:
        for name in reversed(containers):
            command("docker", "rm", "-f", name, check=False)
        for name in reversed(volumes):
            command("docker", "volume", "rm", name, check=False)
        command("docker", "network", "rm", network, check=False)
    result["cleanup_verified"] = all(command("docker", "inspect", name, check=False).returncode != 0 for name in containers)
    result["cleanup_verified"] = result["cleanup_verified"] and all(command("docker", "volume", "inspect", name, check=False).returncode != 0 for name in volumes)
    result["cleanup_verified"] = result["cleanup_verified"] and command("docker", "network", "inspect", network, check=False).returncode != 0
    if not result["cleanup_verified"]:
        raise AssertionError("Disposable integration resources were not all removed")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="patchproof-hosted:local")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.image, args.output)
    print(json.dumps({key: receipt[key] for key in ("checks_passed", "provider_calls", "cleanup_verified")}, indent=2))


if __name__ == "__main__":
    main()
