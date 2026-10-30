"""Single-user localhost API; live inference requires explicit server configuration."""

from __future__ import annotations

import asyncio
import csv
import io
import hashlib
import json
import sqlite3
from copy import deepcopy
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .domain import (
    MAX_IMPORT_BYTES,
    STARTER_PROMPT,
    ValidationError,
    build_dataset,
    digest,
    parse_import,
    strict_json,
)
from .engine import run_experiment
from .exports import markdown, proposal
from .providers import FixtureProvider, LiveAuthorization, LiveBlocked, LiveConfig, UsageLedger
from .store import Store

APP_ROOT = Path(__file__).resolve().parents[2]
STORAGE_FAILURE_MESSAGE = (
    "Experiment stopped, but its final status could not be saved. "
    "Saved evidence is unchanged. Restore local database access and restart PatchProof "
    "before starting another experiment."
)


def now():
    return datetime.now(timezone.utc).isoformat()


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=2_000_000)
    format: Literal["json", "csv"]
    reviewed: StrictBool = False


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_prompt: str = Field(min_length=1, max_length=20_000)
    dataset: dict
    scenario: Literal["improvement", "regression", "provider_failure"] = "improvement"
    mode: Literal["fixture", "live"] = "fixture"


def create_app(
    database_path: Path, *, fixture_delay: float = 0.015, live_config: LiveConfig | None = None,
):
    if live_config is not None:
        live_config.check()
    store = Store(database_path)
    ledger = UsageLedger(database_path.parent / "provider-usage.sqlite3")
    authorization = live_config.authorization if live_config else LiveAuthorization()
    tasks: dict[str, asyncio.Task] = {}
    cancelled: set[str] = set()
    lock = asyncio.Lock()
    demo_dataset: dict | None = None
    storage_failure: dict | None = None

    def request_cancellation(experiment_id: str) -> None:
        task = tasks.get(experiment_id)
        if task is None or experiment_id in cancelled:
            return
        cancelled.add(experiment_id)
        # A queued task must enter its coroutine to finalize the saved run and
        # clean its registry entry. Running tasks can interrupt a provider await.
        if (store.get(experiment_id) or {}).get("status") != "queued":
            task.cancel()

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        for experiment_id in list(tasks):
            request_cancellation(experiment_id)
        if tasks:
            await asyncio.gather(*list(tasks.values()), return_exceptions=True)

    app = FastAPI(title="PatchProof", lifespan=lifespan)
    app.state.store, app.state.ledger = store, ledger
    app.state.authorization, app.state.tasks = authorization, tasks
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = {
            "http://127.0.0.1:8766",
            "http://localhost:8766",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        }
        if request.url.hostname in {"127.0.0.1", "localhost"}:
            allowed.add(str(request.base_url).rstrip("/"))
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if origin and origin not in allowed:
                return JSONResponse({"detail": "Cross-origin writes are blocked."}, status_code=403)
            media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                return JSONResponse({"detail": "Writes require application/json."}, status_code=415)
            # JSON can encode each source byte as six ASCII bytes (for example,
            # a CSV NUL becomes \u0000). parse_import still enforces the 2 MB file limit.
            is_import = (
                request.method == "POST" and request.url.path == "/api/datasets/import"
            )
            body_limit = 6 * MAX_IMPORT_BYTES + 1024 if is_import else 2_200_000
            size_error = (
                "Import request exceeds the JSON transport limit for a 2 MB file."
                if is_import else "Request exceeds 2.2 MB limit."
            )
            length = request.headers.get("content-length")
            try:
                valid_length = not length or (
                    length.isascii() and length.isdigit() and int(length) <= body_limit
                )
            except ValueError:  # Python also bounds decimal-to-integer conversion length.
                valid_length = False
            if not valid_length:
                return JSONResponse({"detail": size_error}, status_code=413)
            # Bound streamed bodies too; Content-Length alone is not trustworthy.
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > body_limit:
                    return JSONResponse({"detail": size_error}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
            try:
                strict_json(request._body.decode("utf-8"))
            except (ValueError, RecursionError) as exc:
                return JSONResponse(
                    {"detail": {"errors": [f"Invalid request JSON or Unicode: {str(exc)[:160]}"]}},
                    status_code=422,
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": {"errors": exc.errors}}, status_code=422)

    @app.get("/api/status")
    async def status():
        try:
            usage = ledger.summary()
            live_calls = usage["live_calls"]
        except (sqlite3.Error, OSError):
            if storage_failure is None:
                raise
            live_calls = None
            usage = {}
        live = authorization.public()
        if live_config:
            live.update(
                enabled=storage_failure is None,
                cap_usd=str(authorization.cap_usd),
                model=live_config.model_metadata()["target"],
            )
            if "charged_or_reserved_usd" in usage:
                live["charged_or_reserved_usd"] = usage["charged_or_reserved_usd"]
        return {
            "execution_kind": "Fixture simulation",
            "live": live,
            "active_experiment_id": next(iter(tasks), None),
            "live_calls": live_calls,
            "storage_failure": storage_failure,
        }

    @app.get("/api/demo")
    async def demo():
        nonlocal demo_dataset
        if demo_dataset is not None:
            return demo_dataset
        data = json.loads((APP_ROOT / "data/demo.json").read_text())
        receipt = APP_ROOT / "data/review-receipt.json"
        review = json.loads(receipt.read_text()) if receipt.exists() else {}
        reviewed_bytes = hashlib.sha256((APP_ROOT / "data/demo.json").read_bytes()).hexdigest()
        review_status = (
            "independently_agent_checked"
            if review.get("resolved") is True
            and review.get("demo_sha256") == reviewed_bytes
            and review.get("human_review_pending") is True
            else "draft"
        )
        dataset = build_dataset(
            data["name"],
            data["cases"],
            source="demo",
            trusted_partitions=True,
            review_status=review_status,
        )
        dataset["starter_prompt"] = STARTER_PROMPT
        demo_dataset = store.register_dataset(dataset)
        return demo_dataset

    @app.get("/api/guide")
    async def guide():
        return {"markdown": (APP_ROOT / "data/guide.md").read_text()}

    @app.get("/api/templates/{kind}")
    async def template(kind: str):
        example = {
            "id": "ticket-001",
            "text": "Please refund order 004812. The cup arrived cracked.",
            "expected": {
                "order_id": "004812",
                "issue_type": "damaged_item",
                "requested_action": "refund",
                "needs_review": False,
            },
        }
        if kind == "csv":
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(
                ["id", "text", "order_id", "issue_type", "requested_action", "needs_review"]
            )
            writer.writerow(
                [example["id"], example["text"], "004812", "damaged_item", "refund", "false"]
            )
            return Response(
                out.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="patchproof-template.csv"'},
            )
        if kind == "json":
            value = {"name": "My support-ticket examples", "cases": [example]}
        elif kind == "scripted":
            value = json.loads((APP_ROOT / "data/scripted-import.json").read_text())
        else:
            raise HTTPException(404, "Template not found.")
        return Response(
            json.dumps(value, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="patchproof-{kind}-template.json"'
            },
        )

    @app.post("/api/datasets/import")
    async def import_dataset(body: ImportRequest):
        return store.register_dataset(
            parse_import(body.content, body.format, reviewed=body.reviewed)
        )

    @app.get("/api/experiments")
    async def experiments():
        return [
            {
                "id": e["id"],
                "created_at": e["created_at"],
                "status": e["status"],
                "phase": e["phase"],
                "scenario": e["scenario"],
                "verdict": e.get("verdict", "inconclusive"),
                "dataset_name": e["dataset"]["name"],
                "execution_kind": e["execution_kind"],
            }
            for e in store.all()
        ]

    def require_experiment(experiment_id):
        e = store.get(experiment_id)
        if not e:
            raise HTTPException(404, "Experiment not found.")
        return e

    async def execute(e):
        nonlocal storage_failure
        is_live = e["execution_kind"] == "Live inference"
        provider = None

        def capture_usage(snapshot):
            if is_live and provider is not None:
                snapshot["usage"] = provider.usage_summary()
                snapshot["provider_receipts"] = deepcopy(provider.receipts)

        async def receipt_saved():
            # Attribute the durable ledger reservation before sending the request.
            capture_usage(e)
            store.save(e)

        async def save(snapshot):
            capture_usage(snapshot)
            store.save(snapshot)

        try:
            provider = (
                live_config.make_adapter(ledger, receipt_callback=receipt_saved)
                if is_live else FixtureProvider(e["scenario"], fixture_delay)
            )
            await run_experiment(
                e, provider, save, lambda: e["id"] in cancelled,
                **({"per_call_timeout": 60, "total_timeout": 1800} if is_live else {}),
            )
        except BaseException as exc:
            # Recover only durable evidence; mutable engine state may include failed saves.
            try:
                latest = store.get(e["id"])
                if latest is None:
                    raise RuntimeError("Saved experiment is unavailable.")
                latest.update(
                    status="interrupted" if isinstance(exc, asyncio.CancelledError) else "error",
                    phase="stopped",
                    completed_at=now(),
                    error=f"Experiment stopped: {type(exc).__name__}",
                )
                store.rebuild_incomplete_evidence(
                    latest, reason="Experiment stopped; required observations are incomplete."
                )
                store.save(latest)
            except Exception:
                storage_failure = {
                    "experiment_id": e["id"], "message": STORAGE_FAILURE_MESSAGE,
                }
        finally:
            tasks.pop(e["id"], None)
            cancelled.discard(e["id"])

    @app.post("/api/experiments", status_code=202)
    async def start(body: RunRequest):
        if body.mode == "live":
            try:
                authorization.check()
            except LiveBlocked as exc:
                raise HTTPException(403, str(exc)) from exc
            if live_config is None:
                raise HTTPException(403, "Live inference requires explicit server configuration.")
        async with lock:
            if storage_failure is not None:
                raise HTTPException(503, storage_failure["message"])
            if not body.baseline_prompt.strip():
                raise HTTPException(422, "Prompt must contain non-whitespace text.")
            dataset_id = body.dataset.get("dataset_id")
            if type(dataset_id) is not str or not 1 <= len(dataset_id) <= 100:
                raise HTTPException(422, "Dataset identity must be a bounded server-issued string.")
            dataset = store.dataset(dataset_id)
            if not dataset:
                raise HTTPException(
                    422, "Load or import a dataset first; server-held dataset identity is required."
                )
            if body.mode == "fixture" and not all(c.get("fixture_outputs") for c in dataset["cases"]):
                raise HTTPException(
                    422,
                    "Fixture simulation requires explicit scripted outputs for every case. Load the demo or the scripted JSON template. Uploaded examples are never assigned fabricated predictions.",
                )
            if tasks:
                raise HTTPException(
                    409, "An experiment is already active. Wait or cancel it first."
                )
            e = {
                "id": str(uuid4()),
                "created_at": now(),
                "status": "queued",
                "phase": "queued",
                "execution_kind": "Live inference" if body.mode == "live" else "Fixture simulation",
                "scenario": "live" if body.mode == "live" else body.scenario,
                "baseline_prompt": body.baseline_prompt,
                "dataset": dataset,
                "model": {
                    "target": "fixture-target-v1",
                    "repair": "fixture-repair-v1",
                    "settings": {"temperature": 0, "max_output_tokens": 512},
                },
                "observations": [],
                "proposals": [],
                "events": [],
                "usage": {"live_calls": 0, "tokens": "not applicable", "cost": "not applicable"},
            }
            if body.mode == "live":
                e["model"] = live_config.model_metadata()
                e["model"]["settings"].update(per_call_timeout_seconds=60, total_timeout_seconds=1800)
                e["authorization"] = {
                    "access_confirmed": True, "cap_confirmed": True,
                    "cap_usd": str(authorization.cap_usd),
                    "cap_scope": "Cumulative sibling provider-usage.sqlite3 ledger; credits and cash",
                }
                e["provider_receipts"] = []
                e["usage"] = {"live_calls": 0, "tokens": 0, "cost": "0"}
                e["usage_at_start"] = ledger.summary()
            e["configuration_hash"] = digest(e["model"])
            e["baseline_prompt_hash"] = digest(body.baseline_prompt)
            store.create_experiment(e)
            tasks[e["id"]] = asyncio.create_task(execute(e))
            return e

    @app.get("/api/experiments/{experiment_id}")
    async def detail(experiment_id: str):
        return require_experiment(experiment_id)

    @app.post("/api/experiments/{experiment_id}/cancel")
    async def cancel(experiment_id: str):
        e = require_experiment(experiment_id)
        request_cancellation(experiment_id)
        return e

    @app.get("/api/experiments/{experiment_id}/export/{kind}")
    async def export(experiment_id: str, kind: str, candidate_id: str | None = None):
        e = require_experiment(experiment_id)
        if kind == "json":
            content, media, extension = (
                json.dumps(e, indent=2, ensure_ascii=False, allow_nan=False),
                "application/json",
                "json",
            )
        elif kind == "markdown":
            content, media, extension = markdown(e), "text/markdown", "md"
        elif kind == "prompt":
            p = proposal(e, candidate_id)
            if not p:
                raise HTTPException(404, "No proposed prompt exists for that selection.")
            content, media, extension = (
                (
                    "Live inference — proposed prompt; human adoption decision required.\n\n"
                    if e["execution_kind"] == "Live inference"
                    else "Fixture simulation — scripted evidence; not live inference.\n\n"
                ) + p["prompt"],
                "text/plain",
                "txt",
            )
        else:
            raise HTTPException(404, "Export format not found.")
        return Response(
            content,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="patchproof-{experiment_id}.{extension}"'
            },
        )

    dist = APP_ROOT / "frontend/dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
