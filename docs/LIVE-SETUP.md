# PatchProof live setup and current access status

Current status, 29 October: billing and promotional credit were verified, the authenticated NVIDIA catalog and bounded probe succeeded, and a fixed live diagnostic completed with a rejected candidate. A later instruction-only follow-up returned the unchanged baseline and stopped before predictions. Live access is now disabled for saved-result review. [LIVE-RESULTS.md](LIVE-RESULTS.md) records actual requests, costs, failures and limits. Future live calls still require an explicitly provisioned private key, confirmed credit/cap and the same cumulative ledger. The historical setup checklist below is not the current access status.

## Historical preparation record — 22 October 2026
Checked 22 October 2026. **Spending remains disabled by the user's explicit choice.** No real credential was read, authenticated model listing performed, inference sent, credit consumed or billing change made. A US$2 cap was recommended, but was not approved. The current launcher runs without live options.

## Account status

Account access, login method, credit redemption and current balance remain unverified. The console was inspected signed out. Hackathon registration does not establish a separate Token Factory account. Complete sign-in and inspect the actual organization/project before asserting usable access. See the [Token Factory console](https://tokenfactory.nebius.com/).

## Prepared model connection

- Model: `nvidia/Nemotron-3_5-Lightning`, used for both extraction and at most two prompt revisions.
- Endpoint: `https://api.tokenfactory.nebius.com/v1/chat/completions`.
- Extraction sees only the prompt and ticket text. Repair sees only development examples, labels and results. Neither changes labels, partitions or evaluator rules.
- Extraction requests JSON and at most 512 output tokens; repair requests text and at most 1024. Both disable thinking, use temperature 0 and set `store: false`.
- Deterministic code evaluates the four-field schema and expected values. There is no model grader and no automatic prompt adoption.
- Fixed price metadata, checked 22 October: US$0.06 per million input tokens and US$0.24 per million output tokens. Verify pricing and exact model availability again before enabling requests.

Official references: [Nebius NVIDIA models/pricing](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference), [chat API](https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion), [JSON output](https://docs.tokenfactory.nebius.com/ai-models-inference/json), [NVIDIA model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16).

## Budget behavior

The recommended initial US$2 total would include credits, cash, the access probe and failed requests. It is a cumulative local inference reservation limit, not a Nebius account-wide hard cap. It cannot control other applications, provider pricing changes, billing adjustments or taxes. Nebius's billing threshold triggers card charges; it is not a spending limit. [Billing documentation](https://docs.tokenfactory.nebius.com/other-capabilities/billing-new)

A request reserves cost transactionally before transport, using message bytes plus framing allowance as a conservative input-token assumption and a fixed output allowance. Confirmed token usage reconciles that reservation at the saved prices. A pending, unknown or excessive usage record blocks further requests, even after restart. Unknown requests never silently become free. Reported usage beyond the assumed bound is recorded and stops further requests; an unexpectedly billed request cannot be undone by the app.

The existing review database is `work/review.sqlite3` in the 22 October task directory, with its sibling `work/provider-usage.sqlite3`. Keep both files and the same directory for the later evaluation. A new directory creates a separate ledger; it must not be used to reset the approved total. The existing demo has already been exposed by fixture runs, and its expected answers remain human-review pending.

The 60-case demo permits at most 152 inference requests: 150 predictions and two repairs, plus a separately approved access probe. Requests are sequential, with no automatic retries. Each has a 60-second elapsed limit, and an experiment has a 30-minute limit. Actual time and cost remain unmeasured.

## Remaining access and execution steps

1. Complete the intended Nebius sign-in and inspect whether an organization/project already exists. Record the chosen Google/GitHub/SSO identity only once observed. Complete personal verification or billing details directly; do not put them in chat.
2. Inspect credit balance and Transactions. The Devpost credit offer is not proof of redemption. Confirm any account-country blocker honestly rather than substituting a different billing country.
3. Choose and explicitly approve the cumulative inference cap. Spending remains off until this happens.
4. Create a restricted Token Factory API key if necessary, and save it outside the app/source/output folders as a private regular file owned by the user, mode 600, containing only the raw key. Give the assistant only its path. No key should appear in chat, command-line arguments, source, evidence or video.
5. Verify the exact model in the authenticated catalog. Catalog access alone does not establish inference/billing access. Run one bounded synthetic extraction probe through the same cumulative ledger, retaining sanitized usage and finish-reason evidence. Stop if it fails; do not retry automatically.
6. Run the full workflow against the existing review database. Save actual input/output, selected candidate, failures, request receipts, elapsed times and token-based estimated costs. The provisional, previously exposed demo cannot establish a fresh independent accuracy claim.
7. Review failures and labels; prepare genuinely fresh independent cases before an adoption claim. Replace fixture-only public-demo material with observed live operation, keeping the final video below 180 seconds.

## Explicit opt-in launcher, for after approval

The ordinary launcher remains fixture-only. The prepared optional flags are:

```text
--live-key-file /absolute/path/to/private/raw-key-file
--live-cap-usd APPROVED_CUMULATIVE_USD_AMOUNT
--confirm-nebius-access
--confirm-live-cap
```

These are operator assertions, not proof of provider verification. They must reflect actual user approval and access evidence; none were supplied in this session. Startup reads only the exact supplied file after validating both confirmations. There is no automatic credential discovery or startup provider call. The browser then requires an explicit selection of live mode; fixture mode remains the default.

## Validation and limitations

The full suite passed 303 backend tests; after two evidence-wording fixes, 20 focused backend tests passed, including a new reserved-but-unsent request case. All 60 frontend tests, Ruff, TypeScript, lint and production build passed. The HTTP transport was mocked for all live-path tests. The tested workflow saved 152 mocked request receipts and 150 observations while preserving provisional labels and prior exposure. Those are integration checks, not provider execution evidence.

The real local server was checked with no live configuration: the live option is disabled, a live start returns HTTP 403 and the cumulative provider-call count is zero. Security source review found no actionable issues. No public deployment, repository publication, video upload or Devpost submission occurred.
