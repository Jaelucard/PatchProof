"""Explicit local SQLite persistence. Never opens Eval Lab's database."""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

from .domain import compare, digest
from .engine import comparison_counts, refresh_proposal_development
from .sqlite_inspection import check_database_sidecars, inspect_database
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, path: Path):
        self.path = path.resolve()
        check_database_sidecars(self.path)
        self._validate_existing_database()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS exposure (version_hash TEXT PRIMARY KEY, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS case_exposure (case_hash TEXT PRIMARY KEY, count INTEGER NOT NULL);
            """)

    def _validate_existing_database(self):
        """Inspect existing SQLite files before changing journal mode or schema."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        expected = {
            "experiments": [("id", "TEXT", 0, 1), ("payload", "TEXT", 1, 0)],
            "datasets": [("id", "TEXT", 0, 1), ("payload", "TEXT", 1, 0)],
            "exposure": [("version_hash", "TEXT", 0, 1), ("count", "INTEGER", 1, 0)],
            "case_exposure": [("case_hash", "TEXT", 0, 1), ("count", "INTEGER", 1, 0)],
        }
        message = "Existing file is not a PatchProof database; choose a new, separate database path."
        try:
            with inspect_database(self.path) as db:
                objects = [
                    (kind, name)
                    for kind, name in db.execute("SELECT type,name FROM sqlite_master")
                    if not name.startswith("sqlite_")
                ]
                if not objects:
                    return
                if set(objects) != {("table", name) for name in expected}:
                    raise ValueError(message)
                for name, signature in expected.items():
                    columns = [
                        (row[1], row[2].upper(), row[3], row[5])
                        for row in db.execute(f"PRAGMA table_info({name})")
                    ]
                    if columns != signature:
                        raise ValueError(message)
        except (OSError, sqlite3.Error) as exc:
            raise ValueError(message) from exc

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def save(self, experiment: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO experiments VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (experiment["id"], json.dumps(experiment, ensure_ascii=False, allow_nan=False)),
            )

    def create_experiment(self, experiment: dict):
        """Commit the initial run and its conservative exposure reservation together."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior_exposure = self._expose(db, experiment["dataset"])
            snapshot = {**experiment, "prior_exposure": prior_exposure}
            db.execute(
                "INSERT INTO experiments VALUES (?,?)",
                (experiment["id"], json.dumps(snapshot, ensure_ascii=False, allow_nan=False)),
            )
        experiment["prior_exposure"] = prior_exposure

    def get(self, experiment_id: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM experiments WHERE id=?", (experiment_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def all(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM experiments ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def register_dataset(self, dataset: dict):
        result = json.loads(json.dumps(dataset))
        result["dataset_id"] = str(uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO datasets VALUES (?,?)",
                (result["dataset_id"], json.dumps(result, ensure_ascii=False)),
            )
        return result

    def dataset(self, dataset_id: str):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def expose(self, dataset: dict):
        """Conservative overlap tracking, independent of scripts, labels' review or split changes."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._expose(db, dataset)

    def _expose(self, db, dataset: dict):
        reused = False
        for case in dataset["cases"]:
            exposure_hash = digest(
                {
                    "normalized_input": " ".join(
                        unicodedata.normalize("NFC", case["text"]).casefold().split()
                    )
                }
            )
            row = db.execute(
                "SELECT count FROM case_exposure WHERE case_hash=?", (exposure_hash,)
            ).fetchone()
            reused = reused or bool(row)
            db.execute(
                "INSERT INTO case_exposure VALUES (?,1) ON CONFLICT(case_hash) DO UPDATE SET count=count+1",
                (exposure_hash,),
            )
        return reused

    @staticmethod
    def rebuild_incomplete_evidence(experiment: dict, *, reason: str) -> None:
        """Rebuild derived evidence in a durable snapshot without I/O or raw-data changes."""
        # A stop can occur after a raw observation save, before pair bookkeeping.
        observations = {
            (o["case_id"], o["stage"]): o for o in experiment.get("observations", [])
        }
        cases = {c["id"]: c for c in experiment.get("dataset", {}).get("cases", [])}
        if "selected_candidate_id" in experiment:
            # Only a selected proposal can determine a modern experiment's verdict.
            experiment["comparisons"] = []
        for proposal in experiment.get("proposals", []):
            pairs = []
            for case_id, case in cases.items():
                baseline = observations.get((case_id, "baseline"))
                candidate = observations.get((case_id, proposal["id"]))
                if not baseline or not candidate:
                    continue
                pairs.append(
                    {
                        "case_id": case_id,
                        "case_hash": case["case_hash"],
                        "partition": case["partition"],
                        "candidate_id": proposal["id"],
                        "baseline": baseline["result"],
                        "candidate": candidate["result"],
                        **compare(baseline["result"], candidate["result"]),
                    }
                )
            proposal["comparisons"] = pairs
            refresh_proposal_development(
                proposal, sum(c["partition"] == "development" for c in cases.values())
            )
            if proposal["id"] == experiment.get("selected_candidate_id"):
                experiment["comparisons"] = pairs
        comparisons = experiment.get("comparisons", [])
        if all("baseline" in c and "candidate" in c for c in comparisons):
            experiment["summary"] = comparison_counts(comparisons)
            for partition, assessment in experiment.get("assessments", {}).items():
                assessment.update(
                    comparison_counts([c for c in comparisons if c["partition"] == partition])
                )
        else:
            # Preserve compatibility with older partial snapshots without selection metadata.
            experiment["summary"] = {
                key: sum(
                    c.get("status", "regressed" if c.get("regressed") else "unchanged") == key
                    for c in comparisons
                )
                for key in ("fixed", "regressed", "still_failing", "unchanged")
            }
        rejected = any(c.get("regressed") for c in comparisons)
        experiment["verdict"] = "rejected" if rejected else "inconclusive"
        reasons = [reason]
        if rejected:
            reasons.insert(
                0,
                "Selected candidate lost previously passing checks; saved observations preserve the rejection.",
            )
        experiment["verdict_reasons"] = reasons
        for assessment in experiment.get("assessments", {}).values():
            if assessment.get("status") == "running":
                assessment.update(status="incomplete", reason=reason)

    def recover(self):
        for experiment in self.all():
            if experiment["status"] not in {"queued", "running"}:
                continue
            recovered_at = datetime.now(timezone.utc).isoformat()
            experiment.update(
                status="interrupted",
                phase="interrupted",
                completed_at=recovered_at,
                error="Server stopped before this experiment finished.",
            )
            self.rebuild_incomplete_evidence(
                experiment, reason="Interrupted run; required observations are incomplete."
            )
            experiment.setdefault("events", []).append(
                {"event": "interrupted_on_restart", "timestamp": recovered_at}
            )
            self.save(experiment)
