# PatchProof: 160-second submission demonstration plan

Updated 30 October 2026. **Local recording draft captured; not reviewed for final submission or published.** A real browser-tab recording of clicks through the saved rejected Nebius run lasts **52.109 seconds** and required no additional inference. The narrated MP4 draft is encoded at [PatchProof-live-evidence-draft.mp4](../demo/PatchProof-live-evidence-draft.mp4), with [English captions](../demo/captions.srt); encoding and full decode validation passed at 52.109 seconds; final editorial review remains before publication. The optional **2:40** plan below remains available for a longer presentation. Every final export must be **less than 180 seconds**.

## Evidence to use

Use saved experiment **`ba2420e6-2691-47a2-b993-18c35e1c1955`**, completed on 29 October at 01:40:42 China time. It used NVIDIA **`nvidia/Nemotron-3_5-Lightning`** through **Nebius Token Factory**. It contains 80 extraction observations and 82 accounted model requests, two byte-identical formatting-only proposals, a selected/frozen candidate and a **rejected** verdict. **Final assessment was not run because regression assessment failed.**

The opening example is **`pp40-020`**, a prepurchase question about a travel kettle in Japan. Expected requested action: `other`. Baseline: `other`. Selected candidate: `status_update`. Both already have the wrong `needs_review:true`, demonstrating a lost correct field inside an already-failing ticket.

## Separate instruction-only follow-up

The captured 52-second draft reviews the original rejected run. Report the later follow-up separately; do not imply the footage is a rerun after the patch. Follow-up `188da207-c77d-4b52-a28e-d41dfa307550` used one repair request on reused development evidence and returned the exact original baseline, with five actual line breaks and zero literal backslash-n separators. The operator stopped before all new predictions. There were zero new development observations, regression calls or final calls, and no extraction-quality gain was established. Shared engine duplicate handling remains unimplemented.

The follow-up added 12,059 tokens and US$0.00074298 estimated cost. All testing now totals **84 accounted requests, 42,180 tokens and US$0.00317376 estimated**, with zero unknown usage. The original experiment and its rejection are unchanged. At the instruction-patch milestone, complete checks passed **308 backend and 60 frontend tests**, plus lint/type checks/build; separate helpers passed 14 probe and 7 follow-up mock tests. The current preview-stage checks are recorded below.

## Before final review or an optional longer recording

1. Open the saved live experiment in the app's history. Live mode is disabled for review. Do not start another paid run merely to obtain recording footage or a more impressive result. Use the saved real outputs and retained live-progress capture from this exact experiment.
2. Check the fixed 20-development / 10-regression / 10-final manifest and mixed review provenance. The completed run assessed development and regression; the ten final cases were not run. Keep that distinction visible.
3. Keep the actual response receipts, terminal status, comparison summary, prompt hash, token-based estimated cost and recorded timestamps with the final evidence package. Preserve the formatting-only proposal limitation and the rejected verdict.
4. Open the source/test-build instructions. Public repository and judge-access URLs still need publication and verification before the closing caption can claim they are available.
5. Record only the app and safe evidence. Hide account/billing pages, keys, private filesystem paths, browser bookmarks, personal tabs and notifications. Use the synthetic tickets already in the run; exclude personal customer data.

Use actual clicks while inspecting saved live evidence. If inserting the retained progress capture, label it **“Recorded live progress: same experiment”**; if cutting across elapsed run time, label **“Later: saved result from the same run.”** Keep the experiment identity consistent. Do not imply the edited video measures the run's elapsed time. The captured browser interaction is a recording of saved-result review, rather than footage of a new inference start. Encoding, narration/caption timing and final publication review still require completion; no public YouTube URL exists.

## Shot and narration plan

The narration below uses observed facts and is ready to rehearse. Only the final public-link sentence remains conditional on publication.

### 0:00–0:25: Lead with the actual lost field

**Screen:** Select `pp40-020` in the saved live experiment. Enlarge the expected, baseline and candidate requested-action values. Show Live inference provenance and the model name.

**Narration:**

“This customer asks which adapter a travel kettle needs in Japan, before buying anything. The original correctly returns ‘other’; the proposed prompt returns ‘status update.’ PatchProof catches that lost field and rejects the proposal. These are saved NVIDIA Nemotron outputs from Nebius Token Factory.”

### 0:25–0:50: Explain the completed workflow

**Screen:** The same experiment's history, timestamps, partition coverage and progress record. A clearly labeled retained progress capture may be inserted; do not perform a new inference start.

**Narration:**

“PatchProof evaluates a fixed set of forty synthetic tickets. It checks the baseline and at most two proposals on development examples, then freezes a selected candidate before separate regression checks. This run stopped before final assessment because a regression was found. Nothing is automatically adopted.”

### 0:50–1:15: Explain responsibilities and the proposal limitation

**Screen:** Model roles, prompt difference and the two identical proposal hashes. Make the literal backslash-n formatting change readable.

**Narration:**

“NVIDIA Nemotron performs extraction and proposes prompts through Nebius Token Factory. Extraction never receives the expected answer; repair sees development evidence only. Python code grades the outputs. Here, both proposals were identical formatting changes, not a substantive repair. We retain that limitation rather than claiming a better strategy.”

### 1:15–1:45: Show why the verdict matters

**Screen:** The selected candidate's totals, partition coverage and Rejected verdict, followed by the failed requested-action check.

**Narration:**

“Across thirty compared cases, two were fixed, one regressed, seventeen still failed and ten were unchanged. Passing checks rose from 151 to 152, but that aggregate gain did not override a lost correct field. Final assessment was not run. The labels have mixed human and delegated-agent review, so this is a synthetic diagnostic, with no production accuracy or adoption claim.”

### 1:45–2:05: Make the rule tangible

**Screen:** In `pp40-020`, point to both the already-wrong `needs_review` field and the newly lost requested-action field. Keep baseline and candidate values side by side.

**Narration:**

“This ticket was already failing its review flag. The original still got the requested action right. A repair must preserve that correct field too. PatchProof keeps both failures visible and rejects the candidate, even inside an already-failing ticket.”

### 2:05–2:25: Show usable saved output

**Screen:** Export the saved JSON or Markdown report and open it. Point to the model, coverage, verdict and usage. Use an actual saved export; hide private filesystem paths.

**Narration:**

“The report preserves the prompt, observations and limitations. The diagnostic completed 82 model requests and recorded 29,938 tokens, at an estimated cost of about a quarter of one US cent. Its recorded start-to-completion interval was 141 seconds. The JSON export matches the saved experiment, so review needs no repeated inference.”

The precise original diagnostic cost is **US$0.00241260**; its separate access probe brings that subtotal to **US$0.00243078**. The later instruction-only follow-up brings all testing to **US$0.00317376**, with 84 accounted requests and 42,180 tokens; no new predictions were made in that follow-up. Cost is a token-based estimate, not an invoice. The diagnostic time excludes onboarding, the access probe and later review. Put those definitions in captions if the figures are shown.

### 2:25–2:40: Close on the developer decision

**Screen:** Return to the actual regression and Rejected verdict. End with the final source and test-build route once published and verified.

**Narration:**

“PatchProof makes a prompt change reviewable: what improved, what broke and what evidence is missing. It uses NVIDIA Nemotron through Nebius Token Factory, with deterministic checks and a human decision at the end.”

**Publication-dependent final sentence:** “The public source and runnable test build are linked in the submission.” Use it only when those links are public and tested; otherwise this remains a rehearsal.

## Final recording and publication checks

- Review the existing 52.109-second actual browser interaction capture and its encoded narrated draft for legibility, narration/caption timing and final duration. The earlier still-capture fixture MP4 is a separate artifact. Use the optional longer plan only if another presentation is useful; do not start more inference for footage.
- Keep the experiment identity consistent through edits. Mark any elapsed-time cut or inserted progress capture. No scripted fixture segment is needed for the actual `pp40-020` regression.
- Say **Nebius Token Factory** and **NVIDIA Nemotron 3.5 Lightning** aloud. Include both in Devpost's description and Built With list.
- Retain the formatting-only proposal limitation, mixed label-review provenance and skipped final assessment. Do not attribute the observed gains causally to a substantive repair.
- Use only media, code and examples the entrant has rights to publish. Avoid billing, profile, API-key and private console screens.
- Check the final file's actual duration is below 180 seconds, with no clipped narration or unreadable tables.
- After the user authorizes publication, use a **public YouTube** video. Verify signed-out playback, copy the exact URL and preserve the published result. A local file, upload draft or unlisted link is not evidence of the required public video.
- Check the public repository and runnable build from the final links and keep them free and unrestricted for judging through **24 December 2026 at 04:00 China/Singapore time**.
- Submit before **31 October 2026 at 01:00 China/Singapore time** and retain the Devpost receipt. Runtime evidence does not by itself guarantee eligibility or acceptance.

Source requirements: [official rules](https://nebiusglobalaihackathon.devpost.com/rules), [official FAQ](https://nebiusglobalaihackathon.devpost.com/details/faqs) and [organizer's packaging guidance](https://nebiusglobalaihackathon.devpost.com/updates/46205-how-to-build-a-winning-project).

## Local private-preview preparation status

A separate password-protected fixture-only gateway includes the actual saved rejected result. On 30 October, full checks passed 374 backend and 60 frontend tests plus Ruff, shell syntax, types, lint and build; all 127 real Docker/HTTP checks passed. The approved safe landing-page navigation exception is verified in Chrome: native sign-in, landing/workspace access, saved-result downloads, a completed 150-observation fixture and history after reload succeeded. Cross-site API navigation and form submission remained blocked with a cached login. This used no additional Nebius calls. Public TLS, funded live judge access and publication remain pending.
