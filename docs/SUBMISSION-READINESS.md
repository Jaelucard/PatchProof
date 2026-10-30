# PatchProof submission readiness

Updated 30 October 2026.

The [public repository](https://github.com/Jaelucard/PatchProof) contains the runnable app, MIT license, saved NVIDIA-on-Nebius evidence, tests and a short browser demonstration. The hosted judge service, public YouTube video and final Devpost entry are still pending. This page records preparation and verification; it is not a submission receipt.

## What is ready

| Requirement | Current evidence |
|---|---|
| Public source and license | Published at [Jaelucard/PatchProof](https://github.com/Jaelucard/PatchProof), with MIT and reuse notices. Anonymous access was verified. |
| Actual Nebius and NVIDIA use | A saved diagnostic used `nvidia/Nemotron-3_5-Lightning` through Nebius Token Factory: 82 requests and 80 extraction observations. |
| Understandable result | The candidate gained one passing check overall but lost a previously correct field. It was rejected and final assessment was skipped. |
| Runnable local build | The compiled interface is included. [Judge instructions](../JUDGE-QUICKSTART.md) explain the fixture workflow and saved evidence. |
| Hosted deployment package | A protected Render deployment is prepared. Its local checks cover authentication, persistent state, cumulative accounting and process shutdown. Actual Render deployment verification remains outstanding. |
| English submission story | [Devpost copy](SUBMISSION-DRAFT.md), architecture, limitations and observed tool feedback are prepared. |
| Short video | A 52.109-second browser recording reviews the saved real result, with synthesized English narration and English captions. Public YouTube publication remains outstanding. |
| Development dependencies | The targeted dependency refresh passed the frontend checks and `npm audit` with zero reported vulnerabilities. |

See the [README](../README.md) for the current test counts and commands, [live results](LIVE-RESULTS.md) for the real-model evidence, and [hosted deployment instructions](../deployment/hosted/README.md) for deployment controls.

## What the evidence does and does not show

The real run demonstrates why individual regressions matter even when an aggregate score improves. Both proposed prompts were identical formatting changes. The later instruction follow-up returned the original baseline and stopped before new predictions. Neither run establishes improved extraction quality.

The 40-ticket dataset is synthetic. It has two individual human approvals and 38 delegated-agent approvals; independent human review remains incomplete. The recorded exposure history must be preserved, and these cases must not be presented as a fresh holdout. All judges share the hosted workspace, so its instructions require synthetic tickets only.

The local preview and hosted-container checks make no new model requests. The hosted runtime preserves the complete original database and cumulative usage ledger. Its initial transfer is fixture-only, and normal startup refuses a missing database rather than restoring an older spending record. Public TLS, platform mounts, server-side credentials and one bounded funded smoke test must still be verified on Render.

## Remaining submission steps

1. Complete Render account setup and resolve hosting-budget controls. Deploy one service with persistent storage, then verify login, public HTTPS, exports, restart persistence and bounded live inference.
2. Publish the prepared video on YouTube with English captions and verify public playback. Add the verified URL to the repository and submission.
3. Confirm the actual Devpost entrant/team details, eligibility, track and required declarations. Transfer the reviewed wording and verified links into the entry. Use private testing instructions for the judge login; keep provider credentials out of all public materials.
4. Review and submit the completed entry, then retain the project URL, timestamp and submitted-status receipt.

The recommended track is **Best Apps and Agents**; the selection has not been verified in the actual form. Component reuse is documented in [REUSE.md](../REUSE.md). No independent user trials or adoption outcomes are claimed.

## Submission and access dates

The [official rules](https://nebiusglobalaihackathon.devpost.com/rules), checked on 30 October, give a submission deadline of **31 October 2026 at 01:00 China/Singapore time** (30 October, 10:00 PDT). Free judge access must remain available through **24 December 2026 at 04:00 China/Singapore time** (23 December, noon Pacific).

The rules require actual Nebius runtime use with an NVIDIA open model, public licensed source, a working demo or test build, English materials, tool feedback and a public YouTube video shorter than three minutes. The [FAQ](https://nebiusglobalaihackathon.devpost.com/details/faqs) permits hosting the rest of the app elsewhere. The [organizer's submission guidance](https://nebiusglobalaihackathon.devpost.com/updates/46205-how-to-build-a-winning-project) provides presentation advice.
