"""Transport-mocked live wiring; these tests are not real provider evidence."""
import json
import time
from argparse import Namespace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from patchproof.__main__ import live_configuration
from patchproof.app import APP_ROOT, create_app
from patchproof.providers import LiveAuthorization, LiveBlocked, LiveConfig


def wait(client, identifier):
    for _ in range(2500):
        value = client.get('/api/experiments/' + identifier).json()
        if value['status'] not in {'queued', 'running'}:
            return value
        time.sleep(.002)
    raise AssertionError('Mocked live run did not complete')


def configured():
    return LiveConfig(authorization=LiveAuthorization(True, True, Decimal('2')), api_key='test-secret-never-export')


def test_live_workflow_persists_receipts_and_preserves_fixture_history(tmp_path, monkeypatch):
    config = configured()
    cases = json.loads((APP_ROOT / 'data/demo.json').read_text())['cases']
    by_text = {case['text']: case for case in cases}
    requests = []
    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        messages = body['messages']
        if messages[0]['content'].startswith('Propose one replacement'):
            data = json.loads(messages[1]['content'])
            output = data['baseline_prompt'] + f"\nMOCK_REVISION_{data['revision_number']}"
        else:
            stage = 'candidate_2' if 'MOCK_REVISION_2' in messages[0]['content'] else 'candidate_1' if 'MOCK_REVISION_1' in messages[0]['content'] else 'baseline'
            output = by_text[messages[1]['content']]['fixture_outputs'][stage]
        return httpx.Response(200, json={
            'id': f'mock-response-{len(requests)}', 'model': body['model'],
            'choices': [{'finish_reason': 'stop', 'message': {'content': output}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20},
        })
    original = LiveConfig.make_adapter
    monkeypatch.setattr(LiveConfig, 'make_adapter', lambda self, ledger, **kwargs: original(self, ledger, transport=httpx.MockTransport(transport), **kwargs))
    path = tmp_path / 'review.sqlite3'
    with TestClient(create_app(path, fixture_delay=0, live_config=config)) as client:
        dataset = client.get('/api/demo').json()
        body = {'baseline_prompt': dataset['starter_prompt'], 'dataset': {'dataset_id': dataset['dataset_id']}}
        fixture = wait(client, client.post('/api/experiments', json=body).json()['id'])
        assert fixture['execution_kind'] == 'Fixture simulation'
        assert fixture['usage']['live_calls'] == 0
        response = client.post('/api/experiments', json={**body, 'mode': 'live', 'scenario': 'provider_failure'})
        assert response.status_code == 202, response.text
        run = wait(client, response.json()['id'])
        assert run['status'] == 'completed', run.get('error')
        assert run['execution_kind'] == 'Live inference'
        assert run['scenario'] == 'live'
        assert run['prior_exposure'] is True
        assert run['dataset']['human_review_pending'] is True
        assert run['verdict'] == 'inconclusive'
        assert len(run['observations']) == 150
        assert len(requests) == run['usage']['live_calls'] == len(run['provider_receipts']) == 152
        assert run['model']['target'] == run['model']['repair'] == 'nvidia/Nemotron-3_5-Lightning'
        assert run['model']['settings']['per_call_timeout_seconds'] == 60
        assert run['model']['settings']['total_timeout_seconds'] == 1800
        assert Decimal(str(run['usage']['cost'])) > 0
        status = client.get('/api/status').json()
        assert status['live']['enabled'] is True
        assert status['live']['cap_usd'] == '2'
        assert status['live_calls'] == 152
        report = client.get(f"/api/experiments/{run['id']}/export/markdown").text
        prompt = client.get(f"/api/experiments/{run['id']}/export/prompt").text
        assert 'configured for Nebius live inference' in report
        assert 'Live provider calls: 152' in report
        assert 'Fixture simulation' not in prompt
        assert 'test-secret-never-export' not in json.dumps([run, status, report, prompt])
        fixture_report = client.get(f"/api/experiments/{fixture['id']}/export/markdown").text
        assert 'scripted evidence' not in prompt
        assert 'Scripted responses' in fixture_report
    # Disabling future live execution never rewrites existing run provenance.
    with TestClient(create_app(path)) as client:
        assert client.get('/api/status').json()['live']['enabled'] is False
        assert client.get('/api/status').json()['live_calls'] == 152
        restored = client.get('/api/experiments/' + run['id']).json()
        assert restored == run
        assert 'configured for Nebius live inference' in client.get(f"/api/experiments/{run['id']}/export/markdown").text


def test_unscripted_live_import_reaches_adapter_and_sanitizes_provider_error(tmp_path, monkeypatch):
    config = configured()
    calls = []
    def transport(request):
        calls.append(request)
        raise RuntimeError('Authorization: Bearer test-secret-never-export request-sensitive-content')
    original = LiveConfig.make_adapter
    monkeypatch.setattr(LiveConfig, 'make_adapter', lambda self, ledger, **kwargs: original(self, ledger, transport=httpx.MockTransport(transport), **kwargs))
    app = create_app(tmp_path / 'review.sqlite3', live_config=config)
    with TestClient(app) as client:
        template = client.get('/api/templates/json').json()
        dataset = client.post('/api/datasets/import', json={'content': json.dumps(template), 'format': 'json'}).json()
        response = client.post('/api/experiments', json={'baseline_prompt': 'Return JSON with four fields.', 'dataset': {'dataset_id': dataset['dataset_id']}, 'mode': 'live'})
        assert response.status_code == 202, response.text
        run = wait(client, response.json()['id'])
        assert len(calls) == 1
        assert run['status'] == 'error'
        assert run['usage']['live_calls'] == 1
        assert len(run['provider_receipts']) == 1
        combined = json.dumps(run) + client.get(f"/api/experiments/{run['id']}/export/markdown").text
        assert 'test-secret-never-export' not in combined
        assert 'request-sensitive-content' not in combined
        assert Decimal(app.state.ledger.summary()['charged_or_reserved_usd']) > 0


def args(**changes):
    values = dict(live_key_file=None, live_cap_usd=None, confirm_nebius_access=False, confirm_live_cap=False)
    values.update(changes)
    return Namespace(**values)


def test_unconfigured_launcher_never_reads_key(monkeypatch):
    def denied(*a, **kw):
        raise AssertionError('Unexpected key read')
    monkeypatch.setattr('patchproof.__main__.os.open', denied)
    assert live_configuration(args()) is None
    with pytest.raises(LiveBlocked):
        live_configuration(args(live_key_file=Path('/explicit/key'), live_cap_usd='2', confirm_nebius_access=True))


def test_explicit_private_key_file_only(tmp_path):
    key = tmp_path / 'key'
    key.write_text('test-private-key\n')
    key.chmod(0o600)
    config = live_configuration(args(live_key_file=key, live_cap_usd='2', confirm_nebius_access=True, confirm_live_cap=True))
    assert config.api_key == 'test-private-key'
    assert 'test-private-key' not in repr(config)
    key.chmod(0o644)
    with pytest.raises(ValueError, match='private regular file'):
        live_configuration(args(live_key_file=key, live_cap_usd='2', confirm_nebius_access=True, confirm_live_cap=True))
    key.chmod(0o600)
    link = tmp_path / 'key-link'
    link.symlink_to(key)
    with pytest.raises(ValueError, match='Unable to read'):
        live_configuration(args(live_key_file=link, live_cap_usd='2', confirm_nebius_access=True, confirm_live_cap=True))


def test_reserved_request_blocks_transport_and_export_does_not_claim_execution(tmp_path, monkeypatch):
    calls = []
    def transport(request):
        calls.append(request)
        raise AssertionError('An unresolved reservation must prevent transport')
    original = LiveConfig.make_adapter
    monkeypatch.setattr(LiveConfig, 'make_adapter', lambda self, ledger, **kwargs: original(self, ledger, transport=httpx.MockTransport(transport), **kwargs))
    app = create_app(tmp_path / 'review.sqlite3', live_config=configured())
    app.state.ledger.reserve(Decimal('.01'), Decimal('2'))
    with TestClient(app) as client:
        dataset = client.get('/api/demo').json()
        response = client.post('/api/experiments', json={'mode': 'live', 'baseline_prompt': dataset['starter_prompt'], 'dataset': {'dataset_id': dataset['dataset_id']}})
        run = wait(client, response.json()['id'])
        assert run['status'] == 'error'
        assert calls == []
        assert run['usage']['live_calls'] == 0
        assert run['provider_receipts'] == []
        # Legacy status key counts ledger reservations, not exact transport attempts.
        assert client.get('/api/status').json()['live_calls'] == 1
        report = client.get(f"/api/experiments/{run['id']}/export/markdown").text
        assert 'configured for Nebius live inference' in report
        assert 'Live provider calls: 0' in report
        assert 'responses were requested' not in report
