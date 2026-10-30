"""Bounded prompt-only experiments with development-only candidate selection."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from .domain import (
    CHECKS,
    CONTRACT_VERSION,
    EVALUATOR_VERSION,
    PARTITIONS,
    compare,
    digest,
    evaluate,
)

PER_CALL_TIMEOUT = 20
TOTAL_TIMEOUT = 240
MAX_PROMPT_CHARS = 30_000


class ExperimentCancelled(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def comparison_counts(comparisons: list[dict]) -> dict:
    counts = {
        key: sum(c["status"] == key for c in comparisons)
        for key in ("fixed", "regressed", "still_failing", "unchanged")
    }
    counts.update(
        {
            "improvements": sum(len(c["fixed"]) for c in comparisons),
            "regressions": sum(len(c["regressed"]) for c in comparisons),
            "baseline_passing_cases": sum(c["baseline"]["passed"] for c in comparisons),
            "candidate_passing_cases": sum(c["candidate"]["passed"] for c in comparisons),
            "baseline_passing_checks": sum(
                sum(c["baseline"]["checks"].values()) for c in comparisons
            ),
            "candidate_passing_checks": sum(
                sum(c["candidate"]["checks"].values()) for c in comparisons
            ),
            "observed_cases": len(comparisons),
            "total_checks": len(comparisons) * len(CHECKS),
        }
    )
    return counts


def refresh_proposal_development(proposal: dict, total_cases: int) -> None:
    """Rebuild proposal evidence from saved pairs without qualifying partial results."""
    pairs = proposal.get("comparisons", [])
    stats = comparison_counts([c for c in pairs if c["partition"] == "development"])
    complete = total_cases > 0 and stats["observed_cases"] == total_cases
    qualified = complete and stats["improvements"] > 0 and stats["regressions"] == 0
    proposal["development"] = {
        **stats,
        "passing_cases": stats["candidate_passing_cases"],
        "total_cases": total_cases,
        "complete": complete,
        "qualified": qualified,
    }
    if any(c["regressed"] for c in pairs):
        proposal["status"] = "rejected"
    elif not complete:
        proposal["status"] = "incomplete"
    elif not qualified:
        proposal["status"] = "not_improved"
    elif proposal.get("status") not in {"selected", "discarded", "assessed", "development_only"}:
        proposal["status"] = "development_qualified"


def _verdict(exp: dict) -> tuple[str, list[str]]:
    selected = next((p for p in exp["proposals"] if p["id"] == exp["selected_candidate_id"]), None)
    if selected and any(c["regressed"] for c in selected["comparisons"]):
        reasons = [
            "Selected proposal lost previously passing checks. Each lost check rejects this comparison."
        ]
        if exp["dataset"]["human_review_pending"]:
            reasons.append(
                "Failed check on provisional tests; expected answers await human review."
            )
        if exp["status"] != "completed":
            reasons.append(
                "Required observations are incomplete; observed regressions are preserved."
            )
        return "rejected", reasons
    reasons: list[str] = []
    if selected is None:
        reasons.append(
            "No development-qualified candidate: a proposal must improve at least one check without losing any previously passing check."
        )
    if exp["status"] != "completed" or any(
        exp["assessments"][p]["status"] not in {"passed", "failed"} for p in PARTITIONS
    ):
        reasons.append("Required observations are missing, failed or interrupted.")
    if not exp["dataset"]["full_experiment_eligible"]:
        reasons.append(
            "Insufficient independent assessment cases: at least 40 total, 10 regression and 10 final cases are required."
        )
    regression = exp["assessments"]["regression"]
    if regression.get("baseline_passing_cases", 0) == 0:
        reasons.append(
            "No fully passing baseline case in the regression partition; regression coverage is insufficient."
        )
    if exp["assessments"]["final"].get("improvements", 0) < 1:
        reasons.append("Final assessment did not demonstrate an improvement.")
    if exp["dataset"]["human_review_pending"] or exp["dataset"]["review_status"] != "user_attested":
        reasons.append("Expected answers await human review.")
    if exp.get("prior_exposure"):
        reasons.append(
            "Final assessment was reused; this run cannot establish fresh independent evidence."
        )
    if exp["execution_kind"] != "Live inference":
        reasons.append(
            "Fixture simulation: scripted outputs demonstrate the checks, not measured model improvement."
        )
    return (
        ("inconclusive", reasons)
        if reasons
        else (
            "eligible_for_human_review",
            [
                "Complete reviewed, fresh observations show development and final improvements with zero lost checks. A developer must decide whether to adopt the prompt."
            ],
        )
    )


async def run_experiment(
    experiment: dict, provider: Any, save: Callable, cancelled: Callable,
    *, per_call_timeout: float | None = None, total_timeout: float | None = None,
) -> dict:
    """Run at most two revisions; save every observation before later operations.

    Provider inputs are isolated copies. A repair request contains only development
    inputs/answers/results; independent cases are not touched until candidate freeze.
    """
    exp = experiment
    call_deadline = PER_CALL_TIMEOUT if per_call_timeout is None else per_call_timeout
    run_deadline = TOTAL_TIMEOUT if total_timeout is None else total_timeout
    exp.setdefault("observations", [])
    exp.setdefault("proposals", [])
    exp.setdefault("events", [])
    exp.setdefault("errors", [])
    exp.update(
        {
            "status": "running",
            "started_at": _now(),
            "selected_candidate_id": None,
            "frozen_candidate_hash": None,
            "comparisons": [],
            "diagnosis": [],
            "assessments": {
                p: {"status": "not_run", "reason": "Candidate has not been frozen."}
                for p in PARTITIONS
            },
            "summary": {key: 0 for key in ("fixed", "regressed", "still_failing", "unchanged")},
            "verdict": "inconclusive",
            "verdict_reasons": ["Experiment is incomplete."],
        }
    )
    dataset = deepcopy(exp["dataset"])
    exp["dataset"] = deepcopy(dataset)
    frozen_data = digest(dataset)
    model = deepcopy(exp.get("model", {}))
    exp["contract_version"] = CONTRACT_VERSION
    exp["evaluator_version"] = EVALUATOR_VERSION
    exp["baseline_prompt_hash"] = digest(exp["baseline_prompt"])
    exp["configuration_hash"] = digest(model)
    baseline_prompt = exp["baseline_prompt"]
    rows: dict[tuple[str, str], dict] = {}
    phase = "validation"
    current_case: str | None = None
    current_stage: str | None = None

    async def persist() -> None:
        if digest(exp["dataset"]) != frozen_data or exp.get("model", {}) != model:
            raise ValueError("Frozen dataset or model configuration changed during the experiment.")
        exp["summary"] = comparison_counts(exp["comparisons"])
        await save(deepcopy(exp))

    def check_cancel() -> None:
        if cancelled():
            raise ExperimentCancelled("Cancellation requested.")

    async def event(name: str, **details: Any) -> None:
        exp["events"].append({"event": name, "timestamp": _now(), **details})
        await persist()

    async def set_phase(name: str, total: int = 0) -> None:
        nonlocal phase
        phase = name
        exp["phase"] = name
        exp["progress"] = {"completed": 0, "total": total}
        check_cancel()
        await event("phase_started", phase=name)

    async def predict(case: dict, stage: str, prompt: str) -> dict:
        nonlocal current_case, current_stage
        check_cancel()
        current_case, current_stage = case["id"], stage
        raw = await asyncio.wait_for(
            provider.predict(prompt, deepcopy(case), stage), timeout=call_deadline
        )
        if type(raw) is not str:
            raise ValueError("Provider prediction must be a raw response string.")
        result = evaluate(raw, case["expected"])
        observation = {
            "case_id": case["id"],
            "case_hash": case["case_hash"],
            "partition": case["partition"],
            "stage": stage,
            "prompt_hash": digest(prompt),
            "recorded_at": _now(),
            "result": result,
        }
        rows[(case["id"], stage)] = result
        exp["observations"].append(observation)
        exp["progress"]["completed"] += 1
        await persist()
        return result

    def comparison(case: dict, candidate_id: str) -> dict:
        original, candidate = rows[(case["id"], "baseline")], rows[(case["id"], candidate_id)]
        return {
            "case_id": case["id"],
            "case_hash": case["case_hash"],
            "partition": case["partition"],
            "candidate_id": candidate_id,
            "baseline": original,
            "candidate": candidate,
            **compare(original, candidate),
        }

    async def independent(partition: str, proposal: dict) -> bool:
        cases = [c for c in dataset["cases"] if c["partition"] == partition]
        if not cases:
            exp["assessments"][partition] = {
                "status": "not_run",
                "reason": "Not run: no cases assigned to this independent partition.",
                "total_cases": 0,
            }
            await event("assessment_not_run", partition=partition, reason="No assigned cases.")
            return False
        assessment = exp["assessments"][partition] = {
            "status": "running",
            "total_cases": len(cases),
        }
        await set_phase(partition + "_assessment", len(cases) * 2)
        observed = []
        for case in cases:
            await predict(case, "baseline", baseline_prompt)
            await predict(case, proposal["id"], proposal["prompt"])
            pair = comparison(case, proposal["id"])
            observed.append(pair)
            proposal["comparisons"].append(pair)
            exp["comparisons"].append(pair)
            assessment.update(comparison_counts(observed))
            # Persist the comparison before making the next independent call.
            await persist()
        assessment.update(comparison_counts(observed))
        assessment["status"] = "failed" if assessment["regressions"] else "passed"
        assessment["reason"] = (
            "Previously passing checks were lost."
            if assessment["regressions"]
            else "No previously passing checks were lost."
        )
        await event("assessment_finished", partition=partition, status=assessment["status"])
        return assessment["regressions"] == 0

    async def execute() -> None:
        nonlocal current_case, current_stage
        if (
            type(baseline_prompt) is not str
            or not baseline_prompt.strip()
            or len(baseline_prompt) > MAX_PROMPT_CHARS
        ):
            raise ValueError(f"Baseline prompt must contain 1–{MAX_PROMPT_CHARS} characters.")
        if not dataset["cases"]:
            raise ValueError("Dataset has no cases.")
        if any(c.get("partition") not in PARTITIONS for c in dataset["cases"]):
            raise ValueError("Every case needs an immutable saved partition.")
        development = [c for c in dataset["cases"] if c["partition"] == "development"]
        if not development:
            raise ValueError("No development cases are available.")
        await event(
            "experiment_frozen",
            dataset_hash=dataset["version_hash"],
            manifest_hash=dataset["manifest_hash"],
            contract_version=CONTRACT_VERSION,
            evaluator_version=EVALUATOR_VERSION,
            configuration_hash=exp["configuration_hash"],
        )
        exp["assessments"]["development"] = {"status": "running", "total_cases": len(development)}
        await set_phase("baseline_development", len(development))
        for case in development:
            await predict(case, "baseline", baseline_prompt)
        failures = {
            key: sum(not rows[(c["id"], "baseline")]["checks"][key] for c in development)
            for key in CHECKS
        }
        exp["diagnosis"] = [
            {
                "check": key,
                "failing_cases": count,
                "kind": "deterministic_failure_category",
                "explanation": f"{count} development responses failed {key}. This category is a repair hypothesis, not a causal model explanation.",
            }
            for key, count in failures.items()
            if count
        ]
        # Deliberately construct a fresh allowlisted development payload.
        payload = [
            {
                "id": c["id"],
                "text": c["text"],
                "expected": deepcopy(c["expected"]),
                "baseline": deepcopy(rows[(c["id"], "baseline")]),
            }
            for c in development
        ]
        previous: list[dict] = []
        for number in (1, 2):
            candidate_id = f"candidate_{number}"
            current_case, current_stage = None, candidate_id
            await set_phase("propose_" + candidate_id)
            prompt = await asyncio.wait_for(
                provider.revise(baseline_prompt, deepcopy(payload), deepcopy(previous), number),
                timeout=call_deadline,
            )
            if type(prompt) is not str or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
                raise ValueError(
                    f"Revision {number} must be a prompt string containing 1–{MAX_PROMPT_CHARS} characters."
                )
            proposal = {
                "id": candidate_id,
                "prompt": prompt,
                "prompt_hash": digest(prompt),
                "created_at": _now(),
                "status": "evaluating",
                "comparisons": [],
                "development": {
                    "qualified": False,
                    "improvements": 0,
                    "regressions": 0,
                    "passing_cases": 0,
                },
            }
            exp["proposals"].append(proposal)
            await event(
                "proposal_saved", candidate_id=candidate_id, prompt_hash=proposal["prompt_hash"]
            )
            await set_phase(candidate_id + "_development", len(development))
            for case in development:
                await predict(case, candidate_id, prompt)
                proposal["comparisons"].append(comparison(case, candidate_id))
                await persist()
            refresh_proposal_development(proposal, len(development))
            previous.append(
                {
                    "id": candidate_id,
                    "prompt": prompt,
                    "development": [
                        {"id": c["id"], "result": deepcopy(rows[(c["id"], candidate_id)])}
                        for c in development
                    ],
                }
            )
            await event(
                "development_proposal_finished",
                candidate_id=candidate_id,
                qualified=proposal["development"]["qualified"],
            )
        exp["assessments"]["development"]["status"] = "passed"
        qualified = [p for p in exp["proposals"] if p["development"]["qualified"]]
        if not qualified:
            exp["assessments"]["development"].update(
                {"status": "failed", "reason": "Neither proposal qualified on development checks."}
            )
            for part in ("regression", "final"):
                exp["assessments"][part] = {
                    "status": "not_run",
                    "reason": "No development-qualified candidate.",
                }
            return
        # Python max retains the earlier proposal when both keys tie.
        selected = max(
            qualified,
            key=lambda p: (p["development"]["improvements"], p["development"]["passing_cases"]),
        )
        exp["selected_candidate_id"] = selected["id"]
        exp["frozen_candidate_hash"] = selected["prompt_hash"]
        selected["status"] = "selected"
        for proposal in qualified:
            if proposal is not selected:
                proposal["status"] = "discarded"
        exp["comparisons"] = list(selected["comparisons"])
        exp["assessments"]["development"].update(selected["development"])
        await set_phase("candidate_frozen")
        await event(
            "candidate_frozen", candidate_id=selected["id"], prompt_hash=selected["prompt_hash"]
        )
        if not dataset["full_experiment_eligible"]:
            selected["status"] = "development_only"
            for part in ("regression", "final"):
                exp["assessments"][part] = {
                    "status": "not_run",
                    "reason": "Not run: dataset is below the full-experiment floor (40 total, at least 10 regression and 10 final cases).",
                }
            await event("assessments_not_run", reason="Dataset below full-experiment floor.")
            return
        if not await independent("regression", selected):
            selected["status"] = (
                "rejected"
                if exp["assessments"]["regression"]["status"] == "failed"
                else "development_only"
            )
            exp["assessments"]["final"] = {
                "status": "not_run",
                "reason": "Not run: regression check failed."
                if selected["status"] == "rejected"
                else "Not run: regression assessment was unavailable.",
            }
            return
        await independent("final", selected)
        if (
            selected["prompt_hash"] != digest(selected["prompt"])
            or selected["prompt_hash"] != exp["frozen_candidate_hash"]
        ):
            raise ValueError("Frozen candidate prompt changed during assessment.")
        if exp["assessments"]["final"]["regressions"]:
            selected["status"] = "rejected"
        else:
            selected["status"] = "assessed"

    try:
        await set_phase("validation")
        async with asyncio.timeout(run_deadline):
            await execute()
        check_cancel()
        exp["status"] = "completed"
    except (ExperimentCancelled, asyncio.CancelledError):
        exp["status"] = "cancelled"
        exp["error"] = "Experiment cancelled; saved observations remain available."
        exp["errors"].append(
            {
                "phase": phase,
                "case_id": current_case,
                "stage": current_stage,
                "type": "cancelled",
                "message": exp["error"],
                "timestamp": _now(),
            }
        )
    except Exception as exc:
        exp["status"] = "error"
        exp["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        exp["errors"].append(
            {
                "phase": phase,
                "case_id": current_case,
                "stage": current_stage,
                "type": type(exc).__name__,
                "message": str(exc)[:500],
                "timestamp": _now(),
            }
        )
    # Reconstruct every available pair even when cancellation interrupted the
    # bookkeeping immediately after an observation was durably saved.
    for proposal in exp["proposals"]:
        proposal["comparisons"] = [
            comparison(c, proposal["id"])
            for c in dataset["cases"]
            if (c["id"], "baseline") in rows and (c["id"], proposal["id"]) in rows
        ]
        refresh_proposal_development(
            proposal, sum(c["partition"] == "development" for c in dataset["cases"])
        )
    selected = next((p for p in exp["proposals"] if p["id"] == exp["selected_candidate_id"]), None)
    if selected:
        exp["comparisons"] = list(selected["comparisons"])
        for part in PARTITIONS:
            available = [c for c in exp["comparisons"] if c["partition"] == part]
            exp["assessments"][part].update(comparison_counts(available))
        if any(c["regressed"] for c in selected["comparisons"]):
            selected["status"] = "rejected"
    for part in PARTITIONS:
        if exp["assessments"][part]["status"] == "running":
            exp["assessments"][part].update(
                {
                    "status": "incomplete",
                    "reason": exp.get("error", "Required observations are unavailable."),
                }
            )
        elif exp["status"] != "completed" and exp["assessments"][part]["status"] == "not_run":
            exp["assessments"][part]["reason"] = (
                "Not run: experiment did not reach this assessment."
            )
    exp["phase"] = exp["status"]
    exp["completed_at"] = _now()
    exp["verdict"], exp["verdict_reasons"] = _verdict(exp)
    exp["events"].append(
        {
            "event": "experiment_finished",
            "timestamp": _now(),
            "status": exp["status"],
            "verdict": exp["verdict"],
        }
    )
    await persist()
    return exp
