"""Saved observations govern partial proposal summaries after errors and restarts."""

from copy import deepcopy
import json

import pytest

from patchproof.domain import build_dataset
from patchproof.engine import run_experiment
from patchproof.store import Store


def make_experiment():
    cases = [
        {
            "id": f"ticket-{i:02}",
            "text": f"Refund order {i:05} because the item arrived damaged.",
            "expected": {
                "order_id": f"{i:05}", "issue_type": "damaged_item",
                "requested_action": "refund", "needs_review": False,
            },
            "partition": "development" if i < 20 else "regression" if i < 30 else "final",
        }
        for i in range(40)
    ]
    return {
        "id": "proposal-recovery", "baseline_prompt": "Extract all four fields.",
        "dataset": build_dataset("Recovery fixtures", cases, trusted_partitions=True),
        "model": {}, "execution_kind": "Fixture simulation",
    }


class ScriptedProvider:
    def __init__(self, *, loss=False, stop=None):
        self.loss, self.stop = loss, stop
        self.candidate_calls = 0
        self.cancelled = False

    async def predict(self, prompt, case, stage):
        result = deepcopy(case["expected"])
        if stage == "baseline":
            result["requested_action"] = None
        if stage == "candidate_1" and case["partition"] == "development":
            self.candidate_calls += 1
            if self.stop == "error" and self.candidate_calls == 2:
                raise TimeoutError("Scripted interruption after one saved comparison")
            if self.candidate_calls == 1:
                if self.loss:
                    result["order_id"] = "lost"
                self.cancelled = self.stop == "cancel"
        return json.dumps(result)

    async def revise(self, prompt, payload, previous, number):
        return prompt + f" Revision {number}: preserve explicit facts."


async def run_script(provider):
    snapshots = []

    async def save(snapshot):
        snapshots.append(deepcopy(snapshot))

    result = await run_experiment(make_experiment(), provider, save, lambda: provider.cancelled)
    return result, snapshots


@pytest.mark.parametrize("stop", ["error", "cancel"])
@pytest.mark.parametrize("loss", [False, True])
@pytest.mark.asyncio
async def test_partial_development_retains_counts_without_qualifying(stop, loss):
    result, _ = await run_script(ScriptedProvider(loss=loss, stop=stop))
    proposal = result["proposals"][0]
    assert result["status"] == ("error" if stop == "error" else "cancelled")
    assert result["verdict"] == "inconclusive"  # No selected candidate exists.
    assert result["selected_candidate_id"] is None
    assert proposal["status"] == ("rejected" if loss else "incomplete")
    assert proposal["development"]["observed_cases"] == 1
    assert proposal["development"]["total_cases"] == 20
    assert proposal["development"]["improvements"] == 1
    assert proposal["development"]["regressions"] == int(loss)
    assert proposal["development"]["complete"] is False
    assert proposal["development"]["qualified"] is False


@pytest.mark.parametrize("loss", [False, True])
@pytest.mark.asyncio
async def test_restart_rebuilds_partial_proposal_after_raw_save(tmp_path, loss):
    _, snapshots = await run_script(ScriptedProvider(loss=loss, stop="error"))
    crash = next(
        item for item in snapshots
        if item["status"] == "running" and len(item["observations"]) == 21
    )
    assert not crash["proposals"][0]["comparisons"]  # Raw save precedes pair bookkeeping.
    store = Store(tmp_path / "crash.sqlite3")
    store.save(crash)
    store.recover()
    recovered = store.get(crash["id"])
    proposal = recovered["proposals"][0]
    assert recovered["status"] == "interrupted"
    assert recovered["verdict"] == "inconclusive"
    assert proposal["status"] == ("rejected" if loss else "incomplete")
    assert proposal["development"]["observed_cases"] == 1
    assert proposal["development"]["improvements"] == 1
    assert proposal["development"]["regressions"] == int(loss)
    assert proposal["development"]["complete"] is False
    assert proposal["development"]["qualified"] is False


@pytest.mark.asyncio
async def test_restart_after_final_development_raw_recovers_complete_proposal(tmp_path):
    _, snapshots = await run_script(ScriptedProvider())
    crash = next(
        item for item in snapshots
        if item["phase"] == "candidate_1_development"
        and len(item["observations"]) == 40
    )
    assert len(crash["proposals"][0]["comparisons"]) == 19
    store = Store(tmp_path / "crash.sqlite3")
    store.save(crash)
    store.recover()
    recovered = store.get(crash["id"])
    proposal = recovered["proposals"][0]
    assert recovered["selected_candidate_id"] is None
    assert recovered["verdict"] == "inconclusive"
    assert proposal["development"]["observed_cases"] == 20
    assert proposal["development"]["improvements"] == 20
    assert proposal["development"]["complete"] is True
    assert proposal["development"]["qualified"] is True
    assert proposal["status"] == "development_qualified"


@pytest.mark.asyncio
async def test_independent_pairs_do_not_pollute_development_or_selection_status(tmp_path):
    result, _ = await run_script(ScriptedProvider())
    selected, discarded = result["proposals"]
    assert len(selected["comparisons"]) == 40
    assert selected["status"] == "assessed"
    assert discarded["status"] == "discarded"
    for proposal in (selected, discarded):
        assert proposal["development"]["improvements"] == 20
        assert proposal["development"]["observed_cases"] == 20
        assert proposal["development"]["complete"] is True
        assert proposal["development"]["qualified"] is True
    # A crash after the independent pairs were saved must preserve the same
    # development-only counts and existing selection decisions.
    result["status"] = "running"
    store = Store(tmp_path / "crash.sqlite3")
    store.save(result)
    store.recover()
    recovered = store.get(result["id"])
    assert [p["status"] for p in recovered["proposals"]] == ["assessed", "discarded"]
    assert [p["development"] for p in recovered["proposals"]] == [
        selected["development"], discarded["development"],
    ]


@pytest.mark.asyncio
async def test_independent_loss_rejects_without_rewriting_development_evidence():
    class IndependentLoss(ScriptedProvider):
        async def predict(self, prompt, case, stage):
            raw = await super().predict(prompt, case, stage)
            if stage == "candidate_1" and case["id"] == "ticket-20":
                return json.dumps({**case["expected"], "order_id": "lost-independently"})
            return raw

    result, _ = await run_script(IndependentLoss())
    selected = result["proposals"][0]
    assert result["verdict"] == "rejected"
    assert selected["status"] == "rejected"
    assert selected["development"]["complete"] is True
    assert selected["development"]["qualified"] is True
    assert selected["development"]["regressions"] == 0
    assert selected["development"]["improvements"] == 20
    assert result["assessments"]["regression"]["regressions"] == 1
    assert result["assessments"]["final"]["status"] == "not_run"
