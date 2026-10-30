> Historical fixture rehearsal. The current submission demonstration should use the actual saved rejected run described in [LIVE-RESULTS.md](LIVE-RESULTS.md). A local narrated browser recording has been prepared; publication is pending. The optional live adapter is connected to orchestration and has been exercised.

# PatchProof demo: 2:40 local rehearsal

**Status: local narrated still-capture walkthrough; not published, not a live screen recording, and not a qualifying live Nebius demonstration.** Every screen is captured from the actual application using synthetic fixtures. Narration uses a local synthetic voice. There are no claimed customer results or live-model improvements.

## Capture plan and narration

Open with the dev-03 regression evidence, not a logo or title slide. Keep the first lost order ID visible in the first 30 seconds. For the final submission, replace fixture segments with authorized real-model evidence and name the actual NVIDIA model and Nebius service aloud; do not remove limitations that still apply.

### 0:00–0:25 · 01-regression

This prompt repair fixes a customer's refund request, but loses their order number. PatchProof catches that regression even though the ticket was already failing. For developers changing support ticket extraction prompts, the question is simple: what improved, and what broke? This is a local scripted demonstration, not live model inference.

### 0:25–0:45 · 02-start

Start with the included sixty synthetic tickets. One action runs the baseline, up to two prompt revisions, and separate regression and final checks. The first useful result takes only seconds in this local simulation. That timing does not predict live model latency.

### 0:45–1:10 · 03-improvement

The second candidate fixes twenty three tickets and leaves two still failing. We can inspect the original output, proposed output, expected answer, and exact changed checks. No lost checks were observed in this scripted run. PatchProof still withholds an adoption recommendation: these are fixtures, and the labels await human review.

### 1:10–1:35 · 04-models

The roles are explicit. The target model would extract four fields from each ticket. The repair model would receive development evidence and propose prompt changes. Deterministic code scores the outputs; there is no language model judge. Today, both model roles are scripted fixtures. The prepared Nebius adapter is not connected to live orchestration.

### 1:35–1:55 · 05-failure

Here is a limitation that remains visible: the customer asks for two independent remedies, but this schema has one action field. The expected answer is unknown, with human review required. The candidate incorrectly says refund. The tool reports the error; it does not claim that a higher aggregate score makes the prompt safe.

### 1:55–2:15 · 06-timeout

A simulated provider timeout stops after seven saved observations. Those observations remain available, with an incomplete verdict and no invented proposal. JSON evidence and a readable report can be exported without rerunning inference. A failed run stays a failed run.

### 2:15–2:40 · 07-close

PatchProof makes one developer decision inspectable: whether a prompt change deserves further review. Before competition submission, it still needs authorized NVIDIA inference on Nebius, reviewed labels, real failure and timing evidence, and public access. This walkthrough demonstrates the local evaluation workflow, not a qualifying live integration.

## Recording checklist

- Show the actual browser and field-level values at a legible scale. Use captions; avoid tiny whole-page screenshots.
- The included MP4 uses still captures held under narration, with a selectable English subtitle track and separate SRT. It is a rehearsal artifact; final recording should show clicks and runtime progress.
- Recheck the exact exported duration is less than 180 seconds; the target is 160 seconds.
- Use only media and code you are authorized to publish. No credentials, personal tickets or private workspace paths belong in the recording.
- Publish on YouTube only after the live-runtime, model, labels and public-access gaps are resolved and publication is approved.
- Verify the public URL while signed out, paste the exact link in Devpost, and keep the final receipt. A local MP4 or draft form is not submission evidence.

## Rehearsal versus final claims

The synthetic selected-candidate run has 23 fixed tickets, two still failing and zero observed regressions across 60 comparisons. These are authored fixture counts, not real model accuracy. The initial server execution was 3.79373 seconds; this excludes setup and user discovery. No live latency, cost, model quality or account eligibility was measured. The recorded deterministic evaluator catches dev-03 order loss and leaves final-11 action error visible.
