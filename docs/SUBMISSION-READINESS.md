# PatchProof submission readiness — updated 30 October 2026

Current status, 30 October: actual NVIDIA-on-Nebius runtime use is verified. The original repair was rejected and final assessment was correctly skipped. A licensed local source package, portable judge instructions, saved real evidence, updated description and a short narrated browser-recording draft are prepared. A public repository, final judge access URLs, public YouTube URL, entrant details, entrant feedback and Devpost receipt are still pending. See [LIVE-RESULTS.md](LIVE-RESULTS.md). This is preparation evidence, not a qualification or submission receipt. The authenticated fixture-only local preview passed 127 real Docker/HTTP checks and 374 backend/60 frontend tests plus Ruff, shell syntax, types, lint and build. Chrome sign-in, landing/workspace access, saved-result downloads, a 150-observation fixture and retained history after reload passed. Cross-site API and form requests remained blocked with a cached login. Public TLS/funded live access is not established. See [preview preparation](../deployment/preview/README.md).

## Historical preparation record — 22 October 2026

The sections below preserve the earlier preparation audit. Their access, test, video and planning statements describe 22 October and are superseded by the current status above and [LIVE-RESULTS.md](LIVE-RESULTS.md). The deadline and access-end date were refreshed from the rules on 30 October.

**Verdict recorded on 22 October: implemented and locally validated, but not yet evidenced as a qualifying or submitted hackathon entry.** PatchProof is the selected project. This audit did not repeat project selection.

## Evidence found

The actual application is at `the application root`. Its optional live orchestration is now wired and transport-mock-tested; the runtime remains fixture-only because account access is unverified and the user chose to keep spending disabled. No PatchProof repository was returned by a current search of the connected GitHub installations; this does not prove none exists elsewhere. A focused Gmail search for Nebius/PatchProof submissions since 17 October returned the judging email, not a submission receipt. Neither search establishes that an entry was submitted.

The Devpost judging email of 21 October was read directly. It links to the [session recording](https://youtu.be/LjCh-ZIyjx4); the recording itself was not reviewed. Feedback in this work is grounded in the email and published rules.

## Requirement versus actual status

| Requirement | Status on 22 October | Evidence needed to close it |
|---|---|---|
| Working, understandable application | **Confirmed locally, fixture mode** | Local workflow, fresh runs and tests are available; real-provider behavior remains unverified |
| Nebius runtime and NVIDIA open model | **Prepared and mock-tested; no real execution verified** | Authorized runtime request, exact NVIDIA model ID, saved input/output, usage, latency, cost and error evidence |
| Track | **Not confirmed in form** | Best Apps and Agents is the recommended fit for the current prompt workflow; select and verify it in Devpost |
| Public repository and license | **Local source/MIT license present; public URL unverified** | Publish reviewed source, preserve LICENSE/REUSE, verify signed-out access and a clean setup |
| Working demo or test-build URL | **Local only** | Accessible URL, test instructions and free judge access for the required period |
| Public demonstration under three minutes | **Local 2:40 narrated still-capture draft; not public** | Record actual live operation, replace fixture-only evidence, publish on YouTube and check signed-out playback/duration |
| Description and English materials | **Local drafts prepared; form unverified** | Transfer reviewed text, exact model/service names and URLs into required fields |
| Nebius/NVIDIA product feedback | **Missing live-use basis** | Specific observed strengths, failures, latency, onboarding friction and reuse decision from actual authorized use |
| Existing-work and dependency disclosure | **Present locally** | Preserve Eval Lab foundation disclosure from REUSE.md in repository and submission |
| Registration, entrant eligibility and team details | **Current state unverified** | Verify account/form and actual entrant facts; receiving registration email is not a final-entry receipt |
| Submission | **Unverified** | Final confirmation, project URL and timestamp after submitting the completed entry |

The [official overview](https://nebiusglobalaihackathon.devpost.com/) lists the materials and track choices. The [official rules](https://nebiusglobalaihackathon.devpost.com/rules) require actual Nebius execution with an NVIDIA open model, a public licensed repository, working access, English materials and a public YouTube video below 180 seconds. Confirm entrant eligibility and component rights against those rules. The deadline is **31 October 2026 at 01:00 China time** (30 October, 10:00 PDT). Judge access must remain available through **24 December 2026 at 04:00 China time** (23 December, noon Pacific).

The [FAQ](https://nebiusglobalaihackathon.devpost.com/details/faqs) clarifies that calling NVIDIA on another provider does not meet the Nebius requirement; the rest of the app may be hosted elsewhere. Account onboarding restrictions are separate from competition eligibility. Do not use a different billing region as a workaround. The overview's “three minutes or shorter” differs from the rules' stricter duration; the earlier plan targeted 160 seconds. The current saved-result recording is 52.109 seconds.

## Changes made for the judges

1. **Action first:** a visible Run current fixture button above the main layout uses the loaded dataset, prompt and scenario. Three short steps explain what to inspect. Existing lock, import and storage safeguards apply to both start controls.
2. **Specific audience:** the page now identifies developers changing support-ticket extraction prompts and the decision it supports: inspect improved and regressed fields before adoption.
3. **Visible responsibilities:** extraction, repair and deterministic scoring are explained beside the evidence, with saved fixture IDs. No live NVIDIA model is claimed.
4. **Honest results:** comparison coverage identifies the inspected proposal and missing cases; active execution now says evidence is being collected. A discarded proposal is not confused with the frozen candidate.
5. **Packaging:** technical map, six-case failure atlas, timed narration, actual screen captures, local narrated MP4, English subtitles, source review archive and fresh evidence receipts.

No extra model, search, agent framework or cloud integration was added. The single useful capability remains prompt-change evaluation.

## Highest-impact remaining work, in order

**First: establish usable Nebius access and a total credit/spending cap.** These are explicit outstanding requirements from the earlier build brief. No credentials were searched, no live inference was attempted and no spend occurred here. The prepared integration selects NVIDIA Nemotron 3.5 Lightning and saves its documented prices. Once access and a cap are confirmed, verify that exact model in the authenticated catalog, make one bounded probe and capture one end-to-end real run. See [LIVE-SETUP.md](LIVE-SETUP.md). Both extraction and repair may use the same suitable NVIDIA model; a second model is justified only by measured benefit.

**Second: review the 60 expected labels and test new cases.** Human review remains pending. Current final cases have already been seen in local runs; do not describe repeated execution as new unseen evidence. Freeze a candidate before testing a genuinely new, human-reviewed holdout. Record every failed field and aborted request, not just aggregate gains. Measure first useful result from an actual cold product visit, plus service latency and cost.

**Third: validate the audience claim.** Have two or three developers who maintain structured LLM extraction workflows try the app without coaching. Ask them to find one fixed field, one regression and one unresolved failure. Record whether they reach useful evidence within two minutes and whether the report changes a deployment decision. No user interviews or adoption outcomes are currently established.

**Fourth: prepare safe public access and final packaging.** The backend is deliberately localhost-only and has no public multi-user isolation. Merely rebinding it publicly is not a deployment solution. Prepare a scoped judge deployment or a reproducible test-build route, with server-side credentials, bounded use and sufficient access duration. Publish only reviewed source and non-private examples. Replace the still-capture draft with actual live operation; keep the opening lost-order example within 30 seconds and export below 180 seconds. Complete product feedback using observations, following the [organizer's packaging guidance](https://nebiusglobalaihackathon.devpost.com/updates/46205-how-to-build-a-winning-project).

Suggested working dates in China time: access/integration by 24 October; labels, unseen evaluation and developer trials by 26 October; final recording and public-access checks by 28 October; submit on 29 October, leaving a buffer before 31 October at 01:00. These are planning targets, not scheduled automations or promises of completion.

## Publication boundary

No repository publication, Git commit/push, public deployment, YouTube upload, Devpost modification or submission occurred. The local MP4 is an honest fixture-workflow rehearsal, not proof of required live integration. Publishing the current package as a complete qualifying project would overstate the evidence.
