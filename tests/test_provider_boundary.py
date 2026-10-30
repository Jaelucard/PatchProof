import json
import gzip
import sqlite3
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from patchproof.domain import build_dataset, compare, evaluate
from patchproof.engine import run_experiment
from patchproof.providers import (
    FixtureProvider, LiveAuthorization, LiveBlocked, NebiusAdapter, UsageLedger,
)


@pytest.mark.parametrize("access,cap", [(False, False), (False, True), (True, False)])
async def test_either_missing_confirmation_never_reaches_transport(tmp_path, access, cap):
    reached = []

    def transport(request):
        reached.append(request)
        raise AssertionError("Must never reach network transport")

    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    adapter = NebiusAdapter(
        LiveAuthorization(access, cap, Decimal("1")),
        ledger,
        api_key="mock-only",
        model="mock-model",
        input_usd_per_million=Decimal("1"),
        output_usd_per_million=Decimal("1"),
        transport=httpx.MockTransport(transport),
    )
    with pytest.raises(LiveBlocked):
        await adapter.complete([{"role": "user", "content": "test"}])
    assert reached == []
    assert ledger.summary()["live_calls"] == 0


@pytest.mark.parametrize(
    "price,cap",
    [
        (None, Decimal("1")),
        (Decimal("NaN"), Decimal("1")),
        (Decimal("0"), Decimal("1")),
        (Decimal("1"), Decimal("NaN")),
        (Decimal("1"), Decimal("0.000000001")),
    ],
)
async def test_unknown_prices_invalid_or_exhausted_budget_fail_closed(tmp_path, price, cap):
    reached = []
    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    adapter = NebiusAdapter(
        LiveAuthorization(True, True, cap),
        ledger,
        api_key="mock",
        model="mock",
        input_usd_per_million=price,
        output_usd_per_million=price,
        transport=httpx.MockTransport(lambda r: reached.append(r)),
    )
    with pytest.raises(LiveBlocked):
        await adapter.complete([{"role": "user", "content": "test"}])
    assert reached == []
    assert ledger.summary()["live_calls"] == 0


async def test_mock_usage_reconciles_and_output_tokens_bounded(tmp_path):
    reached = []

    def response(request):
        reached.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    adapter = NebiusAdapter(
        LiveAuthorization(True, True, Decimal("1")),
        ledger,
        api_key="mock",
        model="mock",
        input_usd_per_million=Decimal("1"),
        output_usd_per_million=Decimal("2"),
        transport=httpx.MockTransport(response),
    )
    assert await adapter.complete([{"role": "user", "content": "test"}]) == '{"ok":true}'
    assert reached[0]["max_tokens"] == 512
    assert ledger.summary() == {"live_calls": 1, "charged_or_reserved_usd": "0.000018"}


@pytest.mark.parametrize("mode", ["timeout", "bad_json", "missing_usage", "bad_content"])
async def test_failed_or_unknown_usage_holds_reservation(tmp_path, mode):
    def response(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("scripted", request=request)
        if mode == "bad_json":
            return httpx.Response(200, text="broken")
        payload = {"choices": [{"message": {"content": "test"}}]}
        if mode == "bad_content":
            payload = {"choices": []}
        return httpx.Response(200, json=payload)

    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    adapter = NebiusAdapter(
        LiveAuthorization(True, True, Decimal("1")),
        ledger,
        api_key="mock",
        model="mock",
        input_usd_per_million=Decimal("1"),
        output_usd_per_million=Decimal("2"),
        transport=httpx.MockTransport(response),
    )
    with pytest.raises(ValueError):
        await adapter.complete([{"role": "user", "content": "test"}])
    assert ledger.summary()["live_calls"] == 1
    assert Decimal(ledger.summary()["charged_or_reserved_usd"]) > 0
    with ledger.connect() as db:
        assert db.execute("SELECT state FROM usage").fetchone()[0] == "usage_unknown"


def test_reservations_shared_across_adapter_instances(tmp_path):
    path = tmp_path / "usage.sqlite3"
    first, second = UsageLedger(path), UsageLedger(path)
    first.reserve(Decimal(".8"), Decimal("1"))
    with pytest.raises(LiveBlocked):
        second.reserve(Decimal(".3"), Decimal("1"))
    assert second.summary()["live_calls"] == 1


async def test_prepared_target_and_repair_protocols_use_allowlisted_messages(tmp_path):
    messages = []

    def response(request):
        messages.append(json.loads(request.content)["messages"])
        return httpx.Response(
            200, json={
                "choices": [{"message": {"content": "prepared response"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            }
        )

    adapter = NebiusAdapter(
        LiveAuthorization(True, True, Decimal("1")),
        UsageLedger(tmp_path / "ledger.sqlite3"),
        api_key="mock",
        model="mock",
        input_usd_per_million=Decimal("1"),
        output_usd_per_million=Decimal("1"),
        transport=httpx.MockTransport(response),
    )
    await adapter.predict(
        "Target prompt",
        {
            "text": "Visible ticket",
            "expected": {"secret_label": "DO_NOT_SEND"},
            "fixture_outputs": {"baseline": "DO_NOT_SEND"},
        },
        "baseline",
    )
    assert messages[0] == [
        {"role": "system", "content": "Target prompt"},
        {"role": "user", "content": "Visible ticket"},
    ]
    await adapter.revise("Target prompt", [{"id": "development-only", "text": "Dev ticket"}], [], 1)
    repair = json.loads(messages[1][1]["content"])
    assert repair["development"] == [{"id": "development-only", "text": "Dev ticket"}]
    assert "DO_NOT_SEND" not in json.dumps(messages)
    with pytest.raises(LiveBlocked):
        await adapter.revise("test", [], [], 3)
    assert len(messages) == 2


@pytest.mark.parametrize("envelope", [
    '{"choices":[{"message":{"content":"test"}}],'
    '"usage":{"prompt_tokens":1000000,"completion_tokens":0},'
    '"usage":{"prompt_tokens":0,"completion_tokens":0}}',
    '{"choices":[{"message":{"content":"test"}}],'
    '"usage":{"prompt_tokens":0,"prompt_tokens":0,"completion_tokens":0}}',
    '{"choices":[{"message":{"content":"test"}}],'
    '"usage":{"prompt_tokens":0,"completion_tokens":0},"other":NaN}',
    '{"choices":[{"message":{"content":"test"}}],"usage":[]}',
    '[]',
])
async def test_ambiguous_provider_envelope_retains_full_reservation(tmp_path, envelope):
    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    adapter = NebiusAdapter(
        LiveAuthorization(True, True, Decimal("1")), ledger,
        api_key="mock", model="mock",
        input_usd_per_million=Decimal("1"), output_usd_per_million=Decimal("1"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=envelope)),
    )
    with pytest.raises(ValueError):
        await adapter.complete([{"role": "user", "content": "test"}])
    with ledger.connect() as db:
        reserved, charged, state = db.execute(
            "SELECT reserved,charged,state FROM usage"
        ).fetchone()
    assert reserved > 0
    assert charged is None
    assert state == "usage_unknown"


@pytest.mark.parametrize("cost,cap", [
    ("0.000000001", "0.0000000001"),
    ("0.0000000011", "0.0000000019"),
    ("9223372037", "99999999999"),
    ("1", "1e10000"),
])
def test_unrepresentable_or_fractional_cap_never_rounds_up(tmp_path, cost, cap):
    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    with pytest.raises(LiveBlocked):
        ledger.reserve(Decimal(cost), Decimal(cap))
    assert ledger.summary()["live_calls"] == 0


def test_exact_nanodollar_boundary_remains_usable(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    ledger.reserve(Decimal("0.000000001"), Decimal("0.0000000019"))
    with pytest.raises(LiveBlocked):
        ledger.reserve(Decimal("0.0000000001"), Decimal("0.0000000019"))
    assert ledger.summary() == {"live_calls": 1, "charged_or_reserved_usd": "1E-9"}


@pytest.mark.parametrize("stage", ["candidate_1", "candidate_2"])
async def test_regression_fixture_targets_selected_candidate_once(stage):
    expected = {"order_id": "0019", "issue_type": "other",
                "requested_action": "refund", "needs_review": False}
    raw = json.dumps(expected)
    provider = FixtureProvider("regression", delay=0)
    case = {"id": "ticket", "partition": "regression", "expected": expected,
            "fixture_outputs": {stage: raw, "baseline": raw}}
    assert await provider.predict("prompt", case, "baseline") == raw
    changed = await provider.predict("prompt", case, stage)
    assert evaluate(changed, expected)["checks"]["order_id"] is False
    assert await provider.predict("prompt", case, stage) == raw


@pytest.mark.parametrize("raw", ["not JSON", "[]", "null", '"text"',
                                '{"order_id":"0019","order_id":"0019"}',
                                '{"order_id": NaN}'])
async def test_regression_fixture_preserves_invalid_script_for_evaluation(raw):
    expected = {"order_id": "0019", "issue_type": "other",
                "requested_action": "refund", "needs_review": False}
    provider = FixtureProvider("regression", delay=0)
    case = {"id": "ticket", "partition": "regression", "expected": expected,
            "fixture_outputs": {"candidate_2": raw, "baseline": json.dumps(expected)}}
    observed = await provider.predict("prompt", case, "candidate_2")
    assert observed == raw
    assert evaluate(observed, expected)["passed"] is False


async def test_regression_fixture_chooses_a_field_the_baseline_passed():
    expected = {"order_id": "0019", "issue_type": "other",
                "requested_action": "refund", "needs_review": False}
    baseline = json.dumps({**expected, "order_id": "WRONG"})
    candidate = json.dumps(expected)
    case = {"id": "ticket", "partition": "regression", "expected": expected,
            "fixture_outputs": {"baseline": baseline, "candidate_1": candidate}}
    observed = await FixtureProvider("regression", delay=0).predict("prompt", case, "candidate_1")
    changes = compare(evaluate(baseline, expected), evaluate(observed, expected))
    assert changes["regressed"] == ["issue_type"]
    assert "order_id" in changes["fixed"]


@pytest.mark.parametrize("candidate_id", ["SCRIPTED-REGRESSION", "WRONG"])
async def test_regression_fixture_never_fixes_a_sentinel_collision(candidate_id):
    expected = {"order_id": "SCRIPTED-REGRESSION", "issue_type": "other",
                "requested_action": "refund", "needs_review": False}
    baseline = json.dumps(expected)
    candidate = json.dumps({**expected, "order_id": candidate_id})
    case = {"id": "ticket", "partition": "regression", "expected": expected,
            "fixture_outputs": {"baseline": baseline, "candidate_1": candidate}}
    observed = await FixtureProvider("regression", delay=0).predict("prompt", case, "candidate_1")
    changes = compare(evaluate(baseline, expected), evaluate(observed, expected))
    assert changes["regressed"] == ["order_id"]
    if candidate_id == "WRONG":
        assert observed == candidate  # Preserve an already authored regression.


async def test_regression_fixture_skips_baseline_without_passes_then_tries_later_case():
    expected = {"order_id": "0019", "issue_type": "other",
                "requested_action": "refund", "needs_review": False}
    candidate = json.dumps(expected)
    provider = FixtureProvider("regression", delay=0)
    case = {"id": "first", "partition": "regression", "expected": expected,
            "fixture_outputs": {"baseline": "not JSON", "candidate_1": candidate}}
    assert await provider.predict("prompt", case, "candidate_1") == candidate
    assert provider.regression_injected is False
    case = {**case, "id": "later", "fixture_outputs": {
        "baseline": candidate, "candidate_1": candidate,
    }}
    observed = await provider.predict("prompt", case, "candidate_1")
    assert compare(evaluate(candidate, expected), evaluate(observed, expected))["regressed"]
    assert provider.regression_injected is True


@pytest.mark.parametrize("baseline,expected_lost", [
    ('{"order_id":"WRONG","issue_type":null,"requested_action":null,"needs_review":true}', "schema"),
    ("[]", "json"),
])
async def test_regression_fixture_can_lose_a_baseline_structure_check(baseline, expected_lost):
    expected = {"order_id": "0019", "issue_type": "other",
                "requested_action": "refund", "needs_review": False}
    candidate = json.dumps(expected)
    case = {"id": "ticket", "partition": "regression", "expected": expected,
            "fixture_outputs": {"baseline": baseline, "candidate_1": candidate}}
    observed = await FixtureProvider("regression", delay=0).predict("prompt", case, "candidate_1")
    changes = compare(evaluate(baseline, expected), evaluate(observed, expected))
    assert changes["regressed"] == [expected_lost]


def test_large_accounted_usage_blocks_more_calls_without_sqlite_sum_overflow(tmp_path):
    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    maximum = Decimal("9223372036.854775807")
    # Existing accounted history can exceed SQLite SUM's signed integer range.
    # Seed that historical state directly; new unresolved requests are serialized.
    with ledger.connect() as db:
        db.executemany(
            "INSERT INTO usage VALUES (?,10000000,?,'accounted')",
            [("existing-1", ledger.nano(maximum)), ("existing-2", ledger.nano(maximum))],
        )
    assert Decimal(ledger.summary()["charged_or_reserved_usd"]) == 2 * maximum
    with pytest.raises(LiveBlocked):
        ledger.reserve(Decimal(".01"), Decimal("1"))


@pytest.mark.parametrize("malformed", [False, True])
async def test_custom_regression_run_rejects_selected_proposal_with_saved_evidence(malformed):
    cases = []
    for index in range(40):
        expected = {"order_id": f"{index:05}", "issue_type": "other",
                    "requested_action": "refund", "needs_review": False}
        cases.append({
            "id": f"custom-{index}", "text": f"Please refund order {index:05}.",
            "expected": expected,
            "fixture_outputs": {
                "baseline": json.dumps({**expected, "requested_action": None}),
                "candidate_1": json.dumps({**expected, "order_id": "WRONG"} if malformed else expected),
                "candidate_2": json.dumps(expected),
            },
        })
    dataset = build_dataset("Custom regression fixture", cases)
    first_regression = next(c for c in dataset["cases"] if c["partition"] == "regression")
    if malformed:
        first_regression["fixture_outputs"]["candidate_2"] = "not JSON"
    experiment = {
        "id": "test", "execution_kind": "Fixture simulation", "baseline_prompt": "Extract",
        "dataset": dataset, "model": {},
    }

    async def save(snapshot):
        pass

    result = await run_experiment(experiment, FixtureProvider("regression", delay=0), save, lambda: False)
    assert result["status"] == "completed"
    assert result["selected_candidate_id"] == ("candidate_2" if malformed else "candidate_1")
    assert result["verdict"] == "rejected"
    assert result["assessments"]["regression"]["regressions"] >= 1
    assert result["assessments"]["final"]["status"] == "not_run"
    if malformed:
        saved = next(o for o in result["observations"]
                     if o["case_id"] == first_regression["id"] and o["stage"] == "candidate_2")
        assert saved["result"]["raw"] == "not JSON"
        assert saved["result"]["checks"]["json"] is False


async def test_demo_regression_retains_exactly_one_order_id_loss():
    demo = json.loads((Path(__file__).parents[1] / "data/demo.json").read_text())
    dataset = build_dataset(demo["name"], demo["cases"], trusted_partitions=True)
    experiment = {
        "id": "demo-test", "execution_kind": "Fixture simulation", "baseline_prompt": "Extract",
        "dataset": dataset, "model": {},
    }

    async def save(snapshot):
        pass

    result = await run_experiment(experiment, FixtureProvider("regression", delay=0), save, lambda: False)
    assert result["selected_candidate_id"] == "candidate_2"
    assert result["assessments"]["regression"]["regressions"] == 1
    losses = [comparison["regressed"] for comparison in result["comparisons"] if comparison["regressed"]]
    assert losses == [["order_id"]]
    assert result["verdict"] == "rejected"
    assert result["assessments"]["final"]["status"] == "not_run"


async def test_compressed_provider_response_is_rejected_before_decoding(tmp_path):
    wire = gzip.compress(b"x" * (2 * 1024 * 1024))
    seen = {"read": False, "closed": False, "accept_encoding": None}

    class CompressedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            seen["read"] = True
            yield wire

        async def aclose(self):
            seen["closed"] = True

    def response(request):
        seen["accept_encoding"] = request.headers.get("accept-encoding")
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=CompressedStream())

    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    adapter = NebiusAdapter(
        LiveAuthorization(True, True, Decimal("1")), ledger,
        api_key="mock", model="mock",
        input_usd_per_million=Decimal("1"), output_usd_per_million=Decimal("1"),
        transport=httpx.MockTransport(response),
    )
    with pytest.raises(ValueError, match="content encoding"):
        await adapter.complete([{"role": "user", "content": "test"}])
    assert seen == {"read": False, "closed": True, "accept_encoding": "identity"}
    with ledger.connect() as db:
        reserved, charged, state = db.execute("SELECT reserved,charged,state FROM usage").fetchone()
    assert reserved > 0 and charged is None and state == "usage_unknown"


async def test_uncompressed_stream_still_enforces_total_response_bound(tmp_path):
    class LargeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b" " * 40000
            yield b" " * 40000

    ledger = UsageLedger(tmp_path / "usage.sqlite3")
    adapter = NebiusAdapter(
        LiveAuthorization(True, True, Decimal("1")), ledger,
        api_key="mock", model="mock",
        input_usd_per_million=Decimal("1"), output_usd_per_million=Decimal("1"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=LargeStream())),
    )
    with pytest.raises(ValueError, match="64 KiB"):
        await adapter.complete([{"role": "user", "content": "test"}])
    with ledger.connect() as db:
        assert db.execute("SELECT charged,state FROM usage").fetchone() == (None, "usage_unknown")


@pytest.mark.parametrize("schema", [
    "CREATE TABLE customers (name TEXT); INSERT INTO customers VALUES ('synthetic');",
    "CREATE TABLE sqliteBackup (value TEXT); INSERT INTO sqliteBackup VALUES ('synthetic');",
    "CREATE TABLE usage (amount INTEGER); INSERT INTO usage VALUES (17);",
    "CREATE TABLE usage (id TEXT PRIMARY KEY, reserved INTEGER NOT NULL, charged INTEGER, state TEXT NOT NULL); CREATE VIEW foreign_view AS SELECT * FROM usage;",
])
def test_ledger_refuses_foreign_database_without_modifying_it(tmp_path, schema):
    path = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(schema)
    original = path.read_bytes()
    with pytest.raises(ValueError, match="PatchProof usage ledger"):
        UsageLedger(path)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("foreign.sqlite3-*"))


def test_ledger_refuses_non_sqlite_file_without_modifying_it(tmp_path):
    path = tmp_path / "foreign.sqlite3"
    path.write_bytes(b"Unrelated synthetic file")
    with pytest.raises(ValueError, match="PatchProof usage ledger"):
        UsageLedger(path)
    assert path.read_bytes() == b"Unrelated synthetic file"


def test_ledger_reopens_existing_legacy_usage_without_losing_reservations(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE usage (id TEXT PRIMARY KEY, reserved INTEGER NOT NULL, charged INTEGER, state TEXT NOT NULL)")
        db.execute("INSERT INTO usage VALUES ('existing',800000000,NULL,'usage_unknown')")
    ledger = UsageLedger(path)
    assert ledger.summary() == {"live_calls": 1, "charged_or_reserved_usd": "0.8"}
    with pytest.raises(LiveBlocked):
        ledger.reserve(Decimal(".3"), Decimal("1"))


@pytest.mark.parametrize("keep_open", [False, True])
def test_ledger_rejects_foreign_wal_database_without_side_effects(tmp_path, keep_open):
    path = tmp_path / "foreign-wal.sqlite3"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE customers (name TEXT)")
        db.execute("INSERT INTO customers VALUES ('synthetic')")
        db.commit()
        if not keep_open:
            db.close()
        before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
        with pytest.raises(ValueError, match="PatchProof usage ledger"):
            UsageLedger(path)
        after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
        assert after == before
    finally:
        db.close()


def test_ledger_reads_valid_uncheckpointed_wal_before_accepting_it(tmp_path):
    path = tmp_path / "legacy-wal.sqlite3"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("CREATE TABLE usage (id TEXT PRIMARY KEY, reserved INTEGER NOT NULL, charged INTEGER, state TEXT NOT NULL)")
        db.execute("INSERT INTO usage VALUES ('existing',800000000,NULL,'usage_unknown')")
        db.commit()
        assert Path(str(path) + "-wal").stat().st_size > 0
        ledger = UsageLedger(path)
        assert ledger.summary() == {"live_calls": 1, "charged_or_reserved_usd": "0.8"}
        with pytest.raises(LiveBlocked):
            ledger.reserve(Decimal(".3"), Decimal("1"))
    finally:
        db.close()
