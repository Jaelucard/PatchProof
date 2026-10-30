# PatchProof

See what your prompt change fixes and what it breaks.

PatchProof helps developers review changes to support-ticket extraction prompts. It compares the original and revised answers field by field, keeps failures visible, and saves the evidence behind the result.

A real NVIDIA-on-Nebius diagnostic showed why that matters: the overall score went up by one check, but the candidate lost a field the baseline got right. PatchProof rejected the candidate and stopped before final assessment.

## How it works

1. Evaluate the original prompt against development examples.
2. Ask for up to two prompt revisions using development evidence.
3. Select and freeze a candidate before separate regression checks.
4. Reject the candidate if it loses any previously passing check. Run final assessment only if the regression checks pass.
5. Inspect the prompt differences, individual answers and saved JSON or readable report before deciding whether to adopt a change.

The contract covers `order_id`, `issue_type`, `requested_action` and `needs_review`. Python code checks strict JSON, the exact schema and each field. NVIDIA `nvidia/Nemotron-3_5-Lightning`, served through Nebius Token Factory, performs extraction and proposes revisions. Expected answers are withheld from extraction calls.

## What the real run found

| Measure | Saved result |
|---|---|
| Model requests | 82, all with accounted usage |
| Extraction observations | 80 |
| Cases compared | 30 |
| Passing checks | 151 → 152 out of 180 |
| Verdict | Rejected: one previously passing check was lost |
| Final assessment | Not run |

For a prepurchase question about a travel kettle in Japan, the baseline correctly extracted the action as `other`. The candidate changed it to `status_update`. That new error counted even though the ticket already had another wrong field.

Both proposed prompts were identical formatting-only changes. A later instruction follow-up returned the original baseline with proper line breaks and stopped before new predictions. These runs do not demonstrate improved extraction quality. The 40-ticket dataset is synthetic and has two individual human approvals plus 38 delegated agent approvals; independent human review remains incomplete.

Read the [results and limits](docs/LIVE-RESULTS.md), inspect the [saved JSON](docs/evidence/live-diagnostic-2026-10-29.json), or watch the [52-second browser demonstration](demo/PatchProof-live-evidence-draft.mp4). The video reviews the saved result, with synthesized English narration and captions.

## Run locally

Use Python 3.13 on a POSIX system. The verified local environment is macOS arm64 with Python 3.13.5. The compiled interface is included, so Node is optional unless you rebuild or run frontend tests.

From the repository root:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r python-runtime-lock.txt
PYTHONPATH=backend .venv/bin/python -B -m patchproof --database .local/patchproof.sqlite3 --port 8766
```

Open **http://127.0.0.1:8766** and choose **Run current fixture**. This starts a scripted demonstration without using provider credits. It shows the workflow; editing the prompt does not change the fixture's scripted outputs. Stop the server with Ctrl+C and use the same command to reopen its saved history.

See the [judge quickstart](JUDGE-QUICKSTART.md) for a walkthrough and setup details. A new local database does not automatically contain the historical real run. The [password-protected preview](deployment/preview/README.md) seeds that saved result and uses fixtures for new runs.

## Live inference and judge access

Live inference requires an explicitly configured server-side Nebius key, confirmed access and a cumulative usage cap. Requests have bounded outputs, no automatic retries and durable usage receipts. See [live setup](docs/LIVE-SETUP.md).

The current local review preview is password protected and fixture-only. The [Render deployment package](deployment/hosted/README.md) is prepared and locally tested, with public hosting awaiting account setup and billing confirmation. It preserves the complete experiment history and original usage ledger, and refuses normal startup if either database is missing. The judge workspace is shared; use synthetic tickets only.

## Verify the build

The 30 October checks passed **430 backend tests**, **60 frontend tests**, **127 local-preview Docker/HTTP checks** and **42 hosted-container Docker/HTTP/lifecycle checks**, plus lint, type checks, shell syntax and the production build. The targeted development-dependency update also passed `npm audit` with zero reported vulnerabilities. The automated provider tests use mocks; actual Nebius results are documented separately. Render's actual disk mounts, public proxy and funded activation still need deployment verification. See the [hosting preparation receipt](docs/evidence/hosting-preparation-2026-10-30.json).

```sh
.venv/bin/python -B -m pytest -q
.venv/bin/ruff check backend tests deployment
sh -n deployment/preview/gateway-entrypoint.sh
cd frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

Frontend checks require Node `^22.22.2`, `^24.15.0` or `>=26.0.0`. The verified environment used Node 26.7.0 and npm 11.19.0. Tests used existing environments and cached images; an empty-cache installation and other platforms have not been verified.

## Read more

- [Architecture and model responsibilities](docs/TECHNICAL.md)
- [Failure examples](docs/FAILURES.md)
- [Submission story](docs/SUBMISSION-DRAFT.md)
- [Current submission readiness](docs/SUBMISSION-READINESS.md)

## License and reuse

PatchProof is MIT licensed. It builds on Eval Lab's local evaluation approach and retains its canonicalization helper and original notice. See [LICENSE](LICENSE), [REUSE.md](REUSE.md) and [third-party notices](THIRD-PARTY-NOTICES.txt).
