import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import type { Dataset, Evaluation, Experiment, HistoryItem, ServerStatus, StorageFailure } from '../types';

const expected = { order_id: '004812', issue_type: 'damaged_item', requested_action: 'refund', needs_review: false };
const dataset: Dataset = { dataset_id: 'server-dataset', name: 'Synthetic test examples', cases: [{ id: 'dev-001', text: '<img src=x onerror="alert(1)"> Please refund order 004812. The cup arrived cracked.', expected, partition: 'development', case_hash: 'sha256:stable', fixture_outputs: { baseline: JSON.stringify(expected), candidate_1: JSON.stringify(expected), candidate_2: JSON.stringify(expected) } }], version_hash: 'sha256:dataset', manifest_hash: 'sha256:manifest', manifest: { development: ['dev-001'], regression: [], final: [] }, review_status: 'draft', human_review_pending: true, full_experiment_eligible: false, source: 'demo', warnings: [], starter_prompt: 'Extract intent.\nInfer a remedy.' };
function evaluation(changed: boolean): Evaluation { return { raw: JSON.stringify({ ...expected, requested_action: changed ? 'replacement' : 'refund' }), parsed: { ...expected, requested_action: changed ? 'replacement' : 'refund' }, checks: { json: true, schema: true, order_id: true, issue_type: true, requested_action: !changed, needs_review: true }, reasons: changed ? { requested_action: 'Expected refund; got replacement.' } : {}, passed: !changed }; }
function experiment(): Experiment {
  const comparison = { case_id: 'dev-001', partition: 'development', candidate_id: 'candidate_1', baseline: evaluation(false), candidate: evaluation(true), fixed: [], regressed: ['requested_action' as const], status: 'regressed' as const };
  return { id: 'run-1', created_at: '2026-10-21T00:00:00Z', completed_at: '2026-10-21T00:00:01Z', status: 'completed', phase: 'completed', execution_kind: 'Fixture simulation', scenario: 'regression', baseline_prompt: dataset.starter_prompt ?? '', dataset, prior_exposure: false, model: { target: 'fixture-target-v1', repair: 'fixture-repair-v1', settings: {} }, observations: [{ case_id: 'dev-001', case_hash: 'sha256:stable', partition: 'development', stage: 'baseline', prompt_hash: 'sha256:baseline', result: evaluation(false) }], proposals: [{ id: 'candidate_1', prompt: 'Extract intent.\nUse null for uncertainty.', prompt_hash: 'sha256:proposal', development: { improvements: 0, regressions: 1, passing_cases: 0, qualified: false }, status: 'rejected', comparisons: [comparison] }], events: [{ phase: 'baseline', message: 'Saved baseline observation' }], usage: { live_calls: 0, tokens: 'not applicable', cost: 'not applicable' }, verdict: 'inconclusive', verdict_reasons: ['No development-qualified candidate.'], diagnosis: [], selected_candidate_id: null, frozen_candidate_hash: null, assessments: { development: { status: 'completed' }, regression: { status: 'not_run', reason: 'No qualifying candidate' }, final: { status: 'not_run', reason: 'No qualifying candidate' } }, comparisons: [], summary: { fixed: 0, regressed: 0, still_failing: 0, unchanged: 0 } };
}
function statusSnapshot(activeId: string | null, storageFailure: StorageFailure | null = null, liveCalls: number | null = 0): ServerStatus { return { storage_failure: storageFailure, execution_kind: 'Fixture simulation', live: { enabled: false, access_confirmed: false, cap_confirmed: false, missing: ['access', 'cap'] }, active_experiment_id: activeId, live_calls: liveCalls }; }
function setup(run = experiment(), importError = false, options: { live?: ServerStatus['live']; activeId?: string | null; storageFailure?: StorageFailure | null; liveCalls?: number | null; history?: HistoryItem[]; runs?: Experiment[]; importGate?: Promise<void>; startGate?: Promise<void>; demoRetryGate?: Promise<void>; demoDataset?: Dataset; statusGate?: Promise<void>; detailErrorStatus?: number; statusErrorStatus?: number; startUpdatesActiveId?: boolean } = {}) {
  const writes: { url: string; body: unknown }[] = [];
  let demoRequests = 0;
  let statusRequests = 0;
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    if (init?.method === 'POST') {
      if (typeof init.body !== 'string') throw new Error('Expected JSON request body');
      writes.push({ url, body: JSON.parse(init.body) as unknown });
    }
    let body: unknown; let status = 200;
    if (url === '/api/status') {
      statusRequests++;
      if (options.statusErrorStatus) { status = options.statusErrorStatus; body = { detail: 'Experiment status temporarily unavailable' }; }
      else { const snapshot = statusSnapshot(options.activeId ?? null, options.storageFailure ?? null, options.liveCalls === undefined ? 0 : options.liveCalls); body = { ...snapshot, live: options.live ?? snapshot.live }; }
    }
    else if (url === '/api/demo') {
      demoRequests++;
      if (options.demoRetryGate && demoRequests === 1) { status = 503; body = { detail: 'Demo temporarily unavailable' }; }
      else body = options.demoDataset ?? dataset;
    }
    else if (url === '/api/guide') body = { markdown: 'Keep clear facts. Use null for contradictions.' };
    else if (url === '/api/experiments' && init?.method === 'POST') { body = run; if (options.startUpdatesActiveId) options.activeId = run.id; }
    else if (url === '/api/experiments') body = options.history ?? [];
    else if (url.startsWith('/api/experiments/')) {
      const id = url.split('/')[3];
      if (options.detailErrorStatus) { status = options.detailErrorStatus; body = { detail: 'Experiment detail temporarily unavailable' }; }
      else {
        body = [run, ...(options.runs ?? [])].find(item => item.id === id);
        if (!body) throw new Error(`Unknown experiment ${id ?? 'missing'}`);
      }
    }
    else if (url === '/api/datasets/import' && importError) { body = { detail: { errors: ['Case ticket-002: issue_type must be an allowed enum or null.'] } }; status = 422; }
    else if (url === '/api/datasets/import') body = { ...dataset, dataset_id: 'server-imported', name: 'Imported examples', review_status: 'draft', human_review_pending: true, source: 'import' };
    else throw new Error(`Unexpected test request ${url}`);
    const response = new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
    const gate = url === '/api/status' && statusRequests === 1 ? options.statusGate : url === '/api/demo' && demoRequests > 1 ? options.demoRetryGate : url === '/api/datasets/import' ? options.importGate : url === '/api/experiments' && init?.method === 'POST' ? options.startGate : undefined;
    return gate ? gate.then(() => response) : Promise.resolve(response);
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><App /></QueryClientProvider>);
  return { writes, user: userEvent.setup(), client };
}
function losePostResponse(url: string) {
  const serverFetch = fetch;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const response = await serverFetch(input, init);
    if (input === url && init?.method === 'POST') throw new TypeError('Accepted response delivery failed');
    return response;
  }));
}
afterEach(() => { vi.unstubAllGlobals(); });

describe('fixture evidence workspace', () => {
  it('starts the currently loaded fixture, edited prompt and selected scenario from quick start', async () => {
    const { user, writes } = setup();
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    await user.type(screen.getByLabelText('Or paste file contents'), 'custom fixture');
    await user.click(screen.getByRole('button', { name: 'Validate and load' }));
    await screen.findByText('Imported examples');
    await user.clear(screen.getByLabelText('Original prompt'));
    await user.type(screen.getByLabelText('Original prompt'), 'Preserve every explicit request.');
    await user.selectOptions(screen.getByLabelText('Fixture scenario'), 'provider_failure');
    expect(screen.getByRole('region', { name: 'Start here' })).toHaveTextContent('Imported examples · Provider failure');
    await user.click(screen.getByRole('button', { name: 'Run current fixture' }));
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    expect(writes.filter(write => write.url === '/api/experiments')).toEqual([{ url: '/api/experiments', body: { baseline_prompt: 'Preserve every explicit request.', scenario: 'provider_failure', mode: 'fixture', dataset: { dataset_id: 'server-imported' } } }]);
  });
  it('blocks both start actions for a blank prompt', async () => {
    const { user, writes } = setup();
    await screen.findByText('Synthetic test examples');
    await user.clear(screen.getByLabelText('Original prompt'));
    await user.type(screen.getByLabelText('Original prompt'), '   ');
    const quick = screen.getByRole('button', { name: 'Run current fixture' });
    expect(quick).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeDisabled();
    await user.click(quick);
    expect(writes).toHaveLength(0);
  });
  it('keeps quick start disabled when no dataset has loaded', async () => {
    const { writes } = setup(experiment(), false, { demoRetryGate: Promise.resolve() });
    await screen.findByText('Demo temporarily unavailable');
    expect(screen.getByRole('button', { name: 'Run current fixture' })).toBeDisabled();
    expect(writes).toHaveLength(0);
  });
  it('shares the start lock between quick start and the setup action', async () => {
    let finishStart: (() => void) | undefined;
    const startGate = new Promise<void>(resolve => { finishStart = resolve; });
    const { user, writes } = setup(experiment(), false, { startGate });
    await screen.findByText('Synthetic test examples');
    await user.dblClick(screen.getByRole('button', { name: 'Run current fixture' }));
    expect(screen.getByRole('button', { name: 'Run current fixture' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Starting…' }));
    expect(writes.filter(write => write.url === '/api/experiments')).toHaveLength(1);
    finishStart?.();
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
  });
  it('shows collection in progress without prematurely presenting an inconclusive verdict', async () => {
    const run = experiment(); run.status = 'running'; run.phase = 'baseline_development'; run.proposals = []; run.verdict_reasons = ['Experiment is incomplete.'];
    setup(run, false, { activeId: run.id });
    expect(await screen.findByRole('heading', { name: 'Evidence is being collected' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'No supported adoption recommendation' })).not.toBeInTheDocument();
    expect(screen.queryByText('Experiment is incomplete.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run current fixture' })).toBeDisabled();
  });
  it('retains a durable rejection while an experiment is still active', async () => {
    const run = experiment(); run.status = 'running'; run.verdict = 'rejected'; run.verdict_reasons = ['A previously correct field was lost.'];
    setup(run, false, { activeId: run.id });
    expect(await screen.findByRole('heading', { name: 'Failed check on provisional tests' })).toBeVisible();
    expect(screen.getByText('A previously correct field was lost.')).toBeVisible();
  });
  it('shows saved model identities and keeps comparison coverage scoped to the inspected proposal', async () => {
    const run = experiment();
    run.model = { ...run.model, target: 'saved-target-id', repair: 'saved-repair-id' };
    run.dataset = { ...dataset, cases: [...dataset.cases, { ...dataset.cases[0]!, id: 'final-001', partition: 'final' }] };
    run.proposals.push({ ...run.proposals[0]!, id: 'candidate_2', status: 'selected', comparisons: [] });
    run.selected_candidate_id = 'candidate_2';
    run.comparisons = [{ ...run.proposals[0]!.comparisons[0]!, candidate_id: 'candidate_2', candidate: evaluation(false), regressed: [], status: 'unchanged' }];
    const { user } = setup(run);
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByRole('button', { name: 'Run current fixture' }));
    const roles = await screen.findByRole('region', { name: 'Model responsibilities' });
    expect(roles).toHaveTextContent('saved-target-id');
    expect(roles).toHaveTextContent('saved-repair-id');
    expect(roles).toHaveTextContent('No model grader.');
    const coverage = screen.getByText(/of 2 tickets have saved comparisons/);
    expect(coverage).toHaveTextContent('candidate 2: 1 of 2 tickets');
    expect(coverage).toHaveTextContent('selected and frozen candidate');
    expect(coverage).toHaveTextContent('Uncompared tickets are not passes.');
    await user.selectOptions(screen.getByLabelText('Inspect proposal'), 'candidate_1');
    expect(coverage).toHaveTextContent('candidate 1: 1 of 2 tickets');
    expect(coverage).toHaveTextContent('This proposal was not selected');
    expect(within(screen.getByRole('table')).getByText('Lost')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'No supported adoption recommendation' })).toBeVisible();
  });
  it('runs a fixture with server-held dataset identity and keeps failed proposals inspectable', async () => {
    const { user, writes } = setup();
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByRole('button', { name: 'Run fixture experiment' }));
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    expect(writes[0]).toEqual({ url: '/api/experiments', body: { baseline_prompt: dataset.starter_prompt, scenario: 'improvement', mode: 'fixture', dataset: { dataset_id: 'server-dataset' } } });
    expect(screen.getByRole('link', { name: 'Prompt' })).toHaveAttribute('href', '/api/experiments/run-1/export/prompt?candidate_id=candidate_1');
    expect(screen.getByText('No development-qualified candidate.')).toBeVisible();
    expect(within(screen.getByRole('table')).getByText('Lost')).toBeVisible();
    expect(screen.getByText('Expected refund; got replacement.')).toBeVisible();
    expect(document.querySelector('img')).toBeNull();
    expect(screen.getByText(dataset.cases[0]!.text, { selector: '.ticket-input' })).toBeVisible();
    expect(screen.getByText('Provider calls: 0')).toBeVisible();
    await waitFor(() => { expect(screen.getByRole('region', { name: 'Experiment evidence' })).toHaveFocus(); });
  });
  it('shows actionable import validation and sends explicit review attestation', async () => {
    const { user, writes } = setup(experiment(), true);
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    await user.type(screen.getByLabelText('Or paste file contents'), 'invalid dataset');
    await user.click(screen.getByRole('checkbox', { name: 'I attest that I have reviewed these expected answers.' }));
    await user.click(screen.getByRole('button', { name: 'Validate and load' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Case ticket-002: issue_type must be an allowed enum or null.');
    expect(alert).toHaveFocus();
    expect(writes[0]).toEqual({ url: '/api/datasets/import', body: { content: 'invalid dataset', format: 'json', reviewed: true } });
  });
  it('keeps incomplete saved observations exportable without offering an absent prompt', async () => {
    const run = experiment(); run.status = 'error'; run.error = 'Fixture provider timed out'; run.proposals = []; run.verdict_reasons = ['Required observations are incomplete.'];
    const { user } = setup(run);
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByRole('button', { name: 'Run fixture experiment' }));
    await screen.findByText('Fixture provider timed out');
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', '/api/experiments/run-1/export/json');
    expect(screen.queryByRole('link', { name: 'Prompt' })).not.toBeInTheDocument();
    const table = screen.getByRole('table');
    expect(within(table).getAllByText('Not observed')).toHaveLength(6);
    expect(within(table).getAllByText('Not compared')).toHaveLength(6);
    expect(within(within(table).getByRole('row', { name: /Order ID/ })).getAllByText('"004812"')).toHaveLength(2);
    await user.click(screen.getByText('Original raw output'));
    expect(screen.getByText(evaluation(false).raw)).toBeVisible();
  });
  it('loads valid imports without inheriting review status from a filename', async () => {
    const { user, writes } = setup();
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    await user.type(screen.getByLabelText('Or paste file contents'), 'fixture import');
    await user.click(screen.getByRole('button', { name: 'Validate and load' }));
    await screen.findByText('Imported examples');
    expect(writes[0]).toMatchObject({ body: { reviewed: false } });
  });
  it('resets a prior review attestation when imported contents change', async () => {
    const { user, writes } = setup();
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    const content = screen.getByLabelText('Or paste file contents');
    const reviewed = screen.getByRole('checkbox', { name: 'I attest that I have reviewed these expected answers.' });
    await user.type(content, 'first reviewed dataset');
    await user.click(reviewed);
    expect(reviewed).toBeChecked();
    await user.type(content, ' with different labels');
    expect(reviewed).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Validate and load' }));
    await screen.findByText('Imported examples');
    expect(writes[0]).toMatchObject({ body: { reviewed: false } });
  });
  it('rejects oversized pasted UTF-8 before contacting the import endpoint', async () => {
    const { user, writes } = setup();
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    fireEvent.change(screen.getByLabelText('Or paste file contents'), { target: { value: 'é'.repeat(1_000_001) } });
    await user.click(screen.getByRole('button', { name: 'Validate and load' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Import exceeds 2,000,000 UTF-8 bytes.');
    expect(alert).toHaveFocus();
    expect(writes).toHaveLength(0);
  });
  it('ignores stale file reads after a newer file is selected', async () => {
    const { user } = setup();
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    let finishFirst: (value: ArrayBuffer) => void = () => { throw new Error('First read has not started'); };
    const firstRead = new Promise<ArrayBuffer>(resolve => { finishFirst = resolve; });
    const first = new File(['first'], 'first.json', { type: 'application/json' });
    Object.defineProperty(first, 'arrayBuffer', { value: () => firstRead });
    const second = new File(['second'], 'second.csv', { type: 'text/csv' });
    Object.defineProperty(second, 'arrayBuffer', { value: () => Promise.resolve(new TextEncoder().encode('second file contents').buffer) });
    await user.upload(screen.getByLabelText('Choose a file'), first);
    await user.upload(screen.getByLabelText('Choose a file'), second);
    await waitFor(() => { expect(screen.getByLabelText('Or paste file contents')).toHaveValue('second file contents'); });
    await act(async () => {
      finishFirst(new TextEncoder().encode('stale first file').buffer);
      await firstRead;
    });
    expect(screen.getByLabelText('Or paste file contents')).toHaveValue('second file contents');
    expect(screen.getByLabelText('Format')).toHaveValue('csv');
  });
  it('keeps an active experiment cancellable when inspecting saved history', async () => {
    const run = experiment(); run.id = 'run-active'; run.status = 'running'; run.phase = 'baseline_development'; run.proposals = [];
    const old = experiment(); old.id = 'run-old';
    const history = [run, old].map(item => ({ ...item, dataset_name: item.dataset.name }));
    const { user, writes } = setup(run, false, { activeId: run.id, history, runs: [old] });
    await screen.findByText('Synthetic test examples');
    await user.selectOptions(screen.getByLabelText('Experiment history'), old.id);
    await screen.findByRole('button', { name: 'View active experiment' });
    const cancel = screen.getByRole('button', { name: 'Cancel active experiment' });
    await user.dblClick(cancel);
    await screen.findByRole('button', { name: 'Cancellation requested…' });
    expect(writes.filter(write => write.url.endsWith('/cancel'))).toEqual([{ url: '/api/experiments/run-active/cancel', body: {} }]);
    expect(screen.getByRole('button', { name: 'Cancellation requested…' })).toBeDisabled();
  });
  it('shows saved candidate observations even if a complete comparison is unavailable', async () => {
    const run = experiment(); run.status = 'interrupted'; run.proposals[0]!.comparisons = [];
    run.observations = [{ case_id: 'dev-001', case_hash: 'sha256:stable', partition: 'development', stage: 'candidate_1', prompt_hash: 'sha256:proposal', result: evaluation(true) }];
    const { user } = setup(run);
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByRole('button', { name: 'Run fixture experiment' }));
    const table = await screen.findByRole('table');
    const action = within(table).getByRole('row', { name: /Requested action/ });
    expect(within(action).getByText('"replacement"')).toBeVisible();
    expect(within(action).getByText('Not observed').closest('span')).toHaveClass('unobserved-value');
    expect(within(action).getByText('Not compared')).toBeVisible();
    await user.click(screen.getByText('Candidate raw output'));
    expect(screen.getByText(evaluation(true).raw)).toBeVisible();
  });
  it('scopes filter counts to the selected assessment partition', async () => {
    const run = experiment();
    run.dataset = { ...dataset, cases: [...dataset.cases, { ...dataset.cases[0]!, id: 'final-001', partition: 'final' }] };
    const { user } = setup(run);
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByRole('button', { name: 'Run fixture experiment' }));
    await screen.findByRole('table');
    await user.selectOptions(screen.getByLabelText('Partition'), 'final');
    expect(screen.getByRole('button', { name: 'All 1' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Regressed 0' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Not compared 1' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Not compared 1' }));
    expect(screen.getByRole('heading', { name: 'final-001' })).toBeVisible();
  });
  it('moves keyboard focus to the evidence region through the skip link', async () => {
    const { user } = setup();
    await screen.findByText('Synthetic test examples');
    await user.tab();
    expect(screen.getByRole('link', { name: 'Skip to evidence' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('region', { name: 'Experiment evidence' })).toHaveFocus();
  });

  it('prevents starting an experiment while a new dataset is being validated', async () => {
    let finishImport: (() => void) | undefined;
    const importGate = new Promise<void>(resolve => { finishImport = resolve; });
    const { user, writes } = setup(experiment(), false, { importGate });
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    await user.type(screen.getByLabelText('Or paste file contents'), 'new dataset');
    await user.click(screen.getByRole('button', { name: 'Validate and load' }));
    const run = await screen.findByRole('button', { name: 'Validating dataset…' });
    expect(run).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Run current fixture' })).toBeDisabled();
    await user.click(run);
    expect(writes).toHaveLength(1);
    expect(writes[0]?.url).toBe('/api/datasets/import');
    finishImport?.();
    await screen.findByText('Imported examples');
    expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled();
  });
  it('sends only one experiment start when the start button is double-clicked', async () => {
    let finishStart: (() => void) | undefined;
    const startGate = new Promise<void>(resolve => { finishStart = resolve; });
    const { user, writes } = setup(experiment(), false, { startGate });
    await screen.findByText('Synthetic test examples');
    await user.dblClick(screen.getByRole('button', { name: 'Run fixture experiment' }));
    expect(writes.filter(write => write.url === '/api/experiments')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Starting…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Run current fixture' })).toBeDisabled();
    finishStart?.();
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
  });

  it('rejects invalid UTF-8 files rather than silently changing input bytes', async () => {
    const { user, writes } = setup();
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    const file = new File([new Uint8Array([0xc3, 0x28])], 'invalid.csv', { type: 'text/csv' });
    Object.defineProperty(file, 'arrayBuffer', { value: () => Promise.resolve(new Uint8Array([0xc3, 0x28]).buffer) });
    await user.upload(screen.getByLabelText('Choose a file'), file);
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a valid UTF-8 JSON or CSV file.');
    expect(screen.getByLabelText('Or paste file contents')).toHaveValue('');
    expect(writes).toHaveLength(0);
  });

  it('blocks loading the demo while an import is pending, then accepts the newer choice', async () => {
    let finishImport: () => void = () => { throw new Error('Import gate has not started'); };
    const importGate = new Promise<void>(resolve => { finishImport = resolve; });
    const { user } = setup(experiment(), false, { importGate });
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByText('Import your examples'));
    await user.type(screen.getByLabelText('Or paste file contents'), 'new imported dataset');
    await user.click(screen.getByRole('button', { name: 'Validate and load' }));
    const demo = screen.getByRole('button', { name: 'Load demo' });
    expect(demo).toBeDisabled();
    await user.click(demo);
    await act(async () => { finishImport(); await importGate; });
    await screen.findByText('Imported examples');
    expect(demo).toBeEnabled();
    await user.click(demo);
    expect(screen.getByText('Synthetic test examples')).toBeVisible();
    expect(screen.queryByText('Imported examples')).not.toBeInTheDocument();
  });

  it('keeps a newer successful import selected when an older demo retry finishes', async () => {
    let finishDemo: () => void = () => { throw new Error('Demo retry has not started'); };
    const demoRetryGate = new Promise<void>(resolve => { finishDemo = resolve; });
    const { user, writes } = setup(experiment(), false, { demoRetryGate });
    await screen.findByText('Demo temporarily unavailable');
    await user.click(screen.getByRole('button', { name: 'Retry demo' }));
    await user.click(screen.getByText('Import your examples'));
    await user.type(screen.getByLabelText('Or paste file contents'), 'newer imported dataset');
    await user.click(screen.getByRole('button', { name: 'Validate and load' }));
    await screen.findByText('Imported examples');
    await act(async () => { finishDemo(); await demoRetryGate; });
    await waitFor(() => { expect(screen.getByRole('button', { name: 'Load demo' })).toBeEnabled(); });
    expect(screen.getByText('Imported examples')).toBeVisible();
    expect(screen.queryByText('Synthetic test examples')).not.toBeInTheDocument();
    expect(writes).toEqual([{ url: '/api/datasets/import', body: { content: 'newer imported dataset', format: 'json', reviewed: false } }]);
  });

  it('starts a 500-case registered dataset without resending ticket text, labels, scripts or manifests', async () => {
    const cases = Array.from({ length: 500 }, (_, index) => ({
      ...dataset.cases[0]!,
      id: `large-${index + 1}`,
      text: `Private fixture ticket ${index + 1}. ${'Customer-provided context. '.repeat(110)}Please refund order 004812. The cup arrived cracked.`,
      partition: index < 250 ? 'development' : index < 375 ? 'regression' : 'final',
      case_hash: `sha256:large-${index + 1}`,
    }));
    const large: Dataset = { ...dataset, dataset_id: 'server-large-500', name: 'Large registered fixture', cases, full_experiment_eligible: true, manifest: {
      development: cases.filter(ticket => ticket.partition === 'development').map(ticket => ticket.id),
      regression: cases.filter(ticket => ticket.partition === 'regression').map(ticket => ticket.id),
      final: cases.filter(ticket => ticket.partition === 'final').map(ticket => ticket.id),
    } };
    const run = experiment(); run.dataset = large; run.proposals = []; run.observations = [];
    const { user, writes } = setup(run, false, { demoDataset: large });
    await screen.findByText('Large registered fixture');
    await user.click(screen.getByRole('button', { name: 'Run fixture experiment' }));
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    expect(writes).toEqual([{ url: '/api/experiments', body: { baseline_prompt: dataset.starter_prompt, scenario: 'improvement', mode: 'fixture', dataset: { dataset_id: 'server-large-500' } } }]);
    const body = JSON.stringify(writes[0]?.body);
    expect(new Blob([body]).size).toBeLessThan(1024);
    for (const excluded of ['Private fixture ticket', 'fixture_outputs', 'expected', 'manifest', 'case_hash']) expect(body).not.toContain(excluded);
  });

  it('retains an automatically discovered run when active status clears before completion evidence arrives', async () => {
    const run = experiment(); run.id = 'reloaded-active'; run.status = 'running'; run.phase = 'final_assessment';
    const history = [{ ...run, dataset_name: run.dataset.name }];
    const { client } = setup(run, false, { activeId: run.id, history });
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    expect(screen.getByLabelText('Experiment history')).toHaveValue(run.id);
    await act(async () => { client.setQueryData(['status'], statusSnapshot(null)); await Promise.resolve(); });
    expect(screen.getByLabelText('Experiment history')).toHaveValue(run.id);
    expect(screen.getByRole('heading', { name: 'Inspect the evidence' })).toBeVisible();
    const completed = { ...run, status: 'completed', phase: 'completed' };
    await act(async () => { client.setQueryData(['experiment', run.id], completed); await Promise.resolve(); });
    expect(screen.getByLabelText('Experiment history')).toHaveValue(run.id);
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${run.id}/export/json`);
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
  });
  it('keeps an explicit new workspace selected through later active status polls', async () => {
    const run = experiment(); run.id = 'active-first'; run.status = 'running'; run.phase = 'baseline_development';
    const { user, client } = setup(run, false, { activeId: run.id, history: [{ ...run, dataset_name: run.dataset.name }] });
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    await user.selectOptions(screen.getByLabelText('Experiment history'), '');
    expect(screen.getByLabelText('Experiment history')).toHaveValue('');
    await act(async () => { client.setQueryData(['status'], statusSnapshot(null)); await Promise.resolve(); });
    await act(async () => { client.setQueryData(['status'], statusSnapshot('active-later')); await Promise.resolve(); });
    expect(screen.getByLabelText('Experiment history')).toHaveValue('');
    expect(screen.queryByRole('heading', { name: 'Inspect the evidence' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'View active experiment' })).toBeVisible();
  });
  it('preserves history chosen before the initial active-status response resolves', async () => {
    let finishStatus: () => void = () => { throw new Error('Status gate has not started'); };
    const statusGate = new Promise<void>(resolve => { finishStatus = resolve; });
    const run = experiment(); run.id = 'late-active'; run.status = 'running';
    const old = experiment(); old.id = 'explicit-history';
    const history = [run, old].map(item => ({ ...item, dataset_name: item.dataset.name }));
    const { user } = setup(run, false, { activeId: run.id, runs: [old], history, statusGate });
    await screen.findByText('Synthetic test examples');
    await user.selectOptions(screen.getByLabelText('Experiment history'), old.id);
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    await act(async () => { finishStatus(); await statusGate; });
    await screen.findByRole('button', { name: 'View active experiment' });
    expect(screen.getByLabelText('Experiment history')).toHaveValue(old.id);
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${old.id}/export/json`);
  });

  it('shows a stopped storage-failure state without changing earlier saved evidence or polling it as active', async () => {
    const run = experiment(); run.id = 'storage-stopped'; run.status = 'running'; run.phase = 'baseline_development'; run.proposals = [];
    run.assessments = { development: { status: 'running' }, regression: { status: 'not_run' }, final: { status: 'not_run' } };
    delete run.verdict; run.verdict_reasons = [];
    const failure: StorageFailure = { experiment_id: run.id, message: 'The experiment stopped and its final status could not be saved. Restore local database access and restart PatchProof.' };
    const server: Parameters<typeof setup>[2] = { activeId: run.id, history: [{ ...run, dataset_name: run.dataset.name }] };
    const { user, client, writes } = setup(run, false, server);
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    server.activeId = null; server.storageFailure = failure; server.liveCalls = null;
    await act(async () => { client.setQueryData(['status'], statusSnapshot(null, failure, null)); await Promise.resolve(); });
    expect(await screen.findByRole('alert')).toHaveTextContent('Experiment stopped; final status could not be saved');
    expect(screen.getByText('Cumulative provider reservations: Unavailable')).toBeVisible();
    expect(screen.getByText('Provider calls: 0')).toBeVisible();
    const progress = screen.getByRole('region', { name: 'Experiment progress' });
    expect(within(progress).getByText('Stopped; final status not saved')).toBeVisible();
    expect(within(progress).getByText('Last saved phase: baseline development')).toBeVisible();
    expect(screen.queryByText('Experiment in progress')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Final status unavailable' })).toBeVisible();
    expect(screen.getByText('Incomplete (saved status: running)')).toBeVisible();
    expect(screen.getByText('Downloads contain the earlier saved snapshot. The unsaved final status and any unsaved observations are not included.')).toBeVisible();
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${run.id}/export/json`);
    expect(client.getQueryData<Experiment>(['experiment', run.id])?.status).toBe('running');
    const restart = screen.getByRole('button', { name: 'Restart required' });
    expect(restart).toBeDisabled(); await user.click(restart); expect(writes).toHaveLength(0);
    const detailCalls = () => vi.mocked(fetch).mock.calls.filter(([input]) => input === `/api/experiments/${run.id}`).length;
    const before = detailCalls(); expect(before).toBeGreaterThan(0);
    await act(async () => { await new Promise(resolve => { setTimeout(resolve, 650); }); });
    expect(detailCalls()).toBe(before);
  });
  it('keeps the storage warning and start block across history and new-workspace navigation', async () => {
    const run = experiment(); run.id = 'failed-storage'; run.status = 'running';
    const old = experiment(); old.id = 'saved-completed'; old.verdict = 'rejected';
    const failure: StorageFailure = { experiment_id: run.id, message: 'Restore local database access and restart PatchProof.' };
    const history = [run, old].map(item => ({ ...item, dataset_name: item.dataset.name }));
    const { user, writes } = setup(run, false, { storageFailure: failure, history, runs: [old] });
    await screen.findByRole('alert');
    await user.selectOptions(screen.getByLabelText('Experiment history'), old.id);
    await screen.findByRole('heading', { name: 'Failed check on provisional tests' });
    expect(screen.getByRole('alert')).toHaveTextContent(failure.message);
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${old.id}/export/json`);
    expect(screen.queryByText('Downloads contain the earlier saved snapshot. The unsaved final status and any unsaved observations are not included.')).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Experiment history'), '');
    expect(screen.getByRole('alert')).toHaveTextContent('Earlier saved evidence remains available.');
    expect(screen.getByRole('button', { name: 'Restart required' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Run current fixture' })).toBeDisabled();
    expect(screen.getByText('Fixture simulation is paused until local storage is restored and PatchProof is restarted.')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'View earlier saved evidence' }));
    await screen.findByText('Stopped; final status not saved');
    expect(screen.getByLabelText('Experiment history')).toHaveValue(run.id);
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
    expect(writes).toHaveLength(0);
  });
  it('clears the storage block when restart status clears the signal and recovered detail is available', async () => {
    const run = experiment(); run.id = 'storage-recovered'; run.status = 'running';
    const failure: StorageFailure = { experiment_id: run.id, message: 'Restore local database access and restart PatchProof.' };
    const { user, client } = setup(run, false, { storageFailure: failure, history: [{ ...run, dataset_name: run.dataset.name }] });
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'View earlier saved evidence' }));
    await screen.findByText('Stopped; final status not saved');
    const recovered = { ...run, status: 'interrupted', phase: 'stopped' };
    await act(async () => {
      client.setQueryData(['experiment', run.id], recovered);
      client.setQueryData(['status'], statusSnapshot(null));
      await Promise.resolve();
    });
    await waitFor(() => { expect(screen.queryByRole('alert')).not.toBeInTheDocument(); });
    expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${run.id}/export/json`);
  });

  it('retains a saved proposal after storage failure without claiming its development assessment finished', async () => {
    const run = experiment(); run.id = 'partial-storage-proposal'; run.status = 'running'; run.phase = 'candidate_1_development';
    run.proposals[0]!.status = 'evaluating'; run.proposals[0]!.comparisons = [];
    const failure: StorageFailure = { experiment_id: run.id, message: 'Restore local database access and restart PatchProof.' };
    const { user } = setup(run, false, { storageFailure: failure, history: [{ ...run, dataset_name: run.dataset.name }] });
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'View earlier saved evidence' }));
    expect(await screen.findByText('Development qualification was not completed in this saved snapshot.')).toBeVisible();
    expect(screen.getByRole('option', { name: 'candidate 1 — saved status: evaluating' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Prompt' })).toHaveAttribute('href', `/api/experiments/${run.id}/export/prompt?candidate_id=candidate_1`);
    expect(screen.queryByText('Experiment in progress')).not.toBeInTheDocument();
  });

  it.each([404, 500])('honors authoritative idle after restart while saved running detail fails with HTTP %s, then recovers', async errorStatus => {
    const run = experiment(); run.id = `restart-stale-${errorStatus}`; run.status = 'running'; run.phase = 'baseline_development'; run.proposals = [];
    delete run.verdict;
    const failure: StorageFailure = { experiment_id: run.id, message: 'Restore local database access and restart PatchProof.' };
    const server: Parameters<typeof setup>[2] = { storageFailure: failure, history: [{ ...run, dataset_name: run.dataset.name }] };
    const { user, client } = setup(run, false, server);
    await screen.findByRole('alert');
    await user.click(screen.getByRole('button', { name: 'View earlier saved evidence' }));
    await screen.findByText('Stopped; final status not saved');
    server.storageFailure = null; server.activeId = null; server.detailErrorStatus = errorStatus;
    await act(async () => {
      await client.refetchQueries({ queryKey: ['status'] });
      await client.refetchQueries({ queryKey: ['experiment', run.id] });
    });
    await screen.findByText(/Evidence refresh failed/);
    expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
    expect(screen.queryByText('Experiment in progress')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Final status unavailable' })).toBeVisible();
    expect(client.getQueryData<Experiment>(['experiment', run.id])?.status).toBe('running');
    delete server.detailErrorStatus; run.status = 'interrupted'; run.phase = 'stopped'; run.verdict = 'inconclusive';
    await act(async () => { await client.refetchQueries({ queryKey: ['experiment', run.id] }); });
    await screen.findByText('interrupted', { selector: '.progress-heading strong' });
    expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled();
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${run.id}/export/json`);
    expect(screen.queryByText(/Evidence refresh failed/)).not.toBeInTheDocument();
  });
  it('keeps another active run distinct from stale running history and preserves explicit New experiment', async () => {
    const saved = experiment(); saved.id = 'stale-running-history'; saved.status = 'running'; delete saved.verdict;
    const other = experiment(); other.id = 'actual-active'; other.status = 'running';
    const server: Parameters<typeof setup>[2] = { activeId: other.id, runs: [other], history: [saved, other].map(item => ({ ...item, dataset_name: item.dataset.name })) };
    const { user, client } = setup(saved, false, server);
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    await user.selectOptions(screen.getByLabelText('Experiment history'), saved.id);
    await screen.findByRole('button', { name: 'View active experiment' });
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${saved.id}/export/json`);
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
    expect(screen.queryByText('Experiment in progress')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel active experiment' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Experiment running' })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Experiment history'), '');
    server.activeId = null;
    await act(async () => { await client.refetchQueries({ queryKey: ['status'] }); });
    await waitFor(() => { expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled(); });
    expect(screen.getByLabelText('Experiment history')).toHaveValue('');
    server.activeId = other.id;
    await act(async () => { await client.refetchQueries({ queryKey: ['status'] }); });
    expect(await screen.findByRole('button', { name: 'View active experiment' })).toBeVisible();
    expect(screen.getByLabelText('Experiment history')).toHaveValue('');
  });

  it('does not revive cached running history after a known idle response is followed by a status error', async () => {
    const run = experiment(); run.id = 'idle-then-status-error'; run.status = 'running'; delete run.verdict;
    const server: Parameters<typeof setup>[2] = { activeId: null, history: [{ ...run, dataset_name: run.dataset.name }] };
    const { user, client } = setup(run, false, server);
    await screen.findByText('Synthetic test examples');
    await user.selectOptions(screen.getByLabelText('Experiment history'), run.id);
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled();
    server.statusErrorStatus = 500; server.detailErrorStatus = 500;
    await act(async () => {
      await client.refetchQueries({ queryKey: ['experiment', run.id] });
      await client.refetchQueries({ queryKey: ['status'] });
    });
    await screen.findByText('Experiment status temporarily unavailable');
    expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
    expect(screen.queryByText('Experiment in progress')).not.toBeInTheDocument();
  });
  it('retains a newer accepted start across status errors until a fresh idle response, without reviving completed cancellation', async () => {
    const run = experiment(); run.id = 'newer-accepted-start'; run.status = 'running'; run.phase = 'baseline_development';
    const server: Parameters<typeof setup>[2] = { activeId: null };
    const { user, client, writes } = setup(run, false, server);
    await screen.findByText('Synthetic test examples');
    server.statusErrorStatus = 500;
    await user.click(screen.getByRole('button', { name: 'Run fixture experiment' }));
    await screen.findByText('Experiment status temporarily unavailable');
    expect(screen.getByRole('button', { name: 'Experiment running' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel experiment' })).toBeVisible();
    expect(writes.filter(write => write.url === '/api/experiments')).toHaveLength(1);
    run.status = 'completed'; run.phase = 'completed';
    await act(async () => { await client.refetchQueries({ queryKey: ['experiment', run.id] }); });
    await screen.findByText('completed', { selector: '.progress-heading strong' });
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
    delete server.statusErrorStatus;
    await act(async () => { await client.refetchQueries({ queryKey: ['status'] }); });
    await waitFor(() => { expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled(); });
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
  });

  it('discards an initial idle status response that arrives after a newer accepted start', async () => {
    let finishInitialStatus: () => void = () => { throw new Error('Status gate has not started'); };
    const statusGate = new Promise<void>(resolve => { finishInitialStatus = resolve; });
    const run = experiment(); run.id = 'accepted-before-first-status'; run.status = 'running'; run.phase = 'baseline_development';
    const server: Parameters<typeof setup>[2] = { activeId: null, statusGate, startUpdatesActiveId: true };
    const { user, client } = setup(run, false, server);
    await screen.findByText('Synthetic test examples');
    await user.click(screen.getByRole('button', { name: 'Run fixture experiment' }));
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    await act(async () => { finishInitialStatus(); await statusGate; });
    await waitFor(() => { expect(screen.getByRole('button', { name: 'Experiment running' })).toBeDisabled(); });
    expect(screen.getByRole('button', { name: 'Cancel experiment' })).toBeVisible();
    expect(client.getQueryData<ServerStatus>(['status'])?.active_experiment_id).toBe(run.id);
  });

  it.each(['running', 'completed'])('keeps a lost start response honest after polling recovers a %s run', async recoveredStatus => {
    const run = experiment(); run.id = 'lost-start-response'; run.status = 'running'; run.phase = 'baseline_development';
    const history: HistoryItem[] = [];
    const server: Parameters<typeof setup>[2] = { activeId: null, history, startUpdatesActiveId: true };
    const { user, client, writes } = setup(run, false, server);
    await screen.findByText('Synthetic test examples');
    losePostResponse('/api/experiments');
    await user.click(screen.getByRole('button', { name: 'Run fixture experiment' }));
    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent('Request notice');
    expect(notice).toHaveTextContent('The server may have accepted it.');
    run.status = recoveredStatus; run.phase = recoveredStatus === 'completed' ? 'completed' : 'baseline_development';
    server.activeId = recoveredStatus === 'running' ? run.id : null;
    history.push({ ...run, dataset_name: run.dataset.name });
    await act(async () => {
      await client.refetchQueries({ queryKey: ['status'] });
      await client.refetchQueries({ queryKey: ['history'] });
    });
    if (recoveredStatus === 'running') {
      await screen.findByRole('button', { name: 'Cancel experiment' });
      expect(screen.getByLabelText('Experiment history')).toHaveValue(run.id);
      expect(screen.getByRole('button', { name: 'Experiment running' })).toBeDisabled();
    } else {
      await screen.findByRole('option', { name: /completed/ });
      expect(screen.getByLabelText('Experiment history')).toHaveValue('');
      expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled();
    }
    expect(screen.getByRole('alert')).toHaveTextContent('Check the current state before submitting again; for experiments, inspect status and saved history.');
    expect(screen.getByRole('alert')).not.toHaveTextContent('Cannot reach');
    expect(writes.filter(write => write.url === '/api/experiments')).toHaveLength(1);
  });

  it('keeps a lost cancel response honest after polling confirms the known run is cancelled', async () => {
    const run = experiment(); run.id = 'lost-cancel-response'; run.status = 'running'; run.phase = 'baseline_development';
    const history = [{ ...run, dataset_name: run.dataset.name }];
    const server: Parameters<typeof setup>[2] = { activeId: run.id, history };
    const { user, client, writes } = setup(run, false, server);
    await screen.findByRole('button', { name: 'Cancel experiment' });
    losePostResponse(`/api/experiments/${run.id}/cancel`);
    await user.click(screen.getByRole('button', { name: 'Cancel experiment' }));
    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent('Request notice');
    expect(notice).toHaveTextContent('The server may have accepted it.');
    run.status = 'cancelled'; run.phase = 'cancelled'; server.activeId = null;
    history[0] = { ...run, dataset_name: run.dataset.name };
    await act(async () => {
      await client.refetchQueries({ queryKey: ['experiment', run.id] });
      await client.refetchQueries({ queryKey: ['status'] });
      await client.refetchQueries({ queryKey: ['history'] });
    });
    await screen.findByText('cancelled', { selector: '.progress-heading strong' });
    expect(screen.getByRole('button', { name: 'Run fixture experiment' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Cancel experiment' })).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('The request outcome could not be confirmed.');
    expect(screen.getByRole('alert')).not.toHaveTextContent('Cannot reach');
    expect(writes.filter(write => write.url.endsWith('/cancel'))).toHaveLength(1);
  });

  it('recovers a failed first evidence read through an explicit retry without changing history selection', async () => {
    const run = experiment(); run.id = 'cold-evidence-retry';
    const server: Parameters<typeof setup>[2] = { detailErrorStatus: 500, history: [{ ...run, dataset_name: run.dataset.name }] };
    const { user, client, writes } = setup(run, false, server);
    await screen.findByText('Synthetic test examples');
    await user.selectOptions(screen.getByLabelText('Experiment history'), run.id);
    expect(await screen.findByRole('alert')).toHaveTextContent('Experiment detail temporarily unavailable');
    const detailCalls = () => vi.mocked(fetch).mock.calls.filter(([input]) => input === `/api/experiments/${run.id}`).length;
    const failedCalls = detailCalls();
    delete server.detailErrorStatus;
    await act(async () => {
      await client.refetchQueries({ queryKey: ['status'] });
      await client.refetchQueries({ queryKey: ['history'] });
    });
    expect(detailCalls()).toBe(failedCalls);
    await user.click(screen.getByRole('button', { name: 'Retry evidence' }));
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    expect(screen.getByLabelText('Experiment history')).toHaveValue(run.id);
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${run.id}/export/json`);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(detailCalls()).toBe(failedCalls + 1);
    expect(writes).toHaveLength(0);
  });

  it('keeps cached evidence and a failed retry visible, then prevents duplicate pending evidence retries', async () => {
    const run = experiment(); run.id = 'cached-evidence-retry';
    const server: Parameters<typeof setup>[2] = { history: [{ ...run, dataset_name: run.dataset.name }] };
    const { user, client, writes } = setup(run, false, server);
    await screen.findByText('Synthetic test examples');
    await user.selectOptions(screen.getByLabelText('Experiment history'), run.id);
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    server.detailErrorStatus = 500;
    await act(async () => { await client.refetchQueries({ queryKey: ['experiment', run.id] }); });
    expect(await screen.findByRole('alert')).toHaveTextContent('Evidence refresh failed. The last saved snapshot is shown.');
    await user.click(screen.getByRole('button', { name: 'Retry evidence' }));
    await waitFor(() => { expect(screen.getByRole('button', { name: 'Retry evidence' })).toBeEnabled(); });
    expect(screen.getByRole('alert')).toHaveTextContent('Experiment detail temporarily unavailable');
    expect(screen.getByRole('heading', { name: 'Inspect the evidence' })).toBeVisible();
    expect(client.getQueryData<Experiment>(['experiment', run.id])).toEqual(run);
    delete server.detailErrorStatus;
    let release: () => void = () => { throw new Error('Evidence gate has not started'); };
    const gate = new Promise<void>(resolve => { release = resolve; });
    const serverFetch = fetch;
    let pendingReads = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await serverFetch(input, init);
      if (input === `/api/experiments/${run.id}` && init?.method !== 'POST') { pendingReads++; await gate; }
      return response;
    }));
    await user.dblClick(screen.getByRole('button', { name: 'Retry evidence' }));
    expect(screen.getByRole('button', { name: 'Retrying evidence…' })).toBeDisabled();
    expect(pendingReads).toBe(1);
    expect(screen.getByRole('link', { name: 'JSON evidence' })).toHaveAttribute('href', `/api/experiments/${run.id}/export/json`);
    await act(async () => { release(); await gate; });
    await waitFor(() => { expect(screen.queryByRole('alert')).not.toBeInTheDocument(); });
    expect(screen.getByLabelText('Experiment history')).toHaveValue(run.id);
    expect(client.getQueryData<Experiment>(['experiment', run.id])).toEqual(run);
    expect(writes).toHaveLength(0);
  });

});

const enabledLive: ServerStatus['live'] = { enabled: true, access_confirmed: true, cap_confirmed: true, missing: [], cap_usd: '2', model: 'nvidia/Nemotron-3_5-Lightning', charged_or_reserved_usd: '0.015' };
function liveExperiment(): Experiment {
  const run = experiment();
  return { ...run, execution_kind: 'Live inference', scenario: 'live', model: { target: enabledLive.model!, repair: enabledLive.model!, settings: { enable_thinking: false } }, usage: { live_calls: 3, tokens: 1800, cost: '0.0002' } };
}

describe('live inference controls and saved provenance', () => {
  it('requires an explicit mode choice and starts unscripted examples with the live mode', async () => {
    const unscripted: Dataset = { ...dataset, source: 'import', cases: dataset.cases.map(ticket => { const copy = { ...ticket }; delete copy.fixture_outputs; return copy; }) };
    const { user, writes } = setup(liveExperiment(), false, { live: enabledLive, demoDataset: unscripted });
    await screen.findByText('Live inference available');
    expect(screen.getByLabelText('Execution mode')).toHaveValue('fixture');
    expect(screen.getByRole('button', { name: 'Run current fixture' })).toBeVisible();
    expect(screen.getByText(/Select Live inference to evaluate these examples/)).toBeVisible();
    expect(screen.getByText('Spending cap: confirmed · US$2 total')).toBeVisible();
    expect(screen.getByText('Accounted or reserved: US$0.015')).toBeVisible();
    await user.selectOptions(screen.getByLabelText('Execution mode'), 'live');
    expect(screen.queryByLabelText('Fixture scenario')).not.toBeInTheDocument();
    expect(screen.queryByText(/Live inference is unavailable/)).not.toBeInTheDocument();
    expect(screen.getByText(/Scripted fixture outputs are ignored/)).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Run current examples on Nebius' }));
    await screen.findByRole('heading', { name: 'Inspect the evidence' });
    expect(writes).toEqual([{ url: '/api/experiments', body: { baseline_prompt: dataset.starter_prompt, dataset: { dataset_id: dataset.dataset_id }, scenario: 'improvement', mode: 'live' } }]);
    expect(screen.getByText('Provider calls: 3')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'No supported adoption recommendation' })).toBeVisible();
  });

  it.each([
    { enabled: false, access_confirmed: false, cap_confirmed: false, missing: ['access', 'cap'] },
    { ...enabledLive, cap_confirmed: false, missing: ['cap'] },
    { ...enabledLive, access_confirmed: false, missing: ['access'] },
  ])('keeps live selection unavailable without every server gate: %j', async live => {
    const { user, writes } = setup(experiment(), false, { live });
    await screen.findByText('Synthetic test examples');
    expect(screen.getByRole('option', { name: 'Live inference — Nebius / NVIDIA' })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('Execution mode'), 'live');
    expect(screen.getByLabelText('Execution mode')).toHaveValue('fixture');
    expect(writes).toHaveLength(0);
  });

  it('does not fall back to a fixture request when live availability is withdrawn', async () => {
    const options = { live: enabledLive };
    const { user, writes, client } = setup(liveExperiment(), false, options);
    await screen.findByText('Live inference available');
    await user.selectOptions(screen.getByLabelText('Execution mode'), 'live');
    options.live = statusSnapshot(null).live;
    act(() => { client.setQueryData(['status'], statusSnapshot(null)); });
    await waitFor(() => { expect(screen.getByRole('button', { name: 'Run current examples on Nebius' })).toBeDisabled(); });
    expect(screen.getByLabelText('Execution mode')).toHaveValue('live');
    expect(screen.getByRole('button', { name: 'Run live experiment' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Run live experiment' }));
    expect(writes).toHaveLength(0);
  });

  it('keeps historical fixture evidence scripted on a live-enabled server', async () => {
    const run = experiment();
    const { user } = setup(run, false, { live: enabledLive, history: [{ ...run, dataset_name: run.dataset.name }] });
    await screen.findByText('Live inference available');
    await user.selectOptions(screen.getByLabelText('Execution mode'), 'live');
    await user.selectOptions(screen.getByLabelText('Experiment history'), run.id);
    const evidence = screen.getByRole('region', { name: 'Experiment evidence' });
    expect(await within(evidence).findByText(/Fixture simulation. Scripted outputs demonstrate/)).toBeVisible();
    expect(within(evidence).getByText('Scripted ticket fields; no live model call.')).toBeVisible();
    expect(within(evidence).getByText('Provider calls: 0')).toBeVisible();
    expect(document.querySelector('.masthead-status')).toHaveTextContent('Fixture simulation');
    expect(screen.getByRole('option', { name: /Fixture simulation — regression/ })).toBeInTheDocument();
  });

  it('keeps historical live evidence distinct after restarting with live access disabled', async () => {
    const run = liveExperiment();
    const { user } = setup(run, false, { history: [{ ...run, dataset_name: run.dataset.name }] });
    await screen.findByText('Synthetic test examples');
    await user.selectOptions(screen.getByLabelText('Experiment history'), run.id);
    const evidence = screen.getByRole('region', { name: 'Experiment evidence' });
    expect(await within(evidence).findByText(/Nebius live run. Only saved provider responses/)).toBeVisible();
    expect(within(evidence).queryByText(/Scripted ticket fields/)).not.toBeInTheDocument();
    expect(within(evidence).getByText('NVIDIA model extracts four ticket fields. Expected answers are withheld from extraction.')).toBeVisible();
    expect(within(evidence).getByText('NVIDIA model proposes prompt revisions using development evidence only.')).toBeVisible();
    expect(within(evidence).getByText(/No model grader/)).toBeVisible();
    expect(within(evidence).getByText('Expected answers await human review')).toBeVisible();
    expect(screen.getByText('Live inference locked')).toBeVisible();
    expect(document.querySelector('.masthead-status')).toHaveTextContent('Live inference');
    expect(screen.getByRole('button', { name: 'Run current fixture' })).toBeVisible();
  });
});
