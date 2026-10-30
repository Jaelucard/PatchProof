"""Cancellation wins while a local response is pending, including the last one."""

import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from patchproof import app as api
from patchproof.domain import build_dataset
from patchproof.engine import run_experiment
from patchproof.providers import FixtureProvider


@pytest.mark.parametrize("location", ["prediction", "revision", "last_prediction"])
async def test_cancel_interrupts_pending_provider_and_preserves_saved_results(
    tmp_path, monkeypatch, location
):
    entered, aborted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    last_final_id = None

    class ControlledProvider(FixtureProvider):
        async def hold(self):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                aborted.set()
                raise

        async def predict(self, prompt, case, stage):
            if (location == "prediction" and self.calls == 7) or (
                location == "last_prediction"
                and case["id"] == last_final_id and stage == "candidate_2"
            ):
                await self.hold()
            return await super().predict(prompt, case, stage)

        async def revise(self, *args):
            if location == "revision":
                await self.hold()
            return await super().revise(*args)

    monkeypatch.setattr(api, "FixtureProvider", ControlledProvider)
    app = api.create_app(tmp_path / "test.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            data = (await client.get("/api/demo")).json()
            last_final_id = [c["id"] for c in data["cases"] if c["partition"] == "final"][-1]
            response = await client.post(
                "/api/experiments", json={"baseline_prompt": "Extract fields.", "dataset": data}
            )
            experiment_id = response.json()["id"]
            task = app.state.tasks[experiment_id]
            try:
                await asyncio.wait_for(entered.wait(), 3)
                before = app.state.store.get(experiment_id)
                assert before["observations"]
                response = await client.post(f"/api/experiments/{experiment_id}/cancel", json={})
                assert response.status_code == 200
                await asyncio.wait_for(aborted.wait(), 1)
                await asyncio.wait_for(asyncio.shield(task), 1)
                after = app.state.store.get(experiment_id)
                assert after["status"] == "cancelled"
                assert after["observations"] == before["observations"]
                assert after["verdict"] == "inconclusive"
                assert not app.state.tasks
                assert (await client.get("/api/status")).json()["active_experiment_id"] is None
                # Cancelling a terminal run is an idempotent read of that saved run.
                again = await client.post(f"/api/experiments/{experiment_id}/cancel", json={})
                assert again.json() == after
            finally:
                release.set()
                await asyncio.wait_for(asyncio.shield(task), 3)


def endpoint(app, path, method="GET"):
    return next(
        route.endpoint for route in app.routes
        if getattr(route, "path", None) == path and method in route.methods
    )


@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancel_before_task_body_starts_finalizes_and_cleans_registry(tmp_path, shutdown):
    app = api.create_app(tmp_path / "queued.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        data = await endpoint(app, "/api/demo")()
        started = await endpoint(app, "/api/experiments", "POST")(
            api.RunRequest(baseline_prompt="Extract fields.", dataset=data)
        )
        experiment_id = started["id"]
        assert app.state.store.get(experiment_id)["status"] == "queued"
        if not shutdown:
            cancel = endpoint(app, "/api/experiments/{experiment_id}/cancel", "POST")
            await cancel(experiment_id)
            await cancel(experiment_id)
            await asyncio.gather(*list(app.state.tasks.values()))
    saved = app.state.store.get(experiment_id)
    assert saved["status"] == "cancelled"
    assert saved["observations"] == []
    assert saved["verdict"] == "inconclusive"
    assert not app.state.tasks


async def test_callback_cancellation_on_last_response_cannot_mark_run_completed():
    data = json.loads((api.APP_ROOT / "data/demo.json").read_text())
    dataset = build_dataset(data["name"], data["cases"], trusted_partitions=True)
    last_final_id = [c["id"] for c in dataset["cases"] if c["partition"] == "final"][-1]
    state = {"cancelled": False}

    class LastResponseCancellation(FixtureProvider):
        async def predict(self, prompt, case, stage):
            raw = await super().predict(prompt, case, stage)
            if case["id"] == last_final_id and stage == "candidate_2":
                state["cancelled"] = True
            return raw

    saved = []

    async def save(snapshot):
        saved.append(deepcopy(snapshot))

    result = await run_experiment(
        {"id": "last-response", "baseline_prompt": "Extract fields.", "dataset": dataset,
         "execution_kind": "Fixture simulation", "model": {}},
        LastResponseCancellation(delay=0), save, lambda: state["cancelled"],
    )
    assert result["status"] == "cancelled"
    assert len(result["observations"]) == 150
    assert result["verdict"] == "inconclusive"
    assert saved[-1] == result


async def test_repeated_cancel_does_not_interrupt_provider_cleanup(tmp_path, monkeypatch):
    entered, cleaning, release_cleanup, closed = (asyncio.Event() for _ in range(4))

    class CleanupProvider(FixtureProvider):
        async def predict(self, *args):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleaning.set()
                await release_cleanup.wait()
                closed.set()
                raise

    monkeypatch.setattr(api, "FixtureProvider", CleanupProvider)
    app = api.create_app(tmp_path / "cleanup.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        data = await endpoint(app, "/api/demo")()
        started = await endpoint(app, "/api/experiments", "POST")(
            api.RunRequest(baseline_prompt="Extract fields.", dataset=data)
        )
        experiment_id = started["id"]
        task = app.state.tasks[experiment_id]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            cancel = endpoint(app, "/api/experiments/{experiment_id}/cancel", "POST")
            await cancel(experiment_id)
            await asyncio.wait_for(cleaning.wait(), 1)
            await cancel(experiment_id)
        finally:
            release_cleanup.set()
            await asyncio.wait_for(asyncio.shield(task), 1)
        assert closed.is_set()
        assert app.state.store.get(experiment_id)["status"] == "cancelled"
        assert not app.state.tasks
