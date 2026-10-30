"""Consequential contract and orchestration tests; all providers are local fakes."""

import asyncio
from copy import deepcopy
import json

import pytest

from patchproof import engine
from patchproof.domain import (
    CONTRACT_VERSION,
    EVALUATOR_VERSION,
    STARTER_PROMPT,
    ValidationError,
    build_dataset,
    compare,
    digest,
    evaluate,
    parse_import,
)

EXPECTED = {
    "order_id": "004812",
    "issue_type": "delivery_problem",
    "requested_action": "refund",
    "needs_review": False,
}


def raw(value):
    return json.dumps(value)


def examples(n=40):
    return [
        {
            "id": f"ticket-{i:03}",
            "text": f"Please refund order {i:05}. It arrived late.",
            "expected": {**EXPECTED, "order_id": f"{i:05}"},
        }
        for i in range(n)
    ]


def dataset(n=40, reviewed=True):
    return build_dataset("Unit-test local scripts", examples(n), reviewed=reviewed)


def experiment(data=None, kind="Fixture simulation", prior=False):
    return {
        "id": "test-exp",
        "created_at": "2026-10-21T03:05:00+08:00",
        "execution_kind": kind,
        "baseline_prompt": STARTER_PROMPT,
        "dataset": data or dataset(),
        "prior_exposure": prior,
        "model": {
            "target": "local-test-fake",
            "repair": "local-test-fake",
            "settings": {"temperature": 0},
        },
        "usage": {"live_calls": 0, "tokens": "not applicable", "cost": "not applicable"},
    }


class FakeProvider:
    def __init__(self, transform=None):
        self.calls = []
        self.repairs = []
        self.transform = transform

    async def predict(self, prompt, case, stage):
        self.calls.append((case["id"], case["partition"], stage, prompt))
        value = deepcopy(case["expected"])
        # Baseline has scripted failed actions, with ample fully passing
        # independent cases. This is a script, not an extraction implementation.
        if stage == "baseline" and case["id"].endswith(("0", "2", "5")):
            value["requested_action"] = None
        if self.transform:
            value = self.transform(case, stage, value)
        return raw(value)

    async def revise(self, baseline_prompt, development_payload, previous, number):
        self.repairs.append(deepcopy((development_payload, previous, number)))
        return (
            baseline_prompt
            + f"\nRevision {number}: preserve explicit facts and unresolved null fields."
        )


async def run(exp, provider, cancelled=lambda: False):
    saves = []

    async def save(snapshot):
        saves.append(deepcopy(snapshot))

    result = await engine.run_experiment(exp, provider, save, cancelled)
    return result, saves


@pytest.mark.parametrize(
    "field,value",
    [
        ("order_id", 4812),
        ("issue_type", "unknown"),
        ("requested_action", "cancel"),
        ("needs_review", "false"),
        ("needs_review", 0),
    ],
)
def test_schema_types_and_field_evidence(field, value):
    actual = {**EXPECTED, field: value}
    result = evaluate(raw(actual), EXPECTED)
    assert result["checks"]["json"] is True
    assert result["checks"]["schema"] is False
    assert result["checks"][field] is False
    for other in set(EXPECTED) - {field}:
        assert result["checks"][other] is True


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        "{} trailing",
        '{"order_id":"1","order_id":"2"}',
        '{"x":NaN}',
        '{"x":Infinity}',
        "```json\n{}\n```",
        "null",
        "[]",
    ],
)
def test_malformed_ambiguous_or_non_object_outputs_never_pass(response):
    result = evaluate(response, EXPECTED)
    assert result["passed"] is False
    assert result["checks"]["schema"] is False


def test_extra_key_fails_schema_but_retains_correct_fields():
    result = evaluate(raw({**EXPECTED, "approval": True}), EXPECTED)
    assert result["checks"]["json"] is True
    assert result["checks"]["schema"] is False
    assert all(result["checks"][field] for field in EXPECTED)


def test_null_uncertainty_and_clear_action_preserve_typed_facts():
    expected = {
        "order_id": "4812",
        "issue_type": "delivery_problem",
        "requested_action": None,
        "needs_review": True,
    }
    result = evaluate(raw(expected), expected)
    assert result["passed"]
    assert not evaluate(raw({**expected, "requested_action": "other"}), expected)["passed"]
    assert evaluate(raw(EXPECTED), EXPECTED)["parsed"]["order_id"] == "004812"


def test_lost_check_inside_already_failing_ticket_is_regression():
    baseline = evaluate(raw({**EXPECTED, "requested_action": None}), EXPECTED)
    candidate = evaluate(raw({**EXPECTED, "order_id": "4812"}), EXPECTED)
    result = compare(baseline, candidate)
    assert result == {
        "fixed": ["requested_action"],
        "regressed": ["order_id"],
        "status": "regressed",
    }
    assert not baseline["passed"] and not candidate["passed"]


def test_prompt_is_separate_from_test_identity_and_expected_is_integrity_input():
    data = dataset()
    again = dataset()
    assert data["cases"][0]["case_hash"] == again["cases"][0]["case_hash"]
    assert digest("prompt A") != digest("prompt B")
    changed = examples()
    changed[0]["expected"]["requested_action"] = "status_update"
    assert (
        build_dataset("Unit-test local scripts", changed, reviewed=True)["cases"][0]["case_hash"]
        != data["cases"][0]["case_hash"]
    )
    assert data["contract_version"] == CONTRACT_VERSION
    assert data["evaluator_version"] == EVALUATOR_VERSION


def test_valid_json_import_and_review_attestation_not_file_status():
    content = {
        "name": "User examples",
        "cases": examples(),
        "review_status": "human_reviewed",
        "source": "demo",
    }
    data = parse_import(raw(content), "json")
    assert data["review_status"] == "draft" and data["human_review_pending"]
    assert data["source"] == "import"
    assert data["full_experiment_eligible"]
    assert parse_import(raw(content), "json", reviewed=True)["review_status"] == "user_attested"
    assert sorted(map(len, data["manifest"].values())) == [10, 10, 20]
    assert data["version_hash"] == parse_import(raw(content), "json")["version_hash"]


def test_csv_preserves_leading_zeros_original_text_and_nullable_cells():
    content = 'id,text,order_id,issue_type,requested_action,needs_review\r\nx,"  Where is order 0007?\nPlease check.  ",0007,delivery_problem,status_update,false\r\ny,"General opening hours?",,other,other,false\r\n'
    data = parse_import(content, "csv", True)
    assert data["cases"][0]["expected"]["order_id"] == "0007"
    assert data["cases"][0]["text"] == "  Where is order 0007?\nPlease check.  "
    assert data["cases"][1]["expected"]["order_id"] is None
    assert not data["full_experiment_eligible"]


@pytest.mark.parametrize(
    "change",
    [
        lambda cs: cs.append(deepcopy(cs[0])),
        lambda cs: cs[1].update(id=cs[0]["id"]),
        lambda cs: cs[1].update(text="  " + cs[0]["text"].upper() + "\n"),
        lambda cs: cs[0]["expected"].update(needs_review="false"),
        lambda cs: cs[0]["expected"].update(order_id=123),
        lambda cs: cs[0]["expected"].update(extra="x"),
    ],
)
def test_bad_imports_reject_with_actionable_errors(change):
    cases = examples()
    change(cases)
    with pytest.raises(ValidationError) as error:
        parse_import(raw({"name": "Bad", "cases": cases}), "json")
    assert error.value.errors and "Case/row" in error.value.errors[0]


@pytest.mark.parametrize(
    "content", ['{"name":"x","name":"y","cases":[]}', '{"name":"x","cases":NaN}', "[]", "{"]
)
def test_invalid_json_imports(content):
    with pytest.raises(ValidationError):
        parse_import(content, "json")


@pytest.mark.parametrize(
    "content",
    [
        "id,text,order_id,issue_type,requested_action,needs_review\na,b,,,,False",
        "id,text,order_id,issue_type,requested_action,needs_review\na,b,,,,false,extra",
        "id,text,order_id,issue_type,requested_action,needs_review\na,b,,,",
        "id,id,order_id,issue_type,requested_action,needs_review\na,b,,,,false",
    ],
)
def test_invalid_csv(content):
    with pytest.raises(ValidationError):
        parse_import(content, "csv")


def test_known_families_stay_together_and_file_partitions_ignored():
    cases = examples()
    for i, case in enumerate(cases):
        case["scenario_family"] = f"family-{i // 5}"
        case["partition"] = "final"
    data = parse_import(raw({"name": "Grouped", "cases": cases}), "json")
    for family in {c["scenario_family"] for c in data["cases"]}:
        assert len({c["partition"] for c in data["cases"] if c["scenario_family"] == family}) == 1
    assert data["full_experiment_eligible"]
    assert data["manifest"]["development"]
    cases = examples()
    for case in cases:
        case["scenario_family"] = "all-same-family"
    assert not build_dataset("Unsplittable", cases)["full_experiment_eligible"]


@pytest.mark.asyncio
async def test_complete_fixture_has_frozen_pairing_and_explicit_inconclusive_verdict():
    provider = FakeProvider()
    result, snapshots = await run(experiment(), provider)
    assert result["status"] == "completed"
    assert result["verdict"] == "inconclusive"
    assert any("Fixture simulation" in text for text in result["verdict_reasons"])
    assert result["selected_candidate_id"] == "candidate_1"  # equal development gains, earlier wins
    assert result["frozen_candidate_hash"] == result["proposals"][0]["prompt_hash"]
    assert len(result["comparisons"]) == 40
    assert all(c["case_hash"] for c in result["comparisons"])
    assert len(provider.repairs) == 2
    frozen = next(
        i
        for i, s in enumerate(snapshots)
        if any(e["event"] == "candidate_frozen" for e in s["events"])
    )
    first_independent = next(
        i
        for i, s in enumerate(snapshots)
        if any(o["partition"] != "development" for o in s["observations"])
    )
    assert frozen < first_independent
    assert all(p["prompt_hash"] != result["baseline_prompt_hash"] for p in result["proposals"])


@pytest.mark.asyncio
async def test_repair_payload_contains_development_only_and_mutation_is_isolated():
    original = dataset()
    dev_ids = set(original["manifest"]["development"])

    class Mutating(FakeProvider):
        async def revise(self, baseline_prompt, development_payload, previous, number):
            assert {c["id"] for c in development_payload} == dev_ids
            assert all(
                set(c) == {"id", "text", "expected", "baseline"} for c in development_payload
            )
            for p in previous:
                assert {c["id"] for c in p["development"]} == dev_ids
            prompt = await super().revise(baseline_prompt, development_payload, previous, number)
            development_payload[0]["expected"]["order_id"] = "malicious mutation"
            if previous:
                previous[0]["development"].clear()
            return prompt

        async def predict(self, prompt, case, stage):
            response = await super().predict(prompt, case, stage)
            case["expected"]["needs_review"] = "mutated"
            case["partition"] = "final"
            return response

    exp = experiment(deepcopy(original))
    result, _ = await run(exp, Mutating())
    assert result["dataset"] == original
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_discarded_first_regression_does_not_reject_qualifying_second():
    def transform(case, stage, value):
        if stage == "candidate_1" and case["partition"] == "development":
            value["order_id"] = "wrong"
        return value

    result, _ = await run(experiment(), FakeProvider(transform))
    assert result["proposals"][0]["status"] == "rejected"
    assert result["selected_candidate_id"] == "candidate_2"
    assert result["verdict"] == "inconclusive"
    assert result["summary"]["regressed"] == 0


@pytest.mark.asyncio
async def test_selection_prioritizes_development_gain_not_independent_results():
    def transform(case, stage, value):
        if stage == "candidate_1" and case["id"].endswith("5"):
            value["requested_action"] = None
        if stage == "candidate_2" and case["partition"] == "regression":
            value["order_id"] = "bad"
        return value

    result, _ = await run(experiment(), FakeProvider(transform))
    assert result["selected_candidate_id"] == "candidate_2"
    assert result["verdict"] == "rejected"
    assert result["assessments"]["final"]["status"] == "not_run"


@pytest.mark.asyncio
async def test_independent_regression_stops_final_and_never_attempts_another_repair():
    def transform(case, stage, value):
        if stage != "baseline" and case["partition"] == "regression":
            value["order_id"] = "lost"
        return value

    provider = FakeProvider(transform)
    result, _ = await run(experiment(dataset(reviewed=False)), provider)
    assert result["verdict"] == "rejected"
    assert result["assessments"]["final"]["status"] == "not_run"
    assert "regression check failed" in result["assessments"]["final"]["reason"]
    assert not any(partition == "final" for _, partition, _, _ in provider.calls)
    assert len(provider.repairs) == 2
    assert any("provisional" in reason for reason in result["verdict_reasons"])


@pytest.mark.asyncio
async def test_no_qualified_candidate_is_inconclusive_and_retains_both():
    def transform(case, stage, value):
        if stage != "baseline" and case["id"].endswith(("0", "2", "5")):
            value["requested_action"] = None
        return value

    provider = FakeProvider(transform)
    result, _ = await run(experiment(), provider)
    assert result["verdict"] == "inconclusive"
    assert result["selected_candidate_id"] is None
    assert len(result["proposals"]) == 2
    assert not any(partition != "development" for _, partition, _, _ in provider.calls)
    assert result["comparisons"] == []
    assert all(p["comparisons"] for p in result["proposals"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,reason",
    [
        ("provisional", "await human review"),
        ("reused", "reused"),
        ("undersized", "at least 40"),
        ("no_coverage", "No fully passing baseline"),
        ("no_final_gain", "did not demonstrate"),
    ],
)
async def test_inconclusive_conditions_precede_positive_eligibility(change, reason):
    data = dataset(20 if change == "undersized" else 40, reviewed=change != "provisional")

    def transform(case, stage, value):
        if change == "no_coverage" and stage == "baseline" and case["partition"] == "regression":
            value["requested_action"] = None
        if (
            change == "no_final_gain"
            and stage != "baseline"
            and case["partition"] == "final"
            and case["id"].endswith(("0", "2", "5"))
        ):
            value["requested_action"] = None
        return value

    # The kind is set to live only to exercise the verdict truth table with
    # local fakes. This unit test makes zero network calls.
    result, _ = await run(
        experiment(data, kind="Live inference", prior=change == "reused"), FakeProvider(transform)
    )
    assert result["verdict"] == "inconclusive"
    assert any(reason in text for text in result["verdict_reasons"])


@pytest.mark.asyncio
async def test_complete_verdict_truth_table_eligible_requires_all_conditions():
    result, _ = await run(experiment(kind="Live inference"), FakeProvider())
    assert result["verdict"] == "eligible_for_human_review"
    assert all(
        result["assessments"][p]["status"] == "passed"
        for p in ("development", "regression", "final")
    )
    assert result["usage"]["live_calls"] == 0  # local fake, no actual live inference


@pytest.mark.asyncio
async def test_provider_error_preserves_completed_data_and_prompt():
    class Failing(FakeProvider):
        async def predict(self, prompt, case, stage):
            if stage == "candidate_2":
                raise RuntimeError("scripted provider failure")
            return await super().predict(prompt, case, stage)

    result, snapshots = await run(experiment(), Failing())
    assert result["status"] == "error" and result["verdict"] == "inconclusive"
    assert len(result["observations"]) == 40  # baseline + first candidate development
    assert len(result["proposals"]) == 2
    assert result["proposals"][1]["prompt"]
    assert "scripted provider failure" in result["error"]
    assert snapshots[-1]["observations"] == result["observations"]


@pytest.mark.asyncio
async def test_observed_regression_survives_later_error_and_incompleteness():
    class FailingAfterLoss(FakeProvider):
        def __init__(self):
            super().__init__()
            self.independent = 0

        async def predict(self, prompt, case, stage):
            if case["partition"] == "regression" and stage != "baseline":
                self.independent += 1
                if self.independent == 2:
                    raise RuntimeError("failed after observed regression")
                return raw({**case["expected"], "order_id": "lost"})
            return await super().predict(prompt, case, stage)

    result, _ = await run(experiment(), FailingAfterLoss())
    assert result["status"] == "error"
    assert result["verdict"] == "rejected"
    assert result["assessments"]["regression"]["status"] == "incomplete"
    assert result["summary"]["regressed"] >= 1
    assert result["assessments"]["final"]["status"] == "not_run"


@pytest.mark.asyncio
async def test_cancel_preserves_observations_and_no_qualified_success():
    state = {"cancelled": False}

    class Cancelling(FakeProvider):
        async def predict(self, prompt, case, stage):
            value = await super().predict(prompt, case, stage)
            state["cancelled"] = True
            return value

    result, _ = await run(experiment(), Cancelling(), lambda: state["cancelled"])
    assert result["status"] == "cancelled"
    assert result["verdict"] == "inconclusive"
    assert len(result["observations"]) == 1


@pytest.mark.asyncio
async def test_cancel_after_independent_loss_keeps_rejected_verdict():
    state = {"cancelled": False}

    class CancellingAfterLoss(FakeProvider):
        async def predict(self, prompt, case, stage):
            if case["partition"] == "regression" and stage != "baseline":
                state["cancelled"] = True
                return raw({**case["expected"], "order_id": "lost"})
            return await super().predict(prompt, case, stage)

    result, _ = await run(experiment(), CancellingAfterLoss(), lambda: state["cancelled"])
    assert result["status"] == "cancelled"
    assert result["verdict"] == "rejected"
    assert result["summary"]["regressed"] == 1


@pytest.mark.asyncio
async def test_timeout_is_bounded_and_inconclusive(monkeypatch):
    monkeypatch.setattr(engine, "PER_CALL_TIMEOUT", 0.001)

    class Slow(FakeProvider):
        async def predict(self, prompt, case, stage):
            await asyncio.sleep(0.02)
            return raw(case["expected"])

    result, _ = await run(experiment(), Slow())
    assert result["status"] == "error"
    assert "TimeoutError" in result["error"]
    assert result["verdict"] == "inconclusive"


@pytest.mark.asyncio
async def test_non_string_prediction_and_revision_are_errors():
    class Malformed(FakeProvider):
        async def predict(self, prompt, case, stage):
            return {"not": "text"}

    result, _ = await run(experiment(), Malformed())
    assert result["status"] == "error" and not result["observations"]

    class BadRevision(FakeProvider):
        async def revise(self, baseline_prompt, development_payload, previous, number):
            return {"prompt": "bad shape"}

    result, _ = await run(experiment(), BadRevision())
    assert result["status"] == "error" and not result["proposals"]
    assert result["observations"]


@pytest.mark.parametrize("response", ["1e999", '{"unknown":1e999}', '{"nested":{"x":-1e999}}'])
def test_nonfinite_float_overflow_rejected_before_evidence_serialization(response):
    result = evaluate(response, EXPECTED)
    assert result["checks"]["json"] is False
    assert result["parsed"] is None
    json.dumps(result, allow_nan=False)


def test_unresolved_import_labels_are_a_blocker():
    cases = examples()
    cases[0]["label_status"] = "unresolved"
    with pytest.raises(ValidationError, match="unresolved/disputed"):
        build_dataset("Disputed", cases)


def test_escaped_unpaired_surrogate_cannot_break_persisted_evidence():
    response = '{"unknown":"\\ud800"}'
    result = evaluate(response, EXPECTED)
    assert result["checks"]["json"] is False
    json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
    with pytest.raises(ValidationError):
        parse_import('{"name":"\\ud800","cases":[]}', "json")


def test_trusted_demo_defaults_to_draft():
    cases = examples(4)
    for c in cases:
        c["partition"] = "development"
    assert (
        build_dataset("Demo", cases, source="demo", trusted_partitions=True)["review_status"]
        == "draft"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 20, 39])
async def test_undersized_scripted_data_runs_development_only_and_never_passes_empty_assessments(
    size,
):
    provider = FakeProvider()
    result, _ = await run(experiment(dataset(size)), provider)
    assert result["status"] == "completed"
    assert result["selected_candidate_id"] is not None
    assert result["verdict"] == "inconclusive"
    assert all(partition == "development" for _, partition, _, _ in provider.calls)
    assert result["assessments"]["regression"]["status"] == "not_run"
    assert result["assessments"]["final"]["status"] == "not_run"
    assert "floor" in result["assessments"]["final"]["reason"]
