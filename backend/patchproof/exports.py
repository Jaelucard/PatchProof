"""Evidence exports are rendered exclusively from saved snapshots."""

from __future__ import annotations

import difflib
import json
import re


def fenced(value, language="json"):
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    runs = re.findall(r"`+", text)
    fence = "`" * max(3, max((len(run) + 1 for run in runs), default=3))
    return f"{fence}{language}\n{text}\n{fence}"


def proposal(experiment: dict, candidate_id: str | None = None):
    chosen = candidate_id or experiment.get("selected_candidate_id")
    return next((p for p in experiment.get("proposals", []) if p["id"] == chosen), None)


def markdown(experiment: dict):
    e = experiment
    dataset = e["dataset"]
    live = e["execution_kind"] == "Live inference"
    authorization = e.get("authorization", {})
    lines = [
        "# PatchProof experiment",
        "",
        f"**{e['execution_kind']}**",
        "",
        f"Experiment: {e['id']}",
        f"Created: {e['created_at']}",
        f"Completed: {e.get('completed_at', 'Not completed')}",
        f"State: {e['status']}; phase: {e['phase']}",
        f"Verdict: {e.get('verdict', 'inconclusive')}",
        "",
        (
            "This run was configured for Nebius live inference. Saved receipts establish whether requests were attempted and responses completed; configuration alone does not establish provider execution, a successful repair or approved labels."
            if live else
            "This fixture evidence demonstrates application checks. Scripted responses are independent of prompt edits and are not live inference or proof of a successful prompt repair."
        ),
        "",
        "## Provenance",
        "Dataset name:",
        fenced(dataset["name"], "text"),
        f"Label review: {dataset['review_status']}; human review pending: {dataset['human_review_pending']}",
        f"Prior assessment exposure: {e.get('prior_exposure', False)} (conservative: previous accepted runs with overlapping tests)",
        f"Live provider access confirmation: {authorization.get('access_confirmed', 'pending')}",
        f"Total spending/credit-use cap confirmation: {authorization.get('cap_confirmed', 'pending')}",
        f"Live provider calls: {e['usage']['live_calls']}",
        f"Approved cumulative inference cap (USD): {authorization.get('cap_usd', 'not applicable')}",
        f"Dataset version: {dataset['version_hash']}",
        f"Manifest hash: {dataset['manifest_hash']}",
        f"Contract: {dataset['contract_version']}",
        f"Evaluator: {dataset['evaluator_version']}",
        f"Configuration hash: {e.get('configuration_hash', 'unknown')}",
        f"Frozen candidate hash: {e.get('frozen_candidate_hash') or 'No candidate frozen'}",
        "",
        "## Interpretation",
    ]
    lines += [
        f"- {reason}" for reason in e.get("verdict_reasons", ["Required observations incomplete."])
    ]
    if e.get("error"):
        lines += ["", "Error:", fenced(e["error"], "text")]
    lines += [
        "",
        "## Assessments",
        fenced(e.get("assessments", {})),
        "",
        "## Counts",
        "Case categories and individual check changes are separate evidence.",
        fenced(e.get("summary", {})),
        "",
        "## Model and usage",
        fenced(e["model"]),
        fenced(e["usage"]),
        "",
        "## Provider request receipts",
        "Costs are conservative local estimates from recorded token usage, not a provider invoice. Unknown requests retain their reservation. A reserved request is not proof that the provider received it.",
        fenced(e.get("provider_receipts", [])),
        "",
        "## Diagnosis (development only)",
        fenced(e.get("diagnosis", [])),
        "",
        "## Original prompt",
        fenced(e["baseline_prompt"], "text"),
        "",
        "## Proposals",
    ]
    for p in e.get("proposals", []):
        lines += [
            "",
            f"### {p['id']} ({p.get('status', 'unknown')})",
            f"Prompt hash: {p['prompt_hash']}",
            fenced(p["prompt"], "text"),
            "Development evidence:",
            fenced(p.get("development", {})),
            "Prompt diff:",
            fenced(
                "\n".join(
                    difflib.unified_diff(
                        e["baseline_prompt"].split("\n"),
                        p["prompt"].split("\n"),
                        fromfile="original",
                        tofile=p["id"],
                        lineterm="",
                    )
                ),
                "diff",
            ),
            "Saved proposal comparisons:",
            fenced(p.get("comparisons", [])),
        ]
    lines += ["", "## Frozen split manifest", fenced(dataset["manifest"]), "", "## Ticket evidence"]
    for index, case in enumerate(dataset["cases"], start=1):
        lines += [
            "",
            f"### Ticket {index} / {case['partition']}",
            "Ticket ID:",
            fenced(case["id"], "text"),
            f"Stable test hash: {case['case_hash']}",
            "Input:",
            fenced(case["text"], "text"),
            "Expected:",
            fenced(case["expected"]),
        ]
        if case.get("annotation_note"):
            lines += ["Annotation note:", fenced(case["annotation_note"], "text")]
        observations = [o for o in e.get("observations", []) if o["case_id"] == case["id"]]
        if not observations:
            lines += ["Not run; no saved observations."]
        for observation in observations:
            lines += [
                f"Stage: {observation['stage']}; prompt hash: {observation['prompt_hash']}",
                fenced(observation["result"]),
            ]
    lines += [
        "",
        "## Selected candidate comparisons",
        fenced(e.get("comparisons", [])),
        "",
        "## Event log",
        fenced(e.get("events", [])),
        "",
    ]
    return "\n".join(lines)
