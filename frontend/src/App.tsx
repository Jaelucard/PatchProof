import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, post } from './api';
import { diffLines } from './diff';
import { CHECKS } from './types';
import type { Check, Comparison, ComparisonStatus, Dataset, Evaluation, Experiment, HistoryItem, Proposal, ServerStatus, StorageFailure, Ticket } from './types';

const CHECK_LABELS: Record<Check, string> = { json: 'Valid JSON', schema: 'Four-field schema', order_id: 'Order ID', issue_type: 'Issue type', requested_action: 'Requested action', needs_review: 'Needs review' };
const STATUS_LABELS: Record<ComparisonStatus, string> = { fixed: 'Fixed', regressed: 'Regressed', still_failing: 'Still failing', unchanged: 'Unchanged' };
const FILTERS = ['all', 'fixed', 'regressed', 'still_failing', 'unchanged', 'not_compared'] as const;
const MAX_IMPORT_BYTES = 2_000_000;
const SCENARIOS = [{ value: 'improvement', label: 'Improvement', description: 'A scripted improvement with no lost checks.' }, { value: 'regression', label: 'Regression', description: 'A candidate loses a previously correct check.' }, { value: 'provider_failure', label: 'Provider failure', description: 'A simulated interruption preserves available evidence.' }];
const pretty = (value: unknown): string => value === undefined ? 'Missing' : JSON.stringify(value, null, 2);
const humanize = (value: string): string => value.replaceAll('_', ' ');
const active = (status?: string): boolean => status === 'queued' || status === 'running';
const reviewLabel = (dataset: Dataset): string => dataset.review_status === 'user_attested' ? 'Labels: user-attested as reviewed' : 'Expected answers await human review';
const shortTime = (value: string): string => new Date(value).toLocaleString('en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
function message(error: unknown): string { return error instanceof Error ? error.message : String(error); }
function readable(value: unknown): string { return typeof value === 'string' ? humanize(value) : pretty(value); }

function ErrorNotice({ text, focus = false, onRetry, retrying = false }: { text: string; focus?: boolean; onRetry?: () => void; retrying?: boolean }) {
  const notice = useRef<HTMLDivElement>(null);
  useEffect(() => { if (focus) notice.current?.focus(); }, [focus, text]);
  return <div className="error-notice" role="alert" ref={notice} tabIndex={-1}><strong>Request notice</strong><p>{text}</p>{onRetry && <button className="secondary" disabled={retrying} onClick={onRetry}>{retrying ? 'Retrying evidence…' : 'Retry evidence'}</button>}</div>;
}

function ImportPanel({ onDataset, disabled, onBusyChange }: { onDataset: (dataset: Dataset) => void; disabled: boolean; onBusyChange: (busy: boolean) => void }) {
  const [content, setContent] = useState('');
  const [format, setFormat] = useState('json');
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const fileVersion = useRef(0);
  const importLock = useRef(false);
  function updateContent(value: string) {
    fileVersion.current++;
    setContent(value); setReviewed(false); setError(''); setSuccess(''); setReading(false);
  }
  async function importData() {
    if (disabled || importLock.current || reading) return;
    setError(''); setSuccess('');
    if (new Blob([content]).size > MAX_IMPORT_BYTES) {
      setError('Import exceeds 2,000,000 UTF-8 bytes. Reduce the file or pasted contents before validating.');
      return;
    }
    importLock.current = true; setBusy(true); onBusyChange(true);
    try {
      const dataset = await post<Dataset>('/api/datasets/import', { content, format, reviewed });
      onDataset(dataset);
      setSuccess(`Loaded ${dataset.cases.length} examples. ${reviewLabel(dataset)}.`);
    }
    catch (err) { setError(message(err)); }
    finally { importLock.current = false; setBusy(false); onBusyChange(false); }
  }
  async function readFile(file?: File) {
    if (!file || disabled || busy) return;
    const version = ++fileVersion.current;
    setError(''); setSuccess(''); setReviewed(false); setContent(''); setReading(false);
    if (file.size > MAX_IMPORT_BYTES) { setError('Import exceeds 2,000,000 UTF-8 bytes. Choose a smaller file.'); return; }
    setReading(true);
    try {
      const bytes = await file.arrayBuffer();
      if (fileVersion.current !== version) return;
      let value: string;
      try { value = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
      catch { throw new Error('Choose a valid UTF-8 JSON or CSV file. Invalid byte sequences cannot be imported without changing the contents.'); }
      setReviewed(false); setContent(value); setFormat(file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'json');
    }
    catch (err) { if (fileVersion.current === version) setError(message(err)); }
    finally { if (fileVersion.current === version) setReading(false); }
  }
  return <details className="import-panel">
    <summary>Import your examples</summary>
    <div className="details-body">
      <p className="small-note" id="import-help">JSON or CSV, up to 2,000,000 UTF-8 bytes and 500 cases. Keep each order identifier as a string. All examples are validated before use.</p>
      <div className="template-links"><a href="/api/templates/json" download>JSON template</a><a href="/api/templates/csv" download>CSV template</a><a href="/api/templates/scripted" download>Scripted fixture</a></div>
      {disabled && <p className="small-note">Import is paused while an experiment is active. Its dataset remains frozen.</p>}
      <fieldset className="import-fields" disabled={disabled || busy}>
        <legend className="visually-hidden">Dataset import</legend>
        <label className="field-label" htmlFor="import-file">Choose a file</label>
        <input id="import-file" type="file" accept=".json,.csv,application/json,text/csv" aria-describedby="import-help" onChange={event => { void readFile(event.currentTarget.files?.[0]); }} />
        <div className="inline-field"><label htmlFor="import-format">Format</label><select id="import-format" value={format} onChange={event => { setFormat(event.target.value); setReviewed(false); setError(''); setSuccess(''); }}><option value="json">JSON</option><option value="csv">CSV</option></select></div>
        <label className="field-label" htmlFor="import-content">Or paste file contents</label>
        <textarea id="import-content" className="code-input import-input" value={content} aria-describedby="import-help" aria-invalid={Boolean(error)} onChange={event => { updateContent(event.target.value); }} placeholder={'{ "name": "My examples", "cases": [...] }'} spellCheck={false} />
        <label className="checkbox-label"><input type="checkbox" disabled={reading} checked={reviewed} onChange={event => { setReviewed(event.target.checked); }} /><span>I attest that I have reviewed these expected answers.</span></label>
        <p className="small-note">Attestation is saved as your statement and resets when contents change. An imported filename or status does not establish review.</p>
        <button className="secondary" disabled={reading || !content.trim()} onClick={() => { void importData(); }}>{busy ? 'Validating…' : reading ? 'Reading file…' : 'Validate and load'}</button>
      </fieldset>
      {success && <p className="small-note import-success" role="status">{success}</p>}
      {error && <ErrorNotice text={error} focus />}
    </div>
  </details>;
}

function DatasetSummary({ dataset, mode, liveAvailable }: { dataset: Dataset; mode: 'fixture' | 'live'; liveAvailable: boolean }) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const scripted = dataset.cases.every(ticket => ['baseline', 'candidate_1', 'candidate_2'].every(stage => typeof ticket.fixture_outputs?.[stage] === 'string'));
  return <div className="dataset-summary">
    <div className="dataset-title"><span className="dataset-mark" aria-hidden="true">▤</span><div><strong>{dataset.name}</strong><span>{dataset.cases.length} distinct examples</span></div></div>
    <dl className="split-summary"><div><dt>Development</dt><dd>{dataset.manifest.development?.length ?? 0}</dd></div><div><dt>Regression</dt><dd>{dataset.manifest.regression?.length ?? 0}</dd></div><div><dt>Final</dt><dd>{dataset.manifest.final?.length ?? 0}</dd></div></dl>
    <p className="review-label">{reviewLabel(dataset)}</p>
    {dataset.review_status === 'independently_agent_checked' && <p className="small-note">Independently agent-checked; human review is pending.</p>}
    {!dataset.full_experiment_eligible && <p className="small-note warning-text">A full experiment needs at least 40 distinct cases, including at least 10 regression and 10 final cases. This dataset remains inspectable.</p>}
    {!scripted && mode === 'fixture' && <p className="small-note warning-text">{liveAvailable ? 'Select Live inference to evaluate these examples with the configured model. Fixture simulation requires explicit baseline and candidate fixture outputs.' : 'Live inference is unavailable. To simulate this import, supply explicit baseline and candidate fixture outputs using the scripted template.'}</p>}{mode === 'live' && <p className="small-note">{dataset.source === 'demo' ? 'Synthetic demo examples. ' : ''}Live inference sends ticket text and development evidence to Nebius. Scripted fixture outputs are ignored.</p>}
    {dataset.warnings.map((warning, i) => <p className="small-note warning-text" key={i}>{warning}</p>)}
    <details className="example-preview" onToggle={event => { setPreviewOpen(event.currentTarget.open); }}><summary>Inspect examples and labels</summary>{previewOpen && <div className="example-list">{dataset.cases.map(ticket => <article key={ticket.id}><div className="ticket-meta"><strong>{ticket.id}</strong><span>{humanize(ticket.partition)}</span></div><p>{ticket.text}</p><pre>{pretty(ticket.expected)}</pre>{ticket.annotation_note && <p className="small-note">{ticket.annotation_note}</p>}</article>)}</div>}</details>
  </div>;
}

function GateStatus({ status }: { status?: ServerStatus | undefined }) {
  const enabled = Boolean(status?.live.enabled && status.live.access_confirmed && status.live.cap_confirmed);
  return <div className="gate-status"><div className="gate-heading"><span aria-hidden="true">◈</span><strong>{enabled ? 'Live inference available' : 'Live inference locked'}</strong></div><p>{enabled ? 'Select Live inference to use the configured NVIDIA model through Nebius.' : 'Nebius access and a total spending or credit-use cap both need explicit confirmation.'}</p><ul><li>Access: {status?.live.access_confirmed ? 'confirmed' : 'pending'}</li><li>Spending cap: {status?.live.cap_confirmed ? 'confirmed' : 'pending'}{status?.live.cap_usd && ` · US$${status.live.cap_usd} total`}</li>{status?.live.model && <li>Model: <code>{status.live.model}</code></li>}{status?.live.charged_or_reserved_usd !== undefined && <li>Accounted or reserved: US${status.live.charged_or_reserved_usd}</li>}</ul><span className="small-note">Cumulative provider reservations: {status ? (status.live_calls ?? 'Unavailable') : 'checking'}</span>{enabled && <p className="small-note">This local cap includes failed requests and unknown usage reservations. It is not an account-wide Nebius spending limit.</p>}</div>;
}

function PhaseProgress({ run, onCancel, cancelling, storageFailure, isActive }: { run: Experiment; onCancel: () => void; cancelling: boolean; storageFailure: StorageFailure | null; isActive: boolean }) {
  const stages = ['baseline', 'diagnosis', 'revision', 'freeze', 'regression', 'final'];
  const inactiveSnapshot = active(run.status) && !isActive;
  const inProgress = active(run.status) && isActive && !storageFailure;
  const phase = storageFailure || inactiveSnapshot ? `Last saved phase: ${humanize(run.phase)}` : humanize(run.phase);
  return <section className="run-progress" aria-label="Experiment progress"><div className="progress-heading"><div role="status" aria-live="polite" aria-atomic="true"><span className={`status-dot ${inProgress ? 'is-active' : ''}`} /><strong>{storageFailure ? 'Stopped; final status not saved' : inactiveSnapshot ? 'Not active; showing saved snapshot' : inProgress ? 'Experiment in progress' : humanize(run.status)}</strong><span className="phase-label">{phase}</span></div>{inProgress && <button className="text-button" disabled={cancelling} onClick={onCancel}>{cancelling ? 'Cancelling…' : 'Cancel experiment'}</button>}</div><ol className="phase-track">{stages.map(stage => <li key={stage} className={inProgress && (stage === 'revision' ? run.phase.startsWith('candidate_') && run.phase.endsWith('_development') : run.phase.includes(stage)) ? 'current-phase' : ''} aria-current={inProgress && (stage === 'revision' ? run.phase.startsWith('candidate_') && run.phase.endsWith('_development') : run.phase.includes(stage)) ? 'step' : undefined}>{humanize(stage)}</li>)}</ol><p className="small-note">{run.observations.length} saved observations. {storageFailure ? 'This is an earlier snapshot; the final run status could not be saved.' : inactiveSnapshot ? 'The server reports this experiment is not active. Final details have not refreshed.' : 'Phase and evidence come from the backend.'}</p></section>;
}

function Verdict({ run, storageFailure, isActive }: { run: Experiment; storageFailure: StorageFailure | null; isActive: boolean }) {
  const incompleteSnapshot = Boolean(storageFailure) || (active(run.status) && !isActive);
  const collecting = active(run.status) && isActive && !storageFailure;
  let title = 'Evidence is being collected';
  if (incompleteSnapshot && run.verdict !== 'rejected') title = 'Final status unavailable';
  else if (run.verdict === 'rejected') title = run.dataset.human_review_pending ? 'Failed check on provisional tests' : 'Candidate rejected';
  else if (collecting) title = 'Evidence is being collected';
  else if (run.verdict === 'inconclusive') title = 'No supported adoption recommendation';
  else if (run.verdict === 'eligible_for_human_review') title = 'Eligible for human review';
  else if (!active(run.status)) title = 'Experiment incomplete';
  return <div className={`verdict ${run.verdict === 'rejected' ? 'is-rejected' : ''}`}>
    <div className="verdict-icon" aria-hidden="true">{run.verdict === 'rejected' ? '×' : '◌'}</div><div><h2>{title}</h2><p>{run.execution_kind === 'Live inference' ? 'Nebius live run. Only saved provider responses count as evidence; a real run does not establish that a prompt repair succeeded.' : 'Fixture simulation. Scripted outputs demonstrate the checks; they are not measured model performance.'}</p>{((!incompleteSnapshot && !collecting) || run.verdict === 'rejected') && run.verdict_reasons && run.verdict_reasons.length > 0 && <ul>{run.verdict_reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}{run.error && <p className="warning-text">{run.error}</p>}</div>
  </div>;
}

function PromptDiff({ baseline, proposal }: { baseline: string; proposal?: Proposal | undefined }) {
  return <section className="prompt-panel"><div className="panel-heading"><h3>Prompt changes</h3><span>{proposal ? humanize(proposal.id) : 'Original prompt'}</span></div>{proposal ? <><p className="diff-key"><span>− Removed</span><span>+ Added</span><span>Unmarked lines are unchanged</span></p><div className="prompt-diff" aria-label="Prompt diff">{diffLines(baseline, proposal.prompt).map((line, index) => <div key={index} className={`diff-line diff-${line.kind}`}><span className="diff-marker" aria-hidden="true">{line.kind === 'removed' ? '−' : line.kind === 'added' ? '+' : ' '}</span><code>{line.text || ' '}</code></div>)}</div><p className="small-note hash-line">Prompt hash <code>{proposal.prompt_hash}</code></p></> : <><pre className="original-prompt">{baseline}</pre><p className="small-note">No proposed prompt is available yet. Any completed proposals remain available here if the experiment stops.</p></>}</section>;
}

function outputField(evaluation: Evaluation | undefined, key: Check): string {
  if (!evaluation) return 'Not observed';
  if (key === 'json' || key === 'schema') return evaluation.checks[key] ? 'Pass' : 'Fail';
  const parsed = evaluation.parsed;
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const record = parsed as Record<string, unknown>;
    return key in record ? pretty(record[key]) : 'Missing';
  }
  return 'Unavailable';
}
function expectedField(ticket: Ticket, key: Check): string { return key === 'json' || key === 'schema' ? 'Pass' : pretty(ticket.expected[key]); }
function CheckTable({ ticket, comparison, original, observedCandidate }: { ticket: Ticket; comparison?: Comparison | undefined; original?: Evaluation | undefined; observedCandidate?: Evaluation | undefined }) {
  const baseline = comparison?.baseline ?? original;
  const candidate = comparison?.candidate ?? observedCandidate;
  return <div className="table-scroll" role="region" aria-label="Ticket correctness checks" tabIndex={0}><table className="check-table"><caption className="visually-hidden">Expected, original and candidate values for each correctness check</caption><thead><tr><th>Check</th><th>Expected</th><th>Original</th><th>Candidate</th><th>Change</th></tr></thead><tbody>{CHECKS.map(key => {
    const lost = comparison?.regressed.includes(key); const fixed = comparison?.fixed.includes(key);
    const reason = candidate?.reasons[key] ?? (!candidate ? baseline?.reasons[key] : undefined);
    return <tr key={key} className={lost ? 'check-lost' : fixed ? 'check-fixed' : ''}><th scope="row">{CHECK_LABELS[key]}</th><td><code>{expectedField(ticket, key)}</code></td><td><span className={!baseline ? 'unobserved-value' : baseline.checks[key] ? 'pass-value' : 'fail-value'}>{baseline ? (baseline.checks[key] ? '✓ ' : '× ') : ''}<code>{outputField(baseline, key)}</code></span></td><td><span className={!candidate ? 'unobserved-value' : candidate.checks[key] ? 'pass-value' : 'fail-value'}>{candidate ? (candidate.checks[key] ? '✓ ' : '× ') : ''}<code>{outputField(candidate, key)}</code></span></td><td>{lost ? <strong className="fail-value">Lost</strong> : fixed ? <strong>Fixed</strong> : comparison ? 'Same' : 'Not compared'}{reason && <span className="check-reason">{reason}</span>}</td></tr>;
  })}</tbody></table></div>;
}

function TicketEvidence({ ticket, comparison, run, proposalId }: { ticket?: Ticket | undefined; comparison?: Comparison | undefined; run: Experiment; proposalId?: string | undefined }) {
  if (!ticket) return <div className="empty-small" role="status">No tickets match this filter.</div>;
  const original = comparison?.baseline ?? run.observations.find(observation => observation.case_id === ticket.id && observation.stage === 'baseline')?.result;
  const candidate = comparison?.candidate ?? run.observations.find(observation => observation.case_id === ticket.id && observation.stage === proposalId)?.result;
  return <article className="ticket-detail"><div className="ticket-meta"><h3>{ticket.id}</h3><span className="partition-tag">{humanize(ticket.partition)}</span>{comparison ? <span className={`change-tag status-${comparison.status}`}>{STATUS_LABELS[comparison.status]}</span> : <span className="change-tag">Not compared</span>}</div><p className="ticket-input">{ticket.text}</p>{ticket.annotation_note && <p className="annotation-note">Annotation: {ticket.annotation_note}</p>}<p className="table-scroll-help small-note">Focus the check table and use the arrow keys, or scroll horizontally, to compare all columns.</p><CheckTable ticket={ticket} comparison={comparison} original={original} observedCandidate={candidate} />{!comparison && <p className="small-note">No complete comparison is saved for this ticket in this proposal. Available observations are shown; missing observations are not counted as passing.</p>}<div className="raw-outputs"><details><summary>Expected output</summary><pre>{pretty(ticket.expected)}</pre></details><details><summary>Original raw output</summary><pre>{original?.raw ?? 'No saved observation'}</pre></details><details><summary>Candidate raw output</summary><pre>{candidate?.raw ?? 'No saved observation'}</pre></details></div><p className="small-note hash-line">Stable test hash <code>{ticket.case_hash}</code></p></article>;
}

function Evidence({ run, storageFailure, isActive }: { run: Experiment; storageFailure: StorageFailure | null; isActive: boolean }) {
  const inactiveSnapshot = active(run.status) && !isActive;
  const incompleteSnapshot = Boolean(storageFailure) || inactiveSnapshot;
  const [proposalId, setProposalId] = useState('');
  const [filter, setFilter] = useState<typeof FILTERS[number]>('all');
  const [partition, setPartition] = useState('all');
  const [ticketId, setTicketId] = useState('');
  const proposal = run.proposals.find(item => item.id === proposalId) ?? run.proposals.find(item => item.id === run.selected_candidate_id) ?? run.proposals[0];
  const selectedProposal = proposal?.id === run.selected_candidate_id;
  const comparisons = (selectedProposal ? run.comparisons : proposal?.comparisons) ?? [];
  const comparisonMap = new Map(comparisons.map(item => [item.case_id, item]));
  const partitionTickets = run.dataset.cases.filter(ticket => partition === 'all' || ticket.partition === partition);
  const scopedComparisons = comparisons.filter(item => partition === 'all' || item.partition === partition);
  const notCompared = partitionTickets.filter(ticket => !comparisonMap.has(ticket.id)).length;
  const counts = scopedComparisons.reduce<Record<ComparisonStatus, number>>((acc, item) => { acc[item.status]++; return acc; }, { fixed: 0, regressed: 0, still_failing: 0, unchanged: 0 });
  const tickets = partitionTickets.filter(ticket => filter === 'all' || (filter === 'not_compared' ? !comparisonMap.has(ticket.id) : comparisonMap.get(ticket.id)?.status === filter));
  const ticket = tickets.find(item => item.id === ticketId) ?? tickets.find(item => comparisonMap.get(item.id)?.status === 'regressed') ?? tickets.find(item => comparisonMap.get(item.id)?.status === 'fixed') ?? tickets[0];
  const lostChecks = comparisons.reduce((sum, item) => sum + item.regressed.length, 0);
  const gainedChecks = comparisons.reduce((sum, item) => sum + item.fixed.length, 0);
  const candidateQuery = proposal ? `?candidate_id=${encodeURIComponent(proposal.id)}` : '';
  return <>
    <Verdict run={run} storageFailure={storageFailure} isActive={isActive} />
    <div className="evidence-top"><div><h2>Inspect the evidence</h2><p className="small-note">Every lost field or format check counts as a regression, even inside an already failing ticket.</p></div><div className="export-actions"><a className="secondary button-link" href={`/api/experiments/${encodeURIComponent(run.id)}/export/json`} download>JSON evidence</a><a className="secondary button-link" href={`/api/experiments/${encodeURIComponent(run.id)}/export/markdown${candidateQuery}`} download>Report</a>{proposal && <a className="secondary button-link" href={`/api/experiments/${encodeURIComponent(run.id)}/export/prompt${candidateQuery}`} download>Prompt</a>}</div></div>
    {storageFailure && <p className="small-note warning-text">Downloads contain the earlier saved snapshot. The unsaved final status and any unsaved observations are not included.</p>}
    <div className="provenance-bar"><span>{run.execution_kind}</span><span>{reviewLabel(run.dataset)}</span><span>{run.prior_exposure ? 'Final assessment reused' : 'No recorded prior assessment exposure'}</span><span>Provider calls: {run.usage.live_calls}</span></div>
    <section className="model-roles" aria-label="Model responsibilities"><div><strong>Ticket extraction</strong><code>{run.model.target}</code><span>{run.execution_kind === 'Live inference' ? 'NVIDIA model extracts four ticket fields. Expected answers are withheld from extraction.' : 'Scripted ticket fields; no live model call.'}</span></div><div><strong>Prompt repair</strong><code>{run.model.repair}</code><span>{run.execution_kind === 'Live inference' ? 'NVIDIA model proposes prompt revisions using development evidence only.' : 'Scripted revisions; development evidence only.'}</span></div><div><strong>Correctness checks</strong><span>Deterministic JSON, schema and field checks against expected answers. No model grader.</span></div></section>
    <div className="assessment-row">{['development', 'regression', 'final'].map(name => { const assessment = run.assessments?.[name]; return <div key={name}><strong>{name === 'final' ? 'Final assessment' : humanize(name)}</strong><span>{incompleteSnapshot && assessment?.status === 'running' ? 'Incomplete (saved status: running)' : assessment ? humanize(assessment.status) : 'Not run'}</span>{assessment?.reason && <p>{assessment.reason}</p>}</div>; })}</div>
    {run.proposals.length > 0 ? <div className="proposal-select"><label htmlFor="proposal-select">Inspect proposal</label><select id="proposal-select" value={proposal?.id ?? ''} onChange={event => { setProposalId(event.target.value); setTicketId(''); setFilter('all'); }} >{run.proposals.map(item => <option key={item.id} value={item.id}>{humanize(item.id)}{item.id === run.selected_candidate_id ? ' — selected and frozen' : ` — ${incompleteSnapshot ? 'saved status: ' : ''}${humanize(item.status)}`}</option>)}</select>{proposal && <p className="small-note">{incompleteSnapshot && proposal.status === 'evaluating' ? 'Development qualification was not completed in this saved snapshot.' : <>Development: {proposal.development.improvements} improved checks, {proposal.development.regressions} lost checks, {proposal.development.passing_cases} fully passing tickets. {proposal.development.qualified ? 'Qualified for selection.' : 'Did not qualify for selection.'}</>}</p>}</div> : <p className="no-proposal">{storageFailure ? 'No proposed prompt is available in this saved snapshot. Earlier observations remain inspectable and exportable.' : inactiveSnapshot ? 'This saved snapshot is incomplete. Final experiment details have not refreshed.' : active(run.status) ? 'Proposals will appear after the baseline and development diagnosis.' : 'No candidate was frozen. Saved observations and errors remain exportable.'}</p>}
    {proposal && <p className="comparison-scope small-note"><strong>{humanize(proposal.id)}:</strong> {comparisons.length} of {run.dataset.cases.length} tickets have saved comparisons. {selectedProposal ? 'This is the selected and frozen candidate.' : 'This proposal was not selected; its comparisons do not change the experiment verdict.'} {comparisons.length < run.dataset.cases.length && 'Uncompared tickets are not passes.'} {active(run.status) && 'Evidence is incomplete.'}</p>}
    {proposal && <div className="comparison-totals"><span><strong>{gainedChecks}</strong> observed improved checks</span><span className={lostChecks ? 'warning-text' : ''}><strong>{lostChecks}</strong> observed lost checks</span><span><strong>{comparisons.filter(item => item.baseline.passed).length}</strong> original fully passing tickets</span><span><strong>{comparisons.filter(item => item.candidate.passed).length}</strong> candidate fully passing tickets</span></div>}
    <div className="evidence-columns"><PromptDiff baseline={run.baseline_prompt} proposal={proposal} /><section className="tickets-panel"><div className="panel-heading"><h3>Affected tickets</h3><label className="partition-filter" htmlFor="partition-filter"><span className="visually-hidden">Partition</span><select id="partition-filter" value={partition} onChange={event => { setPartition(event.target.value); }}><option value="all">All partitions</option><option value="development">Development</option><option value="regression">Regression</option><option value="final">Final assessment</option></select></label></div><div className="ticket-filters" aria-label="Filter tickets">{FILTERS.map(value => <button key={value} className={filter === value ? 'filter-button selected' : 'filter-button'} aria-pressed={filter === value} onClick={() => { setFilter(value); }}>{value === 'all' ? 'All' : value === 'not_compared' ? 'Not compared' : STATUS_LABELS[value]} <span>{value === 'all' ? partitionTickets.length : value === 'not_compared' ? notCompared : counts[value]}</span></button>)}</div><div className="ticket-picker"><label htmlFor="ticket-select">Ticket</label><select id="ticket-select" value={ticket?.id ?? ''} onChange={event => { setTicketId(event.target.value); }}>{tickets.length === 0 && <option value="">No matching tickets</option>}{tickets.map(item => { const comp = comparisonMap.get(item.id); return <option key={item.id} value={item.id}>{item.id} — {humanize(item.partition)} — {comp ? STATUS_LABELS[comp.status] : 'Not compared'}</option>; })}</select><span>{tickets.length} shown</span></div><TicketEvidence ticket={ticket} comparison={ticket ? comparisonMap.get(ticket.id) : undefined} run={run} proposalId={proposal?.id} /></section></div>
    <details className="audit-details"><summary>Diagnosis, saved progress and provenance</summary><div className="audit-grid"><section><h3>Development diagnosis</h3>{run.diagnosis?.length ? run.diagnosis.map((item, index) => <pre key={index}>{readable(item)}</pre>) : <p>No diagnosis saved.</p>}<h3>Saved progress</h3><ol>{run.events.map((event, index) => <li key={index}><pre>{readable(event)}</pre></li>)}</ol></section><section><h3>Experiment identity</h3><dl><dt>ID</dt><dd>{run.id}</dd><dt>Started</dt><dd>{new Date(run.created_at).toLocaleString()}</dd><dt>Completed</dt><dd>{run.completed_at ? new Date(run.completed_at).toLocaleString() : storageFailure ? 'Final status not saved' : inactiveSnapshot ? 'Unavailable in this snapshot' : 'Not complete'}</dd><dt>Dataset hash</dt><dd>{run.dataset.version_hash}</dd><dt>Split manifest hash</dt><dd>{run.dataset.manifest_hash}</dd><dt>Frozen candidate hash</dt><dd>{run.frozen_candidate_hash ?? 'No candidate frozen'}</dd><dt>Target / repair</dt><dd>{run.model.target} / {run.model.repair}</dd><dt>Tokens / cost</dt><dd>{run.usage.tokens} / {run.usage.cost}</dd></dl><p className="small-note">{inactiveSnapshot && !storageFailure ? 'Downloads use the server’s saved evidence and may be newer than this cached snapshot.' : 'All exports use these saved observations.'} Downloading evidence does not run inference.</p></section></div></details>
  </>;
}

export function App() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ['status'], queryFn: () => api<ServerStatus>('/api/status'), refetchInterval: 2000 });
  const demo = useQuery({ queryKey: ['demo'], queryFn: () => api<Dataset>('/api/demo') });
  const history = useQuery({ queryKey: ['history'], queryFn: () => api<HistoryItem[]>('/api/experiments'), refetchInterval: 2000 });
  const guide = useQuery({ queryKey: ['guide'], queryFn: () => api<{ markdown: string }>('/api/guide') });
  const [loadedDataset, setLoadedDataset] = useState<Dataset | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [scenario, setScenario] = useState('improvement');
  const [mode, setMode] = useState<'fixture' | 'live'>('fixture');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const storageFailure = status.data?.storage_failure ?? null;
  const discoveredActiveId = status.data?.active_experiment_id === storageFailure?.experiment_id ? null : status.data?.active_experiment_id;
  // Keep the discovered run selected after the server clears its active pointer.
  if (selectedId === null && discoveredActiveId) setSelectedId(discoveredActiveId);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const importInFlight = useRef(false);
  const datasetSelectionVersion = useRef(0);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelRequestedId, setCancelRequestedId] = useState<string | null>(null);
  const startLock = useRef(false);
  const cancelLock = useRef(false);
  const evidence = useRef<HTMLElement>(null);
  const [error, setError] = useState('');
  const dataset = loadedDataset ?? demo.data;
  const baselinePrompt = prompt ?? demo.data?.starter_prompt ?? '';
  const experimentId = selectedId ?? status.data?.active_experiment_id;
  const current = useQuery({ queryKey: ['experiment', experimentId], queryFn: () => api<Experiment>(`/api/experiments/${encodeURIComponent(experimentId ?? '')}`), enabled: Boolean(experimentId), refetchInterval: query => query.state.data?.id !== storageFailure?.experiment_id && active(query.state.data?.status) ? 500 : false });
  // Keep known activity (including idle null) authoritative across refresh errors.
  const activeIdCandidate = status.data ? status.data.active_experiment_id : active(current.data?.status) ? current.data?.id : null;
  const activeId = activeIdCandidate === storageFailure?.experiment_id ? null : activeIdCandidate;
  const selectedStorageFailure = storageFailure?.experiment_id === current.data?.id ? storageFailure : null;
  const running = Boolean(activeId);
  const cancelling = cancelBusy || Boolean(cancelRequestedId && cancelRequestedId === activeId);
  const liveAvailable = Boolean(status.data?.live.enabled && status.data.live.access_confirmed && status.data.live.cap_confirmed);
  const startDisabled = busy || importing || running || Boolean(storageFailure) || !dataset || !baselinePrompt.trim() || (mode === 'live' && (!liveAvailable || status.isError));
  const displayedKind = current.data?.execution_kind ?? (mode === 'live' ? 'Live inference' : 'Fixture simulation');
  async function startExperiment() {
    if (startDisabled || startLock.current || importInFlight.current) return;
    startLock.current = true; setBusy(true); setError('');
    try {
      const run = await post<Experiment>('/api/experiments', { baseline_prompt: baselinePrompt, dataset: { dataset_id: dataset.dataset_id }, scenario, mode });
      await queryClient.cancelQueries({ queryKey: ['status'] });
      queryClient.setQueryData(['experiment', run.id], run); setSelectedId(run.id);
      // An accepted start is newer activity evidence until the next status response.
      if (active(run.status)) queryClient.setQueryData<ServerStatus>(['status'], previous => previous ? { ...previous, active_experiment_id: run.id } : previous);
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['status'] }), queryClient.invalidateQueries({ queryKey: ['history'] })]);
      evidence.current?.focus();
    } catch (err) { setError(message(err)); }
    finally { startLock.current = false; setBusy(false); }
  }
  async function cancelExperiment(targetId: string | undefined) {
    if (!targetId || targetId === storageFailure?.experiment_id || cancelLock.current || (cancelling && cancelRequestedId === targetId)) return;
    cancelLock.current = true; setCancelBusy(true); setCancelRequestedId(targetId); setError('');
    try { const run = await post<Experiment>(`/api/experiments/${encodeURIComponent(targetId)}/cancel`, {}); queryClient.setQueryData(['experiment', run.id], run); await queryClient.invalidateQueries({ queryKey: ['status'] }); }
    catch (err) { setCancelRequestedId(null); setError(message(err)); }
    finally { cancelLock.current = false; setCancelBusy(false); }
  }
  async function loadDemo() {
    if (importInFlight.current) return;
    const selectionVersion = ++datasetSelectionVersion.current;
    const data = demo.data ?? (await demo.refetch()).data;
    if (data && selectionVersion === datasetSelectionVersion.current) { setLoadedDataset(data); setPrompt(data.starter_prompt ?? ''); setError(''); }
  }
  return <div className="app-shell"><a className="skip-link" href="#evidence" onClick={event => { event.preventDefault(); evidence.current?.focus(); }}>Skip to evidence</a><header className="masthead"><a className="brand" href="#" onClick={event => { event.preventDefault(); setSelectedId(''); }}><span className="brand-symbol" aria-hidden="true">p<span>✓</span></span>PatchProof</a><span className="brand-caption">Prompt repair, with evidence.</span><div className="masthead-status"><span className="simulation-badge">{displayedKind}</span><span className="local-label">Local workspace</span></div></header>
    <div className="workspace-intro"><div><h1>Catch what a prompt repair breaks.</h1><p>For developers changing support-ticket extraction prompts: see which fields improve, which regress, and what still needs review.</p></div><div className="contract-stamp"><strong>Support-ticket intent</strong><span>English · 4 fields · prompt-only revisions</span></div></div>
    <section className="quick-start" aria-label="Start here"><div><strong>Try the workflow</strong><ol><li>{mode === 'live' ? 'Run the loaded examples on Nebius.' : 'Run the loaded fixture.'}</li><li>Compare a changed ticket.</li><li>Inspect failures before adopting.</li></ol><p className="small-note">{dataset ? `${dataset.name} · ${mode === 'live' ? 'Live inference' : SCENARIOS.find(item => item.value === scenario)?.label ?? scenario}` : 'Loading examples…'} · {mode === 'live' ? 'Real model responses; results and failures will be saved for review.' : 'Scripted simulation; not live model performance.'}</p></div><button className="primary" disabled={startDisabled} onClick={() => { void startExperiment(); }}>{mode === 'live' ? 'Run current examples on Nebius' : 'Run current fixture'} <span aria-hidden="true">↗</span></button></section>
    <main className="workspace-layout"><aside className="setup-column" aria-label="Experiment setup"><section className="setup-section"><div className="section-title"><h2>Your test material</h2><button className="text-button" disabled={demo.isFetching || running || busy || importing} onClick={() => { void loadDemo(); }}>{demo.isError ? 'Retry demo' : 'Load demo'}</button></div>{dataset ? <DatasetSummary dataset={dataset} mode={mode} liveAvailable={liveAvailable} /> : demo.isError ? <ErrorNotice text={message(demo.error)} /> : <p className="small-note">Loading the synthetic demo…</p>}<ImportPanel disabled={busy || running} onBusyChange={value => { importInFlight.current = value; setImporting(value); }} onDataset={data => { datasetSelectionVersion.current++; setLoadedDataset(data); setError(''); }} /><details className="guide-panel"><summary>Annotation guide and contract</summary><div className="guide-content"><p className="small-note">Extract current explicit intent. Preserve clear facts; use null for missing or uncertain fields. Company policy and approvals are outside this contract.</p>{guide.data ? <pre>{guide.data.markdown}</pre> : guide.isError ? <p>{message(guide.error)}</p> : <p>Loading annotation guide…</p>}</div></details></section>
      <section className="setup-section"><div className="section-title"><label htmlFor="baseline-prompt">Original prompt</label><span>Editable example</span></div><textarea id="baseline-prompt" className="code-input prompt-input" value={baselinePrompt} maxLength={20000} onChange={event => { setPrompt(event.target.value); }} spellCheck={false} disabled={busy || running} /><p className="small-note">{mode === 'live' ? 'This prompt is sent to the configured NVIDIA model. Expected answers remain separate from ticket extraction.' : 'Fixture outputs are scripted independently of this prompt. Editing it demonstrates the workflow, not the effect of a real repair.'}</p></section>
      <section className="setup-section run-setup"><h2>Run a bounded experiment</h2><label className="field-label" htmlFor="execution-mode">Execution mode</label><select id="execution-mode" value={mode} onChange={event => { setMode(event.target.value === 'live' ? 'live' : 'fixture'); }} disabled={busy || running}><option value="fixture">Fixture simulation</option><option value="live" disabled={!liveAvailable || status.isError}>Live inference — Nebius / NVIDIA</option></select>{mode === 'fixture' && <><label className="field-label" htmlFor="fixture-scenario">Fixture scenario</label><select id="fixture-scenario" value={scenario} onChange={event => { setScenario(event.target.value); }} disabled={busy || running}>{SCENARIOS.map(item => <option value={item.value} key={item.value}>{item.label}</option>)}</select><p className="small-note">{SCENARIOS.find(item => item.value === scenario)?.description}</p></>}{mode === 'live' && <p className="small-note">{liveAvailable ? 'Live inference uses the model and cap configured on this local server. It can consume credits or incur charges.' : 'Live inference is currently unavailable. No live experiment can start until server access and spending limits are confirmed.'}</p>}<p className="bounded-note">Up to two revisions. Development-only selection. Frozen candidate. Separate regression and final checks.</p><button className="primary run-button" disabled={startDisabled} onClick={() => { void startExperiment(); }}><span>{storageFailure ? 'Restart required' : busy ? 'Starting…' : importing ? 'Validating dataset…' : running ? 'Experiment running' : mode === 'live' ? 'Run live experiment' : 'Run fixture experiment'}</span><span aria-hidden="true">↗</span></button>{error && <ErrorNotice text={error} focus />}<GateStatus status={status.data} />{status.isError && <ErrorNotice text={message(status.error)} />}</section>
    </aside><section className="evidence-column" id="evidence" aria-label="Experiment evidence" ref={evidence} tabIndex={-1}><div className="history-bar"><label htmlFor="experiment-history">Experiment history</label><select id="experiment-history" value={experimentId ?? ''} onChange={event => { setSelectedId(event.target.value); }}><option value="">New experiment</option>{storageFailure && !(history.data ?? []).some(run => run.id === storageFailure.experiment_id) && <option value={storageFailure.experiment_id}>Stopped experiment — final status not saved</option>}{activeId && !(history.data ?? []).some(run => run.id === activeId) && <option value={activeId}>Active experiment — {activeId.slice(0, 8)}</option>}{(history.data ?? []).map(run => <option key={run.id} value={run.id}>{shortTime(run.created_at)} — {run.execution_kind} — {humanize(run.scenario)} — {run.id === storageFailure?.experiment_id ? 'stopped; final status not saved' : humanize(run.status)}</option>)}</select>{current.data && <span className="history-id" title={current.data.id}>{current.data.id.slice(0, 8)}</span>}</div>{storageFailure && <div className="error-notice storage-failure-notice" role="alert"><strong>Experiment stopped; final status could not be saved</strong><p>{storageFailure.message}</p><p>Earlier saved evidence remains available. The affected run’s downloads contain its earlier saved snapshot.</p>{experimentId !== storageFailure.experiment_id && <button className="secondary" onClick={() => { setSelectedId(storageFailure.experiment_id); evidence.current?.focus(); }}>View earlier saved evidence</button>}</div>}{history.isError && <ErrorNotice text={message(history.error)} />}{current.isError && current.data && <ErrorNotice text={`Evidence refresh failed. The last saved snapshot is shown. ${message(current.error)}`} onRetry={() => { void current.refetch(); }} retrying={current.isFetching} />}{activeId && activeId !== experimentId && <div className="active-run-banner"><p role="status">An experiment is active. You are viewing {experimentId ? 'saved evidence' : 'the new-experiment workspace'}.</p><div><button className="secondary" onClick={() => { setSelectedId(activeId); evidence.current?.focus(); }}>View active experiment</button><button className="text-button" disabled={cancelling} onClick={() => { void cancelExperiment(activeId); }}>{cancelling ? 'Cancellation requested…' : 'Cancel active experiment'}</button></div></div>}{experimentId ? current.data ? <><PhaseProgress run={current.data} isActive={activeId === current.data.id} storageFailure={selectedStorageFailure} cancelling={cancelling} onCancel={() => { void cancelExperiment(current.data.id); }} /><Evidence key={current.data.id} run={current.data} isActive={activeId === current.data.id} storageFailure={selectedStorageFailure} /></> : current.isError ? <ErrorNotice text={message(current.error)} onRetry={() => { void current.refetch(); }} retrying={current.isFetching} /> : <p className="loading-state" role="status">Loading saved evidence…</p> : <div className="empty-workspace"><div className="empty-mark" aria-hidden="true"><span>−</span><span>+</span></div><h2>A proposal is only as useful<br />as the evidence beside it.</h2><p>Start with the 60-ticket synthetic demo. PatchProof will compare each field, preserve rejected proposals, and keep independent checks separate from repair.</p><div className="empty-preview"><div><span>Original prompt</span><code>Extract the customer's request.</code></div><span className="preview-divider" aria-hidden="true">/</span><div><span>Proposed repair</span><code>Keep clear facts.<br />Mark uncertainty unknown.</code></div></div><p className="small-note">{storageFailure ? 'Fixture simulation is paused until local storage is restored and PatchProof is restarted.' : mode === 'live' ? 'Live inference is selected. The synthetic demo labels still await your review; only a completed run supplies model evidence.' : liveAvailable ? 'Fixture simulation is ready. Live inference is available as a separate mode; demo labels await your review.' : 'Fixture simulation is ready. Live inference remains locked; demo labels await your review.'}</p></div>}</section></main><footer className="app-footer"><span>PatchProof</span><p>Local, single-user evidence workspace. Nothing is automatically adopted, published or deployed.</p><span>{displayedKind}</span></footer></div>;
}
