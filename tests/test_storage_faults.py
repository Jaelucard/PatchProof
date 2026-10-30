"""Injected local persistence faults must preserve durable evidence and stop clearly."""

import asyncio
from copy import deepcopy
import sqlite3

import httpx
import pytest

from patchproof.app import RunRequest, create_app
from patchproof.domain import compare


def endpoint(app, path, method="GET"):
    return next(
        route.endpoint for route in app.routes
        if getattr(route, "path", None) == path and method in route.methods
    )


class SaveFailures:
    def __init__(self, store, trigger, limit):
        self.real_save, self.real_get = store.save, store.get
        self.trigger, self.limit = trigger, limit
        self.before = None
        self.failures = 0

    def __call__(self, snapshot):
        if self.before is None and self.trigger(snapshot):
            self.before = self.real_get(snapshot["id"])
        if self.before is not None and (self.limit is None or self.failures < self.limit):
            self.failures += 1
            raise sqlite3.OperationalError("Injected local storage failure")
        self.real_save(snapshot)


def independent_pair(snapshot):
    return snapshot.get("phase") == "regression_assessment" and any(
        pair["partition"] == "regression" for pair in snapshot.get("comparisons", [])
    )


def candidate_loss(snapshot):
    return snapshot.get("phase") == "candidate_1_development" and any(
        pair["regressed"]
        for proposal in snapshot.get("proposals", [])
        for pair in proposal["comparisons"]
    )


def observed_pairs(snapshot, candidate_id, partition=None):
    rows = {
        (row["case_id"], row["stage"]): row["result"] for row in snapshot["observations"]
    }
    return [
        compare(rows[(case["id"], "baseline")], rows[(case["id"], candidate_id)])
        for case in snapshot["dataset"]["cases"]
        if (partition is None or case["partition"] == partition)
        and (case["id"], "baseline") in rows and (case["id"], candidate_id) in rows
    ]


def assert_evidence_preserved(actual, before):
    for key in (
        "observations", "dataset", "model", "baseline_prompt", "baseline_prompt_hash",
        "configuration_hash", "selected_candidate_id", "frozen_candidate_hash",
    ):
        assert actual[key] == before[key], key
    assert [(p["id"], p["prompt"], p["prompt_hash"]) for p in actual["proposals"]] == [
        (p["id"], p["prompt"], p["prompt_hash"]) for p in before["proposals"]
    ]


async def start_and_finish(app, dataset, scenario):
    started = await endpoint(app, "/api/experiments", "POST")(
        RunRequest(
            baseline_prompt="Extract the four support ticket fields.",
            dataset={"dataset_id": dataset["dataset_id"]}, scenario=scenario,
        )
    )
    experiment_id = started["id"]
    result = await asyncio.wait_for(
        asyncio.gather(app.state.tasks[experiment_id], return_exceptions=True), 10
    )
    return experiment_id, result[0]


@pytest.mark.parametrize("failures", [1, 2])
@pytest.mark.parametrize("scenario", ["improvement", "regression"])
async def test_transient_fault_reconstructs_selected_evidence(tmp_path, failures, scenario):
    path = tmp_path / "experiment.sqlite3"
    app = create_app(path, fixture_delay=0)
    async with app.router.lifespan_context(app):
        dataset = await endpoint(app, "/api/demo")()
        fault = SaveFailures(app.state.store, independent_pair, failures)
        app.state.store.save = fault
        experiment_id, task_result = await start_and_finish(app, dataset, scenario)
        assert task_result is None
        assert fault.failures == failures
        assert len(fault.before["observations"]) == 92
        assert len(fault.before["comparisons"]) == 30
        saved = app.state.store.get(experiment_id)
        assert_evidence_preserved(saved, fault.before)
        assert saved["status"] == "error"
        assert saved["selected_candidate_id"] == "candidate_2"
        assert saved["verdict"] == ("rejected" if scenario == "regression" else "inconclusive")
        expected_pairs = observed_pairs(saved, "candidate_2")
        expected_losses = sum(len(pair["regressed"]) for pair in expected_pairs)
        assert expected_losses == int(scenario == "regression")
        assert saved["summary"]["observed_cases"] == 31
        assert saved["summary"]["regressions"] == expected_losses
        assert saved["assessments"]["regression"]["regressions"] == expected_losses
        assert saved["assessments"]["regression"]["observed_cases"] == 1
        assert saved["assessments"]["regression"]["status"] == "incomplete"
        assert saved["assessments"]["final"]["status"] == "not_run"
        assert saved["proposals"][0]["development"]["regressions"] > 0
        selected = saved["proposals"][1]
        assert selected["development"] == fault.before["proposals"][1]["development"]
        assert selected["development"]["regressions"] == 0
        assert selected["development"]["complete"] is True
        assert selected["development"]["qualified"] is True
        assert selected["status"] == ("rejected" if expected_losses else "selected")
        assert not app.state.tasks
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            status = (await client.get("/api/status")).json()
            assert status["storage_failure"] is None
            assert status["active_experiment_id"] is None
            assert status["live_calls"] == 0
            assert (await client.get(f"/api/experiments/{experiment_id}")).json() == saved
            assert (
                await client.get(f"/api/experiments/{experiment_id}/export/json")
            ).json() == saved
    restarted = create_app(path, fixture_delay=0)
    async with restarted.router.lifespan_context(restarted):
        assert restarted.state.store.get(experiment_id) == saved


@pytest.mark.parametrize("failures", [1, 2])
async def test_transient_fault_never_promotes_unselected_loss_to_experiment_verdict(
    tmp_path, failures,
):
    app = create_app(tmp_path / "experiment.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        dataset = await endpoint(app, "/api/demo")()
        fault = SaveFailures(app.state.store, candidate_loss, failures)
        app.state.store.save = fault
        experiment_id, task_result = await start_and_finish(app, dataset, "improvement")
        assert task_result is None
        assert fault.failures == failures
        saved = app.state.store.get(experiment_id)
        assert_evidence_preserved(saved, fault.before)
        assert saved["selected_candidate_id"] is None
        assert saved["verdict"] == "inconclusive"
        assert saved["comparisons"] == []
        assert saved["summary"]["regressions"] == 0
        proposal = saved["proposals"][0]
        pairs = observed_pairs(saved, proposal["id"], "development")
        assert proposal["development"]["observed_cases"] == len(pairs) < 30
        assert proposal["development"]["regressions"] == sum(
            len(pair["regressed"]) for pair in pairs
        ) > 0
        assert proposal["development"]["complete"] is False
        assert proposal["development"]["qualified"] is False
        assert proposal["status"] == "rejected"


@pytest.mark.parametrize("fallback_failure", ["write", "read", "missing"])
async def test_failed_fallback_signals_stopped_state_without_overwriting_durable_evidence(
    tmp_path, monkeypatch, fallback_failure,
):
    path = tmp_path / "experiment.sqlite3"
    app = create_app(path, fixture_delay=0)
    async with app.router.lifespan_context(app):
        dataset = await endpoint(app, "/api/demo")()
        fault = SaveFailures(
            app.state.store, independent_pair, None if fallback_failure == "write" else 2
        )
        app.state.store.save = fault

        def failed_read(experiment_id):
            if fault.failures >= 2:
                if fallback_failure == "missing":
                    return None
                raise sqlite3.OperationalError("Private injected read detail")
            return fault.real_get(experiment_id)

        if fallback_failure != "write":
            monkeypatch.setattr(app.state.store, "get", failed_read)
        experiment_id, task_result = await start_and_finish(app, dataset, "regression")
        assert task_result is None
        assert fault.failures == (3 if fallback_failure == "write" else 2)
        saved = fault.real_get(experiment_id)
        assert saved == fault.before  # No mutation from the engine's unsaved terminal state.
        assert saved["status"] == "running"
        assert len(saved["observations"]) == 92
        assert not app.state.tasks

        # The in-process gate must run before any further dataset/storage access.
        def unexpected_dataset_read(_):
            raise AssertionError("A blocked start must not access the database")

        monkeypatch.setattr(app.state.store, "dataset", unexpected_dataset_read)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            status = (await client.get("/api/status")).json()
            failure = status["storage_failure"]
            assert failure["experiment_id"] == experiment_id
            assert "restart" in failure["message"].lower()
            assert "Private injected" not in failure["message"]
            assert status["active_experiment_id"] is None
            assert status["live_calls"] == 0
            body = {"baseline_prompt": "Extract fields.", "dataset": dataset}
            denied = await client.post("/api/experiments", json=body)
            assert denied.status_code == 503
            assert denied.json()["detail"] == failure["message"]
            live = await client.post("/api/experiments", json={**body, "mode": "live"})
            assert live.status_code == 403
            # Restored reads alone must not dismiss the process-level failure.
            monkeypatch.setattr(app.state.store, "get", fault.real_get)
            assert (await client.get(f"/api/experiments/{experiment_id}")).json() == saved
            assert (
                await client.get(f"/api/experiments/{experiment_id}/export/json")
            ).json() == saved
            assert (await client.get("/api/status")).json()["storage_failure"] == failure
    restarted = create_app(path, fixture_delay=0)
    async with restarted.router.lifespan_context(restarted):
        recovered = restarted.state.store.get(experiment_id)
        assert_evidence_preserved(recovered, saved)
        assert recovered["status"] == "interrupted"
        assert recovered["verdict"] == "rejected"
        assert recovered["summary"]["regressions"] == 1
        assert (await endpoint(restarted, "/api/status")())["storage_failure"] is None
        fresh = await endpoint(restarted, "/api/demo")()
        fresh_id, result = await start_and_finish(restarted, fresh, "improvement")
        assert result is None
        assert restarted.state.store.get(fresh_id)["status"] == "completed"


def test_reconstruction_ignores_stale_unselected_global_loss(tmp_path):
    """Modern snapshots with no selected candidate cannot inherit global rejection."""
    app = create_app(tmp_path / "experiment.sqlite3")
    snapshot = {
        "id": "unselected", "status": "running", "selected_candidate_id": None,
        "observations": [], "dataset": {"cases": []}, "proposals": [],
        "comparisons": [{"regressed": ["order_id"]}],
    }
    original = deepcopy(snapshot)
    app.state.store.save(snapshot)
    app.state.store.recover()
    recovered = app.state.store.get(snapshot["id"])
    assert recovered["verdict"] == "inconclusive"
    assert recovered["comparisons"] == []
    assert recovered["observations"] == original["observations"]


async def test_known_storage_failure_remains_visible_when_usage_ledger_is_unreadable(
    tmp_path, monkeypatch,
):
    app = create_app(tmp_path / "experiment.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        dataset = await endpoint(app, "/api/demo")()
        app.state.store.save = SaveFailures(app.state.store, independent_pair, None)
        experiment_id, result = await start_and_finish(app, dataset, "regression")
        assert result is None
        failure = (await endpoint(app, "/api/status")())["storage_failure"]
        assert failure["experiment_id"] == experiment_id

        def unreadable_ledger():
            raise sqlite3.OperationalError("Injected directory-wide storage failure")

        monkeypatch.setattr(app.state.ledger, "summary", unreadable_ledger)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/status")
            assert response.status_code == 200
            status = response.json()
            assert status["storage_failure"] == failure
            assert status["active_experiment_id"] is None
            assert status["live_calls"] is None
            assert status["live"]["enabled"] is False
