# PatchProof: real Nebius testing results

Verified 29 October 2026, China/Singapore time. These are actual NVIDIA model calls through Nebius Token Factory, using synthetic tickets. The original experiment was rejected. No prompt was adopted, and the final assessment was not run.

## What ran

| Item | Observed result |
|---|---|
| Provider/model | Nebius Token Factory / nvidia/Nemotron-3_5-Lightning |
| Original experiment | ba2420e6-2691-47a2-b993-18c35e1c1955 |
| Original run time | 29 October, 01:38:21–01:40:42 China time |
| Defined elapsed time | 141.469187 seconds, experiment started_at to completed_at |
| Original run requests | 82 completed, accounted requests; HTTP 200 and finish reason stop |
| Original observations | 80: 60 development predictions and 20 regression predictions |
| Original tokens | 26,514 input + 3,424 output = 29,938 |
| Original estimated cost | US$0.00241260 |
| Access probe | 1 request, 183 tokens, all six checks passed, estimated US$0.00001818 |
| Instruction follow-up | 1 repair request, 12,059 tokens, estimated US$0.00074298; 0 new predictions |
| All testing combined | 84 accounted requests, 42,180 tokens, estimated US$0.00317376; 0 unknown usage |
| Usage limits | US$1 initial cumulative app cap within the user's US$24.50 ceiling and available promotional credit |

Costs are estimates from provider-reported tokens and saved prices, not invoices or an account-wide billing cap. Actual account debit may include tax and billing timing. All usage retained the same cumulative ledger; it was not reset.

## Why the original candidate was rejected

Candidate 1 was selected using development evidence and frozen before regression assessment. Candidate 2 was discarded. Both proposed prompts were byte-identical and equal the baseline with actual newline characters replaced by literal backslash-n separators. This is a formatting-only proposal, not evidence of a successful semantic repair strategy or a causal accuracy gain.

| Partition | Compared cases | Passing checks, baseline to candidate | Improved / lost checks | Fully passing tickets |
|---|---:|---:|---:|---:|
| Development | 20 of 20 | 104 to 105 of 120 | 1 / 0 | 8 to 8 |
| Regression | 10 of 10 | 47 to 47 of 60 | 1 / 1 | 2 to 3 |
| Final | 0 of 10 | Not run | Not assessed | Not assessed |

Across the selected candidate's 30 observed comparisons: 2 fixed tickets, 1 regressed, 17 still failing and 10 unchanged. The aggregate passing-check count rose from 151 to 152 of 180. That did not override the regression rule.

The instructive case is pp40-020: a customer has not bought anything and asks which adapter a travel kettle needs in Japan. The expected requested_action is other. The baseline returned other; the selected candidate returned status_update, losing a previously correct check. Both outputs already had the wrong needs_review=true, so this is a lost correct field inside an already-failing ticket. PatchProof rejected it and stopped before final assessment.

JSON export, terminal snapshot and the durable saved experiment were independently checked as identical. Saved failures and incomplete coverage were retained.

## Targeted instruction change and bounded follow-up

A targeted Nebius repair-instruction change was made. It requests concrete development-supported extraction rules, direct prompt text with actual line breaks, no formatting-only copy or repetition of previous proposals, and an unchanged baseline when no justified substantive change exists. It preserves the fixed contract, untrusted-ticket boundary and development-only inputs. Returned model bytes are not normalized. Engine behavior, UI, scoring, partitions, token limits and retries remain unchanged.

At the instruction-patch milestone, before preview work, four new focused mock cases brought the complete checks to 308 backend tests and 60 frontend tests, Ruff, TypeScript, lint and production build. The operator helpers additionally passed 14 probe mocks and 7 follow-up mocks. Fresh source review found no actionable issue in the narrow instruction patch. This does not establish a complete security scan.

Follow-up 188da207-c77d-4b52-a28e-d41dfa307550 used only the original 20 development cases and filtered development results. It sent one repair request and returned the original baseline unchanged: five actual newlines, zero literal backslash-n separators. The requested direct-text format was observed in this response; no substantive new repair was proposed. The external one-shot operator stopped before all 20 optional predictions because the prompt hash matched the baseline. No retry, regression or final call occurred. Follow-up elapsed time was 2.545968 seconds.

The skip belongs to the operator check. A shared engine duplicate/no-change guard was not implemented, under the instruction-only scope. Exact old/new instruction text and source hashes are retained separately; old experiment metadata and results were not rewritten.

## Interpretation and remaining work

The label record remains two individual human approvals and 38 delegated agent approvals, with human_review_pending=true. Inputs are synthetic and the development examples are now reused. No fresh-holdout, production accuracy or prompt-adoption claim follows from these results. The final partition remains untested because the original regression gate failed; follow-up scope did not reopen it.

Live server mode is disabled for review of saved results. Credentials are excluded from source, exported evidence and the local video.

The local narrated screen-recording draft reviews the actual saved run without new inference. It is not a published YouTube video and its duration is not the experiment's runtime. Public repository/build/video URLs, final entrant details, entrant feedback, publication approval and Devpost submission remain pending.

Official rules: https://nebiusglobalaihackathon.devpost.com/rules

## Authenticated local preview verified — 30 October

See [deployment/preview](../deployment/preview/README.md) for the additive fixture-only review gateway. The approved landing-page navigation exception passed 127 real Docker/HTTP checks, including 46 navigation cases. Full checks passed 374 backend / 60 frontend tests, Ruff, shell syntax, TypeScript, lint and build. A focused security review found no actionable issue in the navigation delta.

Chrome sign-in, landing/workspace access, saved-result review and JSON/report downloads succeeded. The downloaded original JSON matched the saved evidence. A new 150-observation fixture completed with zero provider reservations, and history remained after reload. A separate-site link reached the landing page with a cached login; cross-site API navigation and a form POST remained blocked. This local review made no model calls. Public TLS, funded live judge access and publication remain pending.
