# PatchProof: copy for Devpost

Prepared 30 October 2026. Publication links and entrant details are tracked in [submission readiness](SUBMISSION-READINESS.md).

Published source: [Jaelucard/PatchProof](https://github.com/Jaelucard/PatchProof). Demo video: [PatchProof: Catching a Prompt Regression with Nebius and NVIDIA](https://youtu.be/97ETxB-mhGs).

## Project name

PatchProof

## Tagline

See what your prompt change fixes and what it breaks.

## Recommended track

Best Apps and Agents

## Built With

Python, FastAPI, SQLite, React, TypeScript, Vite, Nebius Token Factory, NVIDIA Nemotron 3.5 Lightning

## Inspiration

A prompt change can improve your overall score while breaking something that used to work. That is easy to miss when you are looking at an average.

PatchProof is for developers who need to decide whether a change to an extraction prompt is worth keeping. It puts the original and revised answers side by side, down to the individual field, so the decision starts with what actually changed.

## What it does

PatchProof tests prompts that extract four things from a support ticket: the order ID, issue type, requested action and whether the request needs human review. It checks the JSON, the schema and each field separately.

The app runs a baseline, asks for up to two revisions using development examples, and selects a candidate before checking it against separate regression cases. If the candidate loses a check the baseline passed, PatchProof rejects it and stops before the final assessment. A ticket that was already partly wrong can still contain a new regression.

The workspace shows prompt differences, expected and observed answers, and the cases that improved, regressed or still need attention. You can reopen a saved run or export its evidence without paying to run the model again. The decision to adopt a prompt stays with the developer.

## How it is built

The interface uses React and TypeScript, with a FastAPI backend and SQLite stores for experiment results and cumulative provider usage. NVIDIA `nvidia/Nemotron-3_5-Lightning` runs through Nebius Token Factory for both ticket extraction and prompt revision.

The extraction call sees the prompt and ticket, but not the expected answer. The repair call sees development examples and their results. Python code scores the outputs and chooses candidates using fixed checks.

Live runs use a server-side key, bounded outputs and a cumulative spending cap. Each request reserves estimated cost before it is sent, then records the returned usage. Unresolved usage stops further calls. Results remain available when live inference is switched off.

## Challenges

The hardest part was keeping a useful score from becoming a misleading one. Lost fields need to remain visible, failed requests need to stay in the record, and reused examples need to keep their exposure history.

The first real run also showed a weakness in the repair step: both proposed prompts were identical copies of the baseline with literal backslash-n text in place of line breaks. Those formatting changes were not a substantive repair, even though some model outputs changed.

## Accomplishments

The real diagnostic saved 80 extraction observations from 82 model requests, with token usage accounted for throughout. Across 30 compared cases, passing checks rose from 151 to 152 out of 180. PatchProof still rejected the candidate because it lost a previously correct requested-action field.

The failing case was a question about using a travel kettle in Japan before buying it. The baseline correctly returned `other`; the candidate changed the action to `status_update`. The ticket already had a different wrong field, but the new mistake still counted. Final assessment did not run.

The app preserved that result for inspection, including the prompt differences and raw outputs. Automated checks cover evaluation, saved history, recovery, exports and the preview's login boundary. The video walks through the saved real result in the browser.

## What we learned

A slightly higher total was not enough to justify keeping the new prompt. Seeing the lost field made that clear.

A follow-up tightened the repair instruction's formatting requirements. One additional response returned the original baseline exactly, with proper line breaks, so the operator stopped before making any new predictions. The formatting requirement worked in that response; extraction quality did not improve as a measured result.

The dataset is synthetic, with two individual human approvals and 38 delegated agent approvals. Independent human review is still incomplete, so these results are a diagnostic rather than evidence of production accuracy.

## What's next

Improve the repair proposals, handle duplicate suggestions explicitly, and complete independent human review of the expected answers. Then test whether developers can use the comparisons to make better prompt-change decisions. Any follow-up on these examples will retain their existing exposure history.

## Nebius and NVIDIA feedback

Nebius Token Factory served the NVIDIA model for both parts of the workflow. Model discovery worked, the initial JSON probe passed all six checks, and all 82 diagnostic requests finished normally with accounted token usage. The saved receipts made cost and outcomes straightforward to inspect afterward.

The main weakness in this run was the repeated formatting-only repair. Clearer instructions produced correctly formatted baseline text in one follow-up, but no substantive new proposal. JSON-object output requests were accepted. During setup, billing had to be completed before access could be checked, and the credit display needed a refresh to show the available balance.

## Existing-project work and reuse

PatchProof builds on Eval Lab's local evaluation approach and retains its MIT-licensed canonicalization helper and notice. Work in October 2026 added the support-ticket contract, checks and partitions, repair workflow, comparison interface, saved evidence, Nebius integration, real-model diagnostic and private-preview preparation. The repository's `REUSE.md` and license files document that foundation.
