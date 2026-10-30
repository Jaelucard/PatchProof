"""Protocol and accounting checks use mocked HTTP only; no provider access."""

import asyncio
from copy import deepcopy
from dataclasses import FrozenInstanceError
from decimal import Decimal
import json

import httpx
import pytest

from patchproof.providers import (
    LiveAuthorization, LiveBlocked, LiveConfig, NebiusAdapter, ProviderFailure, UsageLedger,
)

KEY = "synthetic-provider-secret-123"
MODEL = LiveConfig.model


def response_payload(**changes):
    payload = {
        "id": "chatcmpl-local-test-1", "model": MODEL,
        "choices": [{"message": {"content": '{"order_id":"001","issue_type":null,"requested_action":"refund","needs_review":false}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 40},
    }
    payload.update(changes)
    return payload


def adapter_for(tmp_path, handler, callback=None):
    config = LiveConfig(LiveAuthorization(True, True, Decimal("2")), KEY)
    ledger = UsageLedger(tmp_path / "provider-usage.sqlite3")
    return config.make_adapter(
        ledger, transport=httpx.MockTransport(handler), receipt_callback=callback,
    )


def test_live_config_is_immutable_and_never_reprs_key():
    config = LiveConfig(LiveAuthorization(True, True, Decimal("2")), KEY)
    assert KEY not in repr(config)
    with pytest.raises(FrozenInstanceError):
        config.api_key = "replacement"
    metadata = config.model_metadata()
    assert metadata["target"] == metadata["repair"] == MODEL
    assert metadata["prices"]["input_usd_per_million"] == "0.06"
    assert metadata["prices"]["output_usd_per_million"] == "0.24"
    assert metadata["settings"]["enable_thinking"] is False
    assert metadata["settings"]["max_output_tokens"] == 512
    assert metadata["settings"]["repair_max_output_tokens"] == 1024
    assert KEY not in json.dumps(metadata)


async def test_prediction_and_repair_protocol_and_durable_attribution(tmp_path):
    requests, snapshots = [], []

    async def persist():
        snapshots.append(deepcopy(adapter.receipts))

    def transport(request):
        # A durable snapshot associates the ledger reservation before HTTP.
        current = snapshots[-1][-1]
        assert current["status"] == "reserved"
        with adapter.ledger.connect() as db:
            assert db.execute("SELECT state FROM usage WHERE id=?", (current["request_id"],)).fetchone() == ("reserved",)
        requests.append(json.loads(request.content))
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.extensions["timeout"]["read"] == 60
        assert request.extensions["timeout"]["connect"] == 10
        return httpx.Response(200, json=response_payload())

    adapter = adapter_for(tmp_path, transport, persist)
    await adapter.predict("Extract JSON", {
        "id": "ticket-001", "text": "Please refund 001.",
        "expected": {"must_not_send": "PRIVATE_EXPECTED"},
        "fixture_outputs": {"baseline": "PRIVATE_FIXTURE"},
    }, "baseline")
    await adapter.revise("Extract JSON", [{"id": "dev-1", "text": "Development only"}], [], 1)
    assert len(requests) == 2
    for request in requests:
        assert request["model"] == MODEL
        assert request["chat_template_kwargs"] == {"enable_thinking": False}
        assert request["store"] is False
        assert request["temperature"] == 0
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["max_tokens"] == 512
    assert requests[1]["max_tokens"] == 1024
    assert "response_format" not in requests[1]
    assert "PRIVATE_EXPECTED" not in json.dumps(requests)
    assert "PRIVATE_FIXTURE" not in json.dumps(requests)
    assert adapter.receipts[0]["case_id"] == "ticket-001"
    assert adapter.receipts[0]["operation"] == "prediction"
    assert adapter.receipts[1]["operation"] == "repair"
    assert adapter.receipts[1]["stage"] == "candidate_1"
    assert all(r["provider_model"] == MODEL for r in adapter.receipts)
    assert all(r["finish_reason"] == "stop" for r in adapter.receipts)
    assert all(r["status"] == "completed" for r in adapter.receipts)
    summary = adapter.usage_summary()
    assert summary["live_calls"] == summary["completed_calls"] == summary["accounted_calls"] == 2
    assert summary["unknown_usage_calls"] == 0
    assert summary["tokens"] == 140
    assert Decimal(summary["cost"]) == Decimal("0.0000228")
    assert KEY not in json.dumps(adapter.receipts)


async def test_pretransport_persistence_failure_never_sends_request(tmp_path):
    requests = []

    async def persist():
        raise OSError(f"Persistence failure includes {KEY} and Authorization")

    adapter = adapter_for(tmp_path, lambda req: requests.append(req), persist)
    with pytest.raises(ProviderFailure) as error:
        await adapter.complete([{"role": "user", "content": "JSON"}])
    assert requests == []
    assert KEY not in str(error.value)
    assert KEY not in json.dumps(adapter.receipts)
    assert adapter.usage_summary()["live_calls"] == 0
    assert adapter.usage_summary()["reservations"] == 1
    assert adapter.usage_summary()["unknown_usage_calls"] == 1
    assert Decimal(adapter.usage_summary()["cost"]) > 0


@pytest.mark.parametrize("usage", [None, [], {}, {"prompt_tokens": True, "completion_tokens": 1},
                                    {"prompt_tokens": -1, "completion_tokens": 1},
                                    {"prompt_tokens": 1, "completion_tokens": "2"}])
async def test_unknown_usage_blocks_more_requests_even_after_reopening(tmp_path, usage):
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(200, json=response_payload(usage=usage))

    adapter = adapter_for(tmp_path, response)
    with pytest.raises(ProviderFailure):
        await adapter.complete([{"role": "user", "content": "JSON"}])
    assert adapter.usage_summary()["unknown_usage_calls"] == 1
    assert "remainder unknown" in adapter.usage_summary()["tokens"]
    reopened = adapter_for(tmp_path, response)
    with pytest.raises(LiveBlocked, match="Unreconciled"):
        await reopened.complete([{"role": "user", "content": "JSON"}])
    assert len(requests) == 1
    assert reopened.ledger.summary()["live_calls"] == 1


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": 100001, "completion_tokens": 1},
    {"prompt_tokens": 1, "completion_tokens": 513},
])
async def test_reported_usage_above_bound_is_charged_and_blocks_restarts(tmp_path, usage):
    adapter = adapter_for(tmp_path, lambda req: httpx.Response(200, json=response_payload(usage=usage)))
    with pytest.raises(ProviderFailure, match="reserved bounds"):
        await adapter.complete([{"role": "user", "content": "JSON"}])
    expected = (Decimal(usage["prompt_tokens"]) * Decimal(".06") + Decimal(usage["completion_tokens"]) * Decimal(".24")) / 1_000_000
    assert Decimal(adapter.usage_summary()["cost"]) == expected
    with adapter.ledger.connect() as db:
        assert db.execute("SELECT state FROM usage").fetchone() == ("usage_exceeded",)
    restarted = adapter_for(tmp_path, lambda req: pytest.fail("No more transport allowed"))
    with pytest.raises(LiveBlocked, match="Unreconciled"):
        await restarted.complete([{"role": "user", "content": "JSON"}])


@pytest.mark.parametrize("finish", [None, "length", "content_filter", "tool_calls", "unrecognized"])
async def test_nonstop_completion_never_becomes_a_valid_observation(tmp_path, finish):
    payload = response_payload()
    payload["choices"][0]["finish_reason"] = finish
    adapter = adapter_for(tmp_path, lambda req: httpx.Response(200, json=payload))
    with pytest.raises(ProviderFailure, match="did not finish normally"):
        await adapter.complete([{"role": "user", "content": "JSON"}])
    assert adapter.usage_summary()["accounted_calls"] == 1
    assert adapter.usage_summary()["completed_calls"] == 0
    assert adapter.receipts[0]["status"] == "error"
    with adapter.ledger.connect() as db:
        assert db.execute("SELECT state FROM usage").fetchone() == ("accounted",)
    with pytest.raises(LiveBlocked):
        await adapter.complete([{"role": "user", "content": "JSON"}])


@pytest.mark.parametrize("mode", ["timeout", "http_error", "unexpected_model", "echo_key", "malformed_json"])
async def test_errors_and_receipts_never_disclose_credentials(tmp_path, mode):
    def response(request):
        if mode == "timeout":
            raise httpx.ReadTimeout(f"failed Authorization: Bearer {KEY}", request=request)
        if mode == "http_error":
            return httpx.Response(401, text=f"Authorization: Bearer {KEY}")
        if mode == "malformed_json":
            return httpx.Response(200, text=f'{{"secret":"{KEY}",invalid}}')
        payload = response_payload()
        payload["id"] = KEY
        payload["untrusted_extra"] = {"secret": KEY}
        if mode == "unexpected_model":
            payload["model"] = KEY
        elif mode == "echo_key":
            payload["choices"][0]["message"]["content"] = f"Authorization: Bearer {KEY}"
        return httpx.Response(200, json=payload)

    adapter = adapter_for(tmp_path, response)
    with pytest.raises(ProviderFailure) as error:
        await adapter.complete([{"role": "user", "content": "JSON"}])
    assert KEY not in str(error.value)
    assert KEY not in json.dumps(adapter.receipts)
    assert "Authorization" not in json.dumps(adapter.receipts)
    assert "untrusted_extra" not in json.dumps(adapter.receipts)
    assert adapter.usage_summary()["completed_calls"] == 0


async def test_cancellation_keeps_reservation_and_durable_request_identity(tmp_path):
    entered = asyncio.Event()
    snapshots = []

    async def response(request):
        entered.set()
        await asyncio.Event().wait()

    async def persist():
        snapshots.append(deepcopy(adapter.receipts))

    adapter = adapter_for(tmp_path, response, persist)
    task = asyncio.create_task(adapter.complete([{"role": "user", "content": "JSON"}]))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert snapshots[0][0]["status"] == "reserved"
    assert snapshots[-1][0]["status"] == "cancelled"
    assert snapshots[0][0]["request_id"] == snapshots[-1][0]["request_id"]
    with adapter.ledger.connect() as db:
        assert db.execute("SELECT id,state FROM usage").fetchone() == (snapshots[0][0]["request_id"], "usage_unknown")
    assert adapter.usage_summary()["live_calls"] == 1
    assert Decimal(adapter.usage_summary()["cost"]) > 0


async def test_catalog_verification_is_authenticated_exact_and_noninference(tmp_path):
    requests = []

    def response(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url) == NebiusAdapter.models_endpoint
        assert request.headers["authorization"] == f"Bearer {KEY}"
        return httpx.Response(200, json={"data": [{"id": "other-model"}, {"id": MODEL}]})

    adapter = adapter_for(tmp_path, response)
    receipt = await adapter.verify_model_access()
    assert receipt["catalog_access_confirmed"] is True
    assert receipt["inference_access_confirmed"] is False
    assert receipt["model"] == MODEL
    assert len(requests) == 1
    assert adapter.ledger.summary()["live_calls"] == 0
    assert adapter.receipts == []
    assert KEY not in json.dumps(receipt)


async def test_catalog_verification_does_not_accept_similar_model_name(tmp_path):
    adapter = adapter_for(tmp_path, lambda req: httpx.Response(200, json={"data": [{"id": MODEL + "-other"}]}))
    with pytest.raises(ProviderFailure, match="not found"):
        await adapter.verify_model_access()
    assert adapter.ledger.summary()["live_calls"] == 0


async def test_catalog_verification_requires_confirmations_before_transport(tmp_path):
    ledger = UsageLedger(tmp_path / "provider-usage.sqlite3")
    adapter = NebiusAdapter(
        LiveAuthorization(), ledger, api_key=KEY, model=MODEL,
        transport=httpx.MockTransport(lambda req: pytest.fail("Unauthorized catalog request")),
    )
    with pytest.raises(LiveBlocked):
        await adapter.verify_model_access()
    assert ledger.summary()["live_calls"] == 0


async def test_crash_with_durable_reservation_blocks_new_adapter(tmp_path):
    ledger = UsageLedger(tmp_path / "provider-usage.sqlite3")
    request_id = ledger.reserve(Decimal("0.001"), Decimal("2"))
    restarted = adapter_for(tmp_path, lambda req: pytest.fail("Unresolved reservation reached HTTP"))
    with pytest.raises(LiveBlocked, match="Unreconciled"):
        await restarted.complete([{"role": "user", "content": "JSON"}])
    with restarted.ledger.connect() as db:
        assert db.execute("SELECT id,state FROM usage").fetchone() == (request_id, "reserved")
    assert restarted.ledger.summary()["charged_or_reserved_usd"] == "0.001"


@pytest.mark.parametrize("key", ["", " ", "key\nheader", "key\rheader", "非ascii", "x" * 8193])
def test_malformed_server_key_is_rejected_without_client_creation(tmp_path, key):
    config = LiveConfig(LiveAuthorization(True, True, Decimal("2")), key)
    with pytest.raises(LiveBlocked, match="credential"):
        config.make_adapter(UsageLedger(tmp_path / "provider-usage.sqlite3"))
