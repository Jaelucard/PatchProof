# PatchProof: model responsibilities and evidence

Current status, 29 October: optional live orchestration is implemented and has executed actual NVIDIA Nemotron requests through Nebius Token Factory. Default launches remain fixtures. The original live candidate was rejected for a lost field; a later targeted repair-instruction update returned an unchanged baseline in a development-only check. Read [LIVE-RESULTS.md](LIVE-RESULTS.md) for exact provenance and limitations. The sections below preserve the earlier fixture/preparation description.

## Historical preparation record — 22 October 2026
PatchProof helps developers inspect a proposed change to a support-ticket extraction prompt. It compares what improved, what broke and what remains wrong, then leaves adoption to the developer. The contract extracts customer intent; it does not decide refunds, apply company policy or take customer-facing actions.

**Current runtime: local fixture simulation; live spending disabled by user choice on 22 October 2026.** Optional live orchestration is implemented and tested with mock HTTP responses. It selects `nvidia/Nemotron-3_5-Lightning` for extraction and repair, but account access, model availability for this account and real inference remain unverified. Fixture results and mock tests do not establish model quality, latency or cost.

## Who does what

| Component | Current implementation | Responsibility and boundary |
|---|---|---|
| Target | Fixture: `fixture-target-v1`; optional live: `nvidia/Nemotron-3_5-Lightning` | Fixture responses come from authored scripts. The live target receives only the extraction prompt and ticket text, never expected answers. It returns JSON with a 512-token output allowance. |
| Prompt repair | Fixture: `fixture-repair-v1`; optional live: the same NVIDIA model | Live repair receives development inputs, expected answers, results and prior development proposals. It may change the prompt only, using at most two revisions with 1024 output tokens each. |
| Diagnosis | Deterministic Python code | Counts failed development checks. These categories are repair hypotheses, not explanations of a model's internal reasoning. |
| Evaluation | `strict-six-checks-v1` | Checks strict JSON, the exact four-field schema, and typed equality of `order_id`, `issue_type`, `requested_action` and `needs_review` against expected answers. No LLM judges correctness. |
| Selection and verdict | Deterministic Python code | Rejects any newly lost check; selects using development evidence; freezes the candidate; records independent results. Never adopts a prompt automatically. |

The first three fields may be `null` when unknown; `needs_review` is a JSON boolean. A correct field retains credit even when another field or the schema fails. All six checks must pass for a fully passing ticket.

## Evidence flow

1. Validate and freeze the dataset, split manifest, contract, evaluator and model configuration. The supplied demo has 30 development, 15 regression and 15 final cases.
2. Evaluate the baseline on development cases. Give only development evidence to repair; evaluate at most two revisions on that same partition.
3. A proposal qualifies only after complete development evaluation with at least one improved check and no lost checks. Select the qualified proposal with most improved checks, then most fully passing tickets; ties favor the earlier proposal.
4. Freeze the selected prompt hash before touching independent cases. Evaluate baseline and selected candidate on regression cases. If any check is lost, reject the candidate and skip final assessment. Otherwise evaluate the final partition.
5. Persist observations and comparisons; export saved evidence and prompt diffs. A rejected first proposal does not invalidate a later qualifying proposal.

Case identity binds input, expected answers, contract and evaluator, separately from prompt/configuration identity. Known scenario families stay together. Normalized input exposure is tracked across accepted runs, so renaming IDs or correcting labels does not make a previously used final case fresh.

## What a verdict establishes

A new lost check rejects the selected candidate even when its aggregate score improves. Missing observations are not passes. Without a regression, eligibility for human review still requires complete independent results, reviewed labels, fresh final evidence, sufficient coverage and real inference. The fixture demo therefore remains inconclusive even when its selected candidate loses no checks.

The dataset minimum of 40 cases, including 10 regression and 10 final cases, is an operational floor, not a statistical guarantee. Synthetic labels remain human-review pending. Family grouping and exact-input checks do not establish semantic independence or real-world generalization. English tickets, one target order and one current action are the supported scope; ambiguity should preserve clear facts and mark affected fields unknown.

## Nebius integration status

`NebiusAdapter` uses the fixed global Token Factory chat-completions endpoint. The launcher requires an explicit private key file, usable-access confirmation and an approved positive cumulative USD cap. No environment key discovery, browser credential form or browser-side authorization override exists. Default launches reject live starts with HTTP 403.

Both model roles use temperature 0, thinking disabled and `store: false`; extraction requests JSON-object output, while repair returns prompt text. The evaluator still validates the exact four-field contract. Only completions with `finish_reason: stop`, nonempty text and valid token usage are accepted. Truncation, malformed usage, unexpected model identifiers and sensitive credential material are rejected. Provider failures expose controlled messages rather than request bodies or credentials.

The cumulative sibling `provider-usage.sqlite3` ledger reserves estimated cost before transport. Its request identity is saved into the experiment before sending; receipts preserve usage, model, finish reason and latency afterward. Unknown or interrupted requests retain their reservation and block further calls until reconciled. A persisted reservation is not proof that the provider received the request. Token-based costs are estimates at frozen prices, not invoices; the byte-to-token reservation assumption is conservative but is not a provider guarantee. If reported usage exceeds the bound, the adapter records it and stops further calls. This is an application limit, not an account-wide billing limit, and it cannot control other clients or taxes.

The model's documented prices on 22 October are $0.06 per million input tokens and $0.24 per million output tokens. Pricing and settings are saved into each live experiment. The 60-case demo permits at most 150 extraction calls plus two repairs (152 total), excluding a separate access probe. Requests are sequential, with no automatic retries, tools, redirects or inherited proxies. Live limits are 60 seconds per call and 30 minutes per experiment; existing fixture limits are unchanged.

**All integration evidence so far uses MockTransport.** The user has kept spending disabled; no real key, model-catalog request or inference request was used. Authenticated catalog access would establish key/catalog access only. One bounded inference request must also succeed before claiming usable inference access. See [LIVE-SETUP.md](LIVE-SETUP.md) for the remaining steps. Human label review and fresh independent cases are still required for an adoption recommendation; the already-exposed demo remains a workflow exercise. Keep actual model failures separate from scripted examples in [FAILURES.md](FAILURES.md).

## Source map and reuse

- [providers.py](../backend/patchproof/providers.py): fixture scripts, optional NVIDIA messages, request receipts and budget boundary.
- [engine.py](../backend/patchproof/engine.py): development isolation, candidate freeze, comparisons and verdict.
- [domain.py](../backend/patchproof/domain.py): contract, deterministic evaluator, identities and partitions.
- [app.py](../backend/patchproof/app.py): saved execution provenance, server-controlled live entry point and durable request attribution.
- [REUSE.md](../REUSE.md): isolated Eval Lab derivative, preserved canonical JSON helper and MIT notice. The support-ticket workflow is purpose-specific.
