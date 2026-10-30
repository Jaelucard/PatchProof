"""Initial acceptance and exposure must commit together before execution starts."""

import asyncio
from contextlib import contextmanager

import httpx
import pytest

from patchproof import app as api
from patchproof.providers import FixtureProvider


def endpoint(app, path, method="GET"):
    return next(
        route.endpoint for route in app.routes
        if getattr(route, "path", None) == path and method in route.methods
    )


def exposures(app):
    with app.state.store.connect() as db:
        return dict(db.execute("SELECT case_hash, count FROM case_exposure"))


async def queue(app, dataset, scenario="improvement"):
    return await endpoint(app, "/api/experiments", "POST")(
        api.RunRequest(
            baseline_prompt="Extract the four fields.",
            dataset={"dataset_id": dataset["dataset_id"]},
            scenario=scenario,
        )
    )


async def cancel_queued(app, experiment_id):
    assert app.state.store.get(experiment_id)["status"] == "queued"
    task = app.state.tasks[experiment_id]
    await endpoint(app, "/api/experiments/{experiment_id}/cancel", "POST")(experiment_id)
    await asyncio.wait_for(task, 3)
    saved = app.state.store.get(experiment_id)
    assert saved["status"] == "cancelled"
    assert saved["observations"] == []
    assert not app.state.tasks


@pytest.fixture
def fixture_calls(monkeypatch):
    counts = {"predict": 0, "revise": 0}

    class CountingProvider(FixtureProvider):
        async def predict(self, *args):
            counts["predict"] += 1
            return await super().predict(*args)

        async def revise(self, *args):
            counts["revise"] += 1
            return await super().revise(*args)

    monkeypatch.setattr(api, "FixtureProvider", CountingProvider)
    return counts


@pytest.mark.parametrize("failure", ["insert", "commit"])
async def test_rejected_initial_save_preserves_fresh_exposure_and_retry(
    tmp_path, monkeypatch, fixture_calls, failure
):
    app = api.create_app(tmp_path / "start.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        dataset = await endpoint(app, "/api/demo")()
        store = app.state.store
        trace = []
        if failure == "commit":
            original_connect = store.connect

            @contextmanager
            def foreign_keys():
                with original_connect() as db:
                    db.execute("PRAGMA foreign_keys=ON")
                    db.set_trace_callback(trace.append)
                    yield db

            monkeypatch.setattr(store, "connect", foreign_keys)
            with store.connect() as db:
                db.execute("CREATE TABLE audit_parent (id INTEGER PRIMARY KEY)")
                db.execute(
                    "CREATE TABLE audit_child (parent_id INTEGER REFERENCES audit_parent(id) "
                    "DEFERRABLE INITIALLY DEFERRED)"
                )
                db.execute(
                    "CREATE TRIGGER reject_start AFTER INSERT ON experiments "
                    "BEGIN INSERT INTO audit_child VALUES (99); END"
                )
        else:
            with store.connect() as db:
                db.execute(
                    "CREATE TRIGGER reject_start BEFORE INSERT ON experiments "
                    "BEGIN SELECT RAISE(ABORT, 'initial experiment insert failed'); END"
                )
        before = exposures(app)
        assert before == {}
        trace.clear()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/experiments",
                json={"baseline_prompt": "Extract fields.",
                      "dataset": {"dataset_id": dataset["dataset_id"]}},
            )
            assert response.status_code == 500
            if failure == "commit":
                assert trace[-2:] == ["COMMIT", "ROLLBACK"]
            assert (await client.get("/api/experiments")).json() == []
            status = (await client.get("/api/status")).json()
            assert status["active_experiment_id"] is None
            assert status["live_calls"] == 0
            assert status["storage_failure"] is None
        assert not app.state.tasks
        assert fixture_calls == {"predict": 0, "revise": 0}
        assert exposures(app) == before
        with store.connect() as db:
            db.execute("DROP TRIGGER reject_start")
            if failure == "commit":
                assert db.execute("SELECT * FROM audit_child").fetchall() == []
        retried = await queue(app, dataset)
        assert retried["prior_exposure"] is False
        assert store.get(retried["id"])["prior_exposure"] is False
        assert len(exposures(app)) == 60
        assert set(exposures(app).values()) == {1}
        assert fixture_calls == {"predict": 0, "revise": 0}
        await cancel_queued(app, retried["id"])


async def test_mid_exposure_failure_rolls_back_existing_and_new_counters(tmp_path, fixture_calls):
    app = api.create_app(tmp_path / "exposure.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        dataset = await endpoint(app, "/api/demo")()
        store = app.state.store
        assert store.expose({"cases": [dataset["cases"][0]]}) is False
        before = exposures(app)
        assert len(before) == 1 and set(before.values()) == {1}
        with store.connect() as db:
            db.execute(
                "CREATE TRIGGER reject_exposure AFTER INSERT ON case_exposure "
                "WHEN (SELECT COUNT(*) FROM case_exposure) = 5 "
                "BEGIN SELECT RAISE(ABORT, 'fifth exposure row failed'); END"
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/api/experiments",
                json={"baseline_prompt": "Extract fields.",
                      "dataset": {"dataset_id": dataset["dataset_id"]}},
            )
            assert response.status_code == 500
            assert (await client.get("/api/experiments")).json() == []
            assert (await client.get("/api/status")).json()["active_experiment_id"] is None
        assert exposures(app) == before
        assert not app.state.tasks
        assert fixture_calls == {"predict": 0, "revise": 0}
        with store.connect() as db:
            db.execute("DROP TRIGGER reject_exposure")
        retried = await queue(app, dataset)
        assert retried["prior_exposure"] is True  # The explicit seed remains real prior exposure.
        after = exposures(app)
        assert len(after) == 60 and sum(after.values()) == 61
        assert all(after[key] == count + 1 for key, count in before.items())
        await cancel_queued(app, retried["id"])


@pytest.mark.parametrize("shutdown", [False, True])
async def test_accepted_queued_cancellation_keeps_reserved_exposure(tmp_path, fixture_calls, shutdown):
    app = api.create_app(tmp_path / "queued.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        dataset = await endpoint(app, "/api/demo")()
        started = await queue(app, dataset)
        assert started["prior_exposure"] is False
        assert app.state.store.get(started["id"])["status"] == "queued"
        committed = exposures(app)
        assert len(committed) == 60 and set(committed.values()) == {1}
        if not shutdown:
            await cancel_queued(app, started["id"])
    saved = app.state.store.get(started["id"])
    assert saved["status"] == "cancelled" and saved["observations"] == []
    assert fixture_calls == {"predict": 0, "revise": 0}
    assert exposures(app) == committed
    async with app.router.lifespan_context(app):
        retried = await queue(app, dataset)
        assert retried["prior_exposure"] is True
        assert set(exposures(app).values()) == {2}
        await cancel_queued(app, retried["id"])


async def test_accepted_provider_error_keeps_reserved_exposure(tmp_path):
    app = api.create_app(tmp_path / "provider-error.sqlite3", fixture_delay=0)
    async with app.router.lifespan_context(app):
        dataset = await endpoint(app, "/api/demo")()
        started = await queue(app, dataset, scenario="provider_failure")
        assert started["prior_exposure"] is False
        committed = exposures(app)
        await asyncio.wait_for(app.state.tasks[started["id"]], 5)
        saved = app.state.store.get(started["id"])
        assert saved["status"] == "error" and len(saved["observations"]) == 7
        assert exposures(app) == committed
        assert not app.state.tasks
        retried = await queue(app, dataset)
        assert retried["prior_exposure"] is True
        assert set(exposures(app).values()) == {2}
        await cancel_queued(app, retried["id"])
