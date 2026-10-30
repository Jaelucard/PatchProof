"""The launcher must not mistake a partial frontend distribution for a usable build."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
INDEX = '<script type="module" src="/assets/entry.js"></script><link rel="stylesheet" href="/assets/style.css">'


def launcher_fixture(tmp_path):
    app = tmp_path / "task/outputs/app"
    dist = app / "frontend/dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets/entry.js").write_text("console.log('fixture');")
    (dist / "assets/style.css").write_text("body { color: black; }")
    repair = tmp_path / "complete-build"
    shutil.copytree(dist, repair)
    shutil.copy2(APP_ROOT / "start.sh", app / "start.sh")
    events = tmp_path / "events"
    python = tmp_path / "task/work/venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(
        '#!/bin/sh\nif [ "$1" = -m ]; then '
        'printf "server\\n" >> "$LAUNCHER_EVENTS"; exit 0; fi\n'
        f'exec {shlex.quote(sys.executable)} "$@"\n'
    )
    python.chmod(0o755)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    npm = binaries / "npm"
    npm.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, shutil, sys\n"
        "with open(os.environ['LAUNCHER_EVENTS'], 'a') as log: log.write('npm ' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:] == ['run', 'build'] and os.environ['REPAIR_BUILD'] == '1':\n"
        "    shutil.rmtree(os.environ['DIST_PATH'])\n"
        "    shutil.copytree(os.environ['REPAIR_SOURCE'], os.environ['DIST_PATH'])\n"
    )
    npm.chmod(0o755)
    uv = binaries / "uv"
    uv.write_text('#!/bin/sh\necho "Unexpected install attempt" >&2\nexit 99\n')
    uv.chmod(0o755)

    def launch(repair_build=True):
        result = subprocess.run(
            [str(app / "start.sh")], cwd="/", capture_output=True, text=True, timeout=10,
            env={**os.environ, "PATH": str(binaries) + ":" + os.environ["PATH"],
                 "LAUNCHER_EVENTS": str(events), "REPAIR_BUILD": str(int(repair_build)),
                 "REPAIR_SOURCE": str(repair), "DIST_PATH": str(dist)},
        )
        calls = events.read_text().splitlines() if events.exists() else []
        return result, calls

    return dist, launch


def test_complete_frontend_skips_install_and_build(tmp_path):
    _, launch = launcher_fixture(tmp_path)
    result, calls = launch()
    assert result.returncode == 0, result.stderr
    assert calls == ["server"]


def test_local_asset_urls_resolve_query_fragment_and_percent_encoding(tmp_path):
    dist, launch = launcher_fixture(tmp_path)
    (dist / "assets/entry.js").rename(dist / "assets/entry file.js")
    (dist / "index.html").write_text(
        '<script type="module" src="./assets/entry%20file.js?version=1#../ignored"></script>'
        '<link rel="alternate stylesheet" href="/assets/style.css?version=2#section">'
    )
    result, calls = launch()
    assert result.returncode == 0, result.stderr
    assert calls == ["server"]


@pytest.mark.parametrize("fault", [
    "missing_index", "empty_index", "invalid_utf8_index", "missing_js", "empty_js",
    "missing_css", "empty_css", "stale_hash", "second_module_missing", "second_css_missing",
    "no_module", "no_stylesheet", "external_module", "external_stylesheet", "encoded_escape",
    "symlink_escape", "base_href", "invalid_url", "nul_path",
])
def test_partial_or_invalid_frontend_is_rebuilt_before_server_start(tmp_path, fault):
    dist, launch = launcher_fixture(tmp_path)
    index = dist / "index.html"
    if fault.startswith("missing_"):
        (index if fault == "missing_index" else dist / ("assets/entry.js" if fault == "missing_js" else "assets/style.css")).unlink()
    elif fault.startswith("empty_"):
        (index if fault == "empty_index" else dist / ("assets/entry.js" if fault == "empty_js" else "assets/style.css")).write_bytes(b"")
    elif fault == "invalid_utf8_index":
        index.write_bytes(b"\xff")
    elif fault == "stale_hash":
        index.write_text(INDEX.replace("entry.js", "different-hash.js"))
    elif fault == "second_module_missing":
        index.write_text(INDEX + '<script type="module" src="/assets/missing.js"></script>')
    elif fault == "second_css_missing":
        index.write_text(INDEX + '<link rel="stylesheet" href="/assets/missing.css">')
    elif fault == "no_module":
        index.write_text('<link rel="stylesheet" href="/assets/style.css">')
    elif fault == "no_stylesheet":
        index.write_text('<script type="module" src="/assets/entry.js"></script>')
    elif fault == "external_module":
        index.write_text(INDEX.replace("/assets/entry.js", "https://example.invalid/entry.js"))
    elif fault == "external_stylesheet":
        index.write_text(INDEX.replace("/assets/style.css", "//example.invalid/style.css"))
    elif fault == "encoded_escape":
        (dist.parent / "outside.js").write_text("console.log('outside');")
        index.write_text(INDEX.replace("/assets/entry.js", "../%6futside.js"))
    elif fault == "symlink_escape":
        outside = dist.parent / "outside.js"
        outside.write_text("console.log('outside');")
        (dist / "assets/entry.js").unlink()
        (dist / "assets/entry.js").symlink_to(outside)
    elif fault == "base_href":
        index.write_text('<base href="/elsewhere/">' + INDEX)
    elif fault == "invalid_url":
        index.write_text(INDEX.replace("/assets/entry.js", "http://[invalid"))
    elif fault == "nul_path":
        index.write_text(INDEX.replace("/assets/entry.js", "/assets/entry%00.js"))
    result, calls = launch()
    assert result.returncode == 0, result.stderr
    assert calls == ["npm ci", "npm run build", "server"]


@pytest.mark.parametrize("missing", ["index.html", "assets/entry.js", "assets/style.css"])
def test_successful_build_command_cannot_start_server_with_incomplete_assets(tmp_path, missing):
    dist, launch = launcher_fixture(tmp_path)
    (dist / missing).unlink()
    result, calls = launch(repair_build=False)
    assert result.returncode != 0
    assert "frontend build is incomplete" in result.stderr.lower()
    assert calls == ["npm ci", "npm run build"]
