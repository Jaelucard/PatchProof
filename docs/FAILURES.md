# PatchProof: failure cases and limits

**Every case below is a deliberately scripted fixture, not an observed NVIDIA or Nebius model failure.** It demonstrates how PatchProof handles bad outputs and incomplete evidence. Demo expected answers are independently agent-checked; human review remains pending. No measured prompt-repair benefit or production accuracy is claimed.

## Cases to show judges

| Case and scenario | Saved/authored output | Expected result | Why it matters |
|---|---|---|---|
| `dev-03`, candidate 1, Improvement | Baseline preserves order `7103` but says `replacement`. Candidate 1 fixes the action to `refund` and changes the order ID to `null`. | Preserve `7103` and extract `refund`. Candidate 1 is rejected for losing the order-ID check. | A repair can improve one field while damaging another inside an already-failing ticket. Aggregate improvement cannot hide this regression. |
| `dev-15`, candidate 2, Improvement | `issue_type="damaged_item"` despite the customer being unable to distinguish damage from the wrong watch. | `issue_type=null`, while retaining order `W-622`, action `replacement` and `needs_review=true`. | The selected proposal still fails to preserve uncertainty. Five correct checks do not make the case pass. |
| `final-11`, candidate 2, Improvement | `requested_action="refund"` when the customer independently requests both a refund and a replacement. | `requested_action=null`, preserving the clear order/damage fields and review flag. | The single-action contract cannot represent both remedies. This deliberately retained error appears in final assessment. |
| `reg-01`, candidate 2, Regression | The scenario injects `order_id="SCRIPTED-REGRESSION"` into an otherwise correct response. | Preserve `S-501`. Reject the selected candidate and do not run final assessment. | Independent regression evidence can overturn development qualification. |
| Provider failure scenario | The eighth prediction raises a scripted timeout after seven saved observations. | Keep seven durable observations, record the error, offer evidence/report exports and no invented candidate prompt. | Partial execution must remain inspectable without becoming a success claim. |
| Any prompt edit, fixed fixture scenario | Authored predictions remain unchanged when the original prompt changes. | Identify the run as a simulation; do not attribute output changes or gains to the prompt text. | This build demonstrates evaluation behavior, not real model response to prompt repair. |

## Reproduce in the interface

1. Load the supplied demo, choose **Improvement**, then run a fixture experiment. Inspect **candidate 1** and ticket **dev-03**. The table shows the fixed action and lost order ID together.
2. Select the frozen **candidate 2**, choose **Still failing**, and inspect **dev-15** and **final-11**. Keep the partition filter on **All partitions**, or choose the matching partition. Inspect the original/candidate raw output if needed.
3. Choose **Regression** and run again. Inspect **reg-01**: the order-ID check is lost and final assessment is marked not run. The reused-final warning on later runs is expected and must remain visible.
4. Choose **Provider failure** and run again. Confirm seven saved observations, the timeout, no frozen candidate and no prompt download. Export the saved JSON or report.
5. To demonstrate fixture independence, rerun Improvement with a changed original prompt and compare saved predictions. Ignore run IDs, timestamps and prompt hashes when comparing; those should differ. Reused assessment is correctly flagged.

The scenario selector affects the currently loaded data. Use the supplied demo for the exact IDs above. A normal custom upload has no predictions; fixture runs require explicit scripted outputs and do not invent them.

## How to interpret the improvement example

The selected-candidate comparison reproduced through local HTTP on **22 October 2026** covers 60 tickets: 23 fixed, 2 still failing, 35 unchanged and 0 regressed. That is 44 improved checks and no lost checks. Candidate 1 is separately rejected; its development regression is not silently charged to candidate 2. These counts describe authored fixture behavior only and are not a model benchmark.

The outcome remains **No supported adoption recommendation** because the run is simulated and labels need human review; repeated final cases add a reuse limitation. Even a later live run can establish only the measured coverage, not safety for unseen production traffic.

## Current reproduction receipt

These runs used an isolated local review database, without provider inference. See the [saved validation receipt](evidence/fresh-validation.json).

| Scenario / run ID | Saved observations | Result | Server execution |
|---|---:|---|---:|
| Improvement / `a6a28316-6a87-4141-bca1-fc74ff00c693` | 150 | Inconclusive; two still-failing tickets | 3.794 s |
| Regression / `99bac995-bb0f-4ef8-b040-3a2a4ab9db4c` | 120 | Rejected; one regressed ticket; final not run | 2.740 s |
| Provider failure / `de2cda29-678a-4074-950d-b10befe05f39` | 7 | Error/inconclusive; no selected candidate | 0.148 s |

All three report **zero live provider calls**. The latter two correctly record prior assessment exposure from the earlier run; they are not fresh holdout evaluations. Server durations exclude navigation, reading and rendering, and are not user time-to-value measurements. The timeout is injected immediately on the eighth call, not a measurement of a real provider's timeout latency. Prompt-edit independence is established by the fixture source; it was not separately rerun in this receipt.

## Remaining evidence to collect

- **Live model failures:** none verified. After authorized integration, retain model ID, prompt/configuration, input, raw response, expected answer, failed checks, repeat behavior, latency and usage for each observed failure. Do not relabel these scripted failures as live evidence.
- **Human label review:** pending, especially ambiguous actions and the distinction between missing information and record-only messages. A checkbox records an attestation; it does not perform review.
- **User value:** no target-user study is documented here. Ask support-tool developers to find the reason a proposal was rejected and decide what evidence they need before adoption; record time and confusion.
- **Runtime limits:** local single-user/single-process application; public hosting, authentication and multi-user isolation are not implemented. Infrastructure reliability checks do not establish semantic extraction quality.

Source: [demo.json](../data/demo.json), [independent label review](../data/independent-label-review.md), [FixtureProvider](../backend/patchproof/providers.py), [evaluator](../backend/patchproof/domain.py) and [orchestrator](../backend/patchproof/engine.py). See [TECHNICAL.md](TECHNICAL.md) for model responsibilities and the live-provider boundary.
