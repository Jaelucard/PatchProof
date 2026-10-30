"""Local integration checks. All observations use deterministic scripts, never a network."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from patchproof.app import APP_ROOT, create_app
from patchproof.domain import build_dataset, digest
from patchproof.store import Store


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "patchproof.sqlite3", fixture_delay=0)) as c:
        yield c


def wait(c, experiment_id):
    for _ in range(1500):
        e = c.get("/api/experiments/" + experiment_id).json()
        if e["status"] not in {"queued", "running"}:
            return e
        time.sleep(0.002)
    raise AssertionError("Fixture experiment did not stop within bounded wait")


def run(c, dataset, scenario="improvement"):
    response = c.post(
        "/api/experiments",
        json={
            "baseline_prompt": dataset.get("starter_prompt", "Extract the four fields."),
            "dataset": dataset,
            "scenario": scenario,
            "mode": "fixture",
        },
    )
    assert response.status_code == 202, response.text
    return wait(c, response.json()["id"])


def test_complete_workflow_saved_exports_and_rejected_proposal_isolation(client):
    dataset = client.get("/api/demo").json()
    assert len(dataset["cases"]) == 60
    e = run(client, dataset)
    assert e["status"] == "completed", e
    assert e["selected_candidate_id"] == "candidate_2"
    assert e["frozen_candidate_hash"] == digest(e["proposals"][1]["prompt"])
    assert e["proposals"][0]["development"]["regressions"] >= 1
    assert e["proposals"][1]["development"]["regressions"] == 0
    assert e["summary"]["regressed"] == 0
    assert e["verdict"] == "inconclusive"  # Simulation and provisional labels must remain visible.
    assert e["assessments"]["final"]["status"] == "passed"
    evidence = client.get(f"/api/experiments/{e['id']}/export/json")
    assert evidence.json() == e
    report = client.get(f"/api/experiments/{e['id']}/export/markdown").text
    assert "Fixture simulation" in report
    assert dataset["cases"][0]["text"] in report
    assert "candidate_1" in report and "candidate_2" in report
    prompt = client.get(f"/api/experiments/{e['id']}/export/prompt").text
    assert e["proposals"][1]["prompt"] in prompt
    discarded = client.get(
        f"/api/experiments/{e['id']}/export/prompt?candidate_id=candidate_1"
    ).text
    assert e["proposals"][0]["prompt"] in discarded
    assert client.get("/api/status").json()["live_calls"] == 0
    assert client.get("/api/experiments").json()[0]["id"] == e["id"]
    repeated = run(client, dataset)
    assert repeated["prior_exposure"] is True
    assert repeated["verdict"] == "inconclusive"


def test_regression_stops_final_and_retains_both_prompts(client):
    e = run(client, client.get("/api/demo").json(), "regression")
    assert e["verdict"] == "rejected"
    assert e["summary"]["regressed"] > 0
    assert e["assessments"]["regression"]["status"] == "failed"
    assert e["assessments"]["final"]["status"] == "not_run"
    assert not any(o["partition"] == "final" for o in e["observations"])
    assert len(e["proposals"]) == 2
    assert client.get(f"/api/experiments/{e['id']}/export/prompt").status_code == 200


def test_provider_failure_preserves_partial_observations(client):
    e = run(client, client.get("/api/demo").json(), "provider_failure")
    assert e["status"] == "error"
    assert e["verdict"] == "inconclusive"
    assert len(e["observations"]) == 7
    assert not e["selected_candidate_id"]
    assert client.get(f"/api/experiments/{e['id']}/export/prompt").status_code == 404
    assert client.get(f"/api/experiments/{e['id']}/export/json").json() == e


def test_both_live_confirmations_pending_backend_denies_before_work(client):
    response = client.post(
        "/api/experiments", json={"baseline_prompt": "test", "dataset": {}, "mode": "live"}
    )
    assert response.status_code == 403
    status = client.get("/api/status").json()
    assert status["live"]["access_confirmed"] is False
    assert status["live"]["cap_confirmed"] is False
    assert status["live_calls"] == 0
    assert client.get("/api/experiments").json() == []


def test_import_validation_templates_attestation_and_client_cannot_change_truth(client):
    template = client.get("/api/templates/json").json()
    response = client.post(
        "/api/datasets/import",
        json={"content": json.dumps(template), "format": "json", "reviewed": False},
    )
    assert response.status_code == 200, response.text
    dataset = response.json()
    assert dataset["cases"][0]["expected"]["order_id"] == "004812"
    assert dataset["human_review_pending"] is True
    assert dataset["full_experiment_eligible"] is False
    dataset["review_status"] = "user_attested"
    dataset["cases"][0]["fixture_outputs"] = {
        k: "{}" for k in ("baseline", "candidate_1", "candidate_2")
    }
    response = client.post("/api/experiments", json={"baseline_prompt": "test", "dataset": dataset})
    assert response.status_code == 422
    assert "scripted outputs" in response.text
    template["cases"].append(template["cases"][0])
    response = client.post(
        "/api/datasets/import", json={"content": json.dumps(template), "format": "json"}
    )
    assert response.status_code == 422
    assert "duplicate" in response.text.lower()
    reviewed = client.post(
        "/api/datasets/import",
        json={
            "content": client.get("/api/templates/scripted").text,
            "format": "json",
            "reviewed": True,
        },
    ).json()
    assert reviewed["review_status"] == "user_attested"
    assert reviewed["full_experiment_eligible"] is True
    # Send a tampered browser snapshot; server uses its stored immutable copy.
    original_text = reviewed["cases"][0]["text"]
    reviewed["cases"][0]["text"] = "tampered"
    reviewed["manifest"]["development"] = []
    e = run(client, reviewed)
    assert e["dataset"]["cases"][0]["text"] == original_text
    assert e["dataset"]["manifest"]["development"]
    assert e["verdict"] != "eligible_for_human_review"


def test_cancellation_single_active_and_safe_rendered_import(tmp_path):
    with TestClient(create_app(tmp_path / "db.sqlite3", fixture_delay=0.03)) as c:
        dataset = c.get("/api/demo").json()
        body = {"baseline_prompt": "test", "dataset": dataset}
        first = c.post("/api/experiments", json=body).json()
        assert c.post("/api/experiments", json=body).status_code == 409
        assert c.post(f"/api/experiments/{first['id']}/cancel", json={}).status_code == 200
        e = wait(c, first["id"])
        assert e["status"] == "cancelled"
        assert e["verdict"] == "inconclusive"
        assert c.get("/api/status").json()["active_experiment_id"] is None
        bad_origin = c.post(
            "/api/datasets/import", json={}, headers={"origin": "https://untrusted.example"}
        )
        assert bad_origin.status_code == 403
        assert c.post(f"/api/experiments/{first['id']}/cancel", content="").status_code == 415
        assert c.get("/api/status", headers={"host": "rebind.example"}).status_code == 400


def test_restart_marks_unfinished_and_preserves_observed_rejection(tmp_path):
    path = tmp_path / "db.sqlite3"
    store = Store(path)
    store.save(
        {
            "id": "incomplete",
            "status": "running",
            "phase": "final",
            "verdict": "inconclusive",
            "comparisons": [],
        }
    )
    store.save(
        {
            "id": "rejected",
            "status": "running",
            "phase": "regression",
            "verdict": "rejected",
            "comparisons": [{"regressed": ["order_id"]}],
        }
    )
    with TestClient(create_app(path)):
        assert store.get("incomplete")["status"] == "interrupted"
        assert store.get("incomplete")["verdict"] == "inconclusive"
        assert store.get("rejected")["status"] == "interrupted"
        assert store.get("rejected")["verdict"] == "rejected"


def test_prior_exposure_tracks_cases_even_when_scripts_or_splits_change(tmp_path):
    data = json.loads((APP_ROOT / "data/demo.json").read_text())
    first = build_dataset(
        data["name"], data["cases"], source="demo", trusted_partitions=True, review_status="draft"
    )
    second = build_dataset("New name", data["cases"], reviewed=True)
    assert first["version_hash"] != second["version_hash"]
    store = Store(tmp_path / "db.sqlite3")
    assert store.expose(first) is False
    assert store.expose(second) is True


@pytest.mark.parametrize("label_status", [[], {}, False, 3])
def test_malformed_optional_label_metadata_has_actionable_422(client, label_status):
    template = client.get("/api/templates/json").json()
    template["cases"][0]["label_status"] = label_status
    response = client.post(
        "/api/datasets/import", json={"content": json.dumps(template), "format": "json"}
    )
    assert response.status_code == 422, response.text
    assert "label_status must be a string" in response.text


def test_exposure_survives_changed_case_ids_and_corrected_labels(tmp_path):
    data = json.loads((APP_ROOT / "data/demo.json").read_text())
    original = build_dataset(data["name"], data["cases"])
    changed = json.loads(json.dumps(data["cases"]))
    for case in changed:
        case["id"] = "renamed-" + case["id"]
        case["expected"]["needs_review"] = not case["expected"]["needs_review"]
    renamed = build_dataset("Renamed cases, corrected labels", changed, reviewed=True)
    assert original["cases"][0]["case_hash"] != renamed["cases"][0]["case_hash"]
    store = Store(tmp_path / "db.sqlite3")
    assert store.expose(original) is False
    assert store.expose(renamed) is True


def test_restart_reconstructs_observed_regression_before_comparison_save(tmp_path):
    from patchproof.domain import evaluate

    path = tmp_path / "db.sqlite3"
    data = json.loads((APP_ROOT / "data/demo.json").read_text())
    dataset = build_dataset(data["name"], data["cases"], source="demo", trusted_partitions=True)
    case = next(c for c in dataset["cases"] if c["partition"] == "regression")
    expected = case["expected"]
    wrong = {**expected, "order_id": "LOST-ON-CRASH"}
    baseline = evaluate(json.dumps(expected), expected)
    candidate = evaluate(json.dumps(wrong), expected)
    snapshot = {
        "id": "crash-window",
        "status": "running",
        "phase": "regression_assessment",
        "dataset": dataset,
        "selected_candidate_id": "candidate_2",
        "frozen_candidate_hash": digest("Frozen prompt"),
        "proposals": [
            {
                "id": "candidate_2",
                "prompt": "Frozen prompt",
                "prompt_hash": digest("Frozen prompt"),
                "comparisons": [],
                "status": "selected",
            }
        ],
        "observations": [
            {"case_id": case["id"], "stage": "baseline", "result": baseline},
            {"case_id": case["id"], "stage": "candidate_2", "result": candidate},
        ],
        "comparisons": [],
        "assessments": {
            "development": {"status": "passed"},
            "regression": {"status": "running"},
            "final": {"status": "not_run"},
        },
    }
    store = Store(path)
    store.save(snapshot)
    with TestClient(create_app(path)):
        recovered = store.get("crash-window")
        assert recovered["status"] == "interrupted"
        assert recovered["verdict"] == "rejected"
        assert recovered["comparisons"][0]["regressed"] == ["order_id"]
        assert recovered["proposals"][0]["status"] == "rejected"
        assert recovered["assessments"]["regression"]["status"] == "incomplete"
        assert recovered["assessments"]["final"]["status"] == "not_run"
        assert recovered["summary"]["regressed"] == 1
        assert recovered["assessments"]["regression"]["regressions"] == 1
        assert recovered["assessments"]["regression"]["baseline_passing_checks"] == 6
        assert recovered["assessments"]["regression"]["candidate_passing_checks"] == 5
        assert recovered["completed_at"]


@pytest.mark.parametrize(
    "content",
    [
        '{"baseline_prompt":"\\ud800","dataset":{}}',
        '{"mode":"fixture","mode":"live","baseline_prompt":"test","dataset":{}}',
        '{"baseline_prompt":NaN,"dataset":{}}',
        "{" * 1200,
    ],
)
def test_invalid_request_json_and_unicode_are_actionable(client, content):
    response = client.post(
        "/api/experiments", content=content, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422, response.text
    assert "Invalid request JSON or Unicode" in response.text
    assert client.get("/api/experiments").json() == []
