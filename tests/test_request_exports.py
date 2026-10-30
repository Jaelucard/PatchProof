"""Untrusted identifiers remain data at the request and report boundaries."""

import json
import re
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from patchproof.app import create_app
from patchproof.domain import build_dataset, digest
from patchproof.exports import markdown


def test_custom_loopback_port_accepts_same_origin_but_not_other_origins(tmp_path):
    with TestClient(create_app(tmp_path / "db.sqlite3"), base_url="http://127.0.0.1:9876") as client:
        template = client.get("/api/templates/json").text
        body = {"format": "json", "content": template}
        accepted = client.post(
            "/api/datasets/import", json=body, headers={"Origin": "http://127.0.0.1:9876"}
        )
        assert accepted.status_code == 200, accepted.text
        for origin in ("http://127.0.0.1:9877", "https://untrusted.example", "null"):
            denied = client.post("/api/datasets/import", json=body, headers={"Origin": origin})
            assert denied.status_code == 403


def test_reloading_demo_reuses_registered_snapshot(tmp_path):
    app = create_app(tmp_path / "db.sqlite3")
    with TestClient(app) as client:
        snapshots = [
            client.get("/api/demo", headers={"Origin": "https://untrusted.example"}).json()
            for _ in range(10)
        ]
        assert all(item == snapshots[0] for item in snapshots)
        with app.state.store.connect() as db:
            assert db.execute("SELECT count(*) FROM datasets").fetchone()[0] == 1


@pytest.mark.parametrize("identity", [[], {}, 2**100, True, None, "x" * 101])
def test_invalid_dataset_identity_is_client_error_without_start(tmp_path, identity):
    with TestClient(create_app(tmp_path / "db.sqlite3"), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/experiments",
            json={"baseline_prompt": "Extract fields", "dataset": {"dataset_id": identity}},
        )
        assert response.status_code == 422, response.text
        assert client.get("/api/experiments").json() == []
        assert client.get("/api/status").json()["live_calls"] == 0


def test_export_fences_imported_names_and_ids_with_embedded_markdown(tmp_path):
    injected = "```\n\n![remote](https://example.invalid/tracker)\n\n# Forged verdict"
    expected = {
        "order_id": "0019", "issue_type": "other",
        "requested_action": "cancel_order", "needs_review": False,
    }
    data = {
        "name": injected,
        "cases": [{
            "id": injected, "text": "Please cancel order 0019.", "expected": expected,
            "fixture_outputs": {
                stage: json.dumps(expected)
                for stage in ("baseline", "candidate_1", "candidate_2")
            },
        }],
    }
    with TestClient(create_app(tmp_path / "db.sqlite3", fixture_delay=0)) as client:
        imported = client.post(
            "/api/datasets/import", json={"format": "json", "content": json.dumps(data)}
        )
        assert imported.status_code == 200, imported.text
        started = client.post(
            "/api/experiments", json={"baseline_prompt": "Extract", "dataset": imported.json()}
        )
        assert started.status_code == 202
        run_id = started.json()["id"]
        for _ in range(100):
            saved = client.get(f"/api/experiments/{run_id}").json()
            if saved["status"] not in {"running", "queued"}:
                break
            time.sleep(.01)
        assert saved["status"] == "completed"
        report = client.get(f"/api/experiments/{run_id}/export/markdown").text
        # Remove fenced regions as a Markdown renderer does before reading headings/links.
        outside, fence = [], None
        for line in report.splitlines():
            if fence is not None:
                if line == fence:
                    fence = None
            elif re.match(r"^`{3,}(?:[a-z]+)?$", line):
                fence = re.match(r"^`+", line).group()
            else:
                outside.append(line)
        assert fence is None
        assert "Forged verdict" not in "\n".join(outside)
        assert "https://example.invalid" not in "\n".join(outside)
        assert injected in report  # The original values remain inspectable.
        evidence = client.get(f"/api/experiments/{run_id}/export/json").json()
        assert evidence["dataset"]["name"] == injected
        assert evidence["dataset"]["cases"][0]["id"] == injected


@pytest.mark.parametrize(
    "baseline,candidate,expected_diff",
    [
        ("Extract.", "Extract.\n", "--- original\n+++ candidate_1\n@@ -1 +1,2 @@\n Extract.\n+"),
        ("Extract.\n", "Extract.", "--- original\n+++ candidate_1\n@@ -1,2 +1 @@\n Extract.\n-"),
        ("Extract.", "Extract.\n\n", "--- original\n+++ candidate_1\n@@ -1 +1,3 @@\n Extract.\n+\n+"),
        ("Extract.\n", "Extract.\n", ""),
        ("A\u2028B", "A\nB", "--- original\n+++ candidate_1\n@@ -1 +1,2 @@\n-A\u2028B\n+A\n+B"),
        ("A\r\nB", "A\nB", "--- original\n+++ candidate_1\n@@ -1,2 +1,2 @@\n-A\r\n+A\n B"),
    ],
    ids=["add-final-lf", "remove-final-lf", "add-two-lfs", "identical", "unicode-separator", "crlf"],
)
def test_markdown_diff_preserves_prompt_line_boundaries(baseline, candidate, expected_diff):
    dataset = build_dataset("Newline export evidence", [{
        "id": "synthetic", "text": "A synthetic support ticket.",
        "expected": {"order_id": None, "issue_type": "other",
                     "requested_action": "other", "needs_review": False},
    }])
    saved = {
        "id": "synthetic-export", "created_at": "2026-10-21T00:00:00Z",
        "execution_kind": "Fixture simulation", "status": "completed", "phase": "completed",
        "dataset": dataset, "model": {}, "usage": {"live_calls": 0},
        "baseline_prompt": baseline, "baseline_prompt_hash": digest(baseline),
        "proposals": [{"id": "candidate_1", "prompt": candidate, "prompt_hash": digest(candidate)}],
    }
    original = deepcopy(saved)
    report = markdown(saved)
    diff = report.split("Prompt diff:\n```diff\n", 1)[1].split("\n```", 1)[0]
    assert diff == expected_diff
    assert f"## Original prompt\n```text\n{baseline}\n```" in report
    assert f"Prompt hash: {digest(candidate)}\n```text\n{candidate}\n```" in report
    assert saved == original
