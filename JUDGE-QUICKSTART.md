# Run PatchProof locally

This is a runnable local test build for the Nebius x NVIDIA Global AI Hackathon. The [source repository](https://github.com/Jaelucard/PatchProof) and [demo video](https://youtu.be/97ETxB-mhGs) are public; hosted judge access is still pending. The included app supports a deterministic Fixture simulation and an opt-in Nebius adapter. This package includes saved real Nebius results and a short narrated recording, with no credential.

## Requirements

The verified environment is macOS arm64, Python 3.13.5, Node 26.7.0 and npm 11.19.0. The declared frontend Node range is ^22.22.2, ^24.15.0 or >=26.0.0. Other systems have not been verified. Python's fcntl process lock makes the current launcher POSIX-specific; Windows execution is unverified.

Python 3.13, venv and pip are sufficient for the steps below. The compiled frontend is included, so Node is only needed to rebuild or run frontend checks. Dependencies require network access if not cached.

## Start the included fixture demo

Extract the archive and enter its patchproof directory. Create a new local environment and keep its database inside that extracted folder:

    python3.13 -m venv .venv
    .venv/bin/python -m pip install -r python-runtime-lock.txt
    PYTHONPATH=backend .venv/bin/python -B -m patchproof --database .local/patchproof.sqlite3 --port 8766

Open http://127.0.0.1:8766. If that port is occupied, choose another free port in the command. Stop with Ctrl+C. These commands do not enable provider calls and use a new disposable demo database. The historical start.sh is also preserved, but writes its work directory two levels above the app; the explicit command above avoids that layout assumption.

1. Select Run current fixture.
2. Inspect candidate 1's dev-03 order ID regression and candidate 2's remaining final-11 failure.
3. Inspect prompt differences and per-field comparisons, then export JSON or Markdown.
4. Restart the same command and open the saved experiment from history.

Every such run is labeled Fixture simulation. Scripted output is independent of prompt edits. It demonstrates the workflow and checks, not measured model performance.

## Live NVIDIA-on-Nebius mode

The included docs/LIVE-SETUP.md explains opt-in flags and limits. Inspect the included docs/LIVE-RESULTS.md, docs/evidence/live-diagnostic-2026-10-29.json and the demo recording. These are the actual saved rejected run; they do not populate a newly created application database automatically. An operator may choose live reproduction with their own authorized Token Factory account and private raw-key file. No funded public live endpoint is supplied; the prepared Render deployment still needs platform setup and verification before free judge access is ready. Never publish a shared key or remove loopback protections to make the app public.

The adapter targets nvidia/Nemotron-3_5-Lightning through Nebius Token Factory for extraction and at most two prompt revisions. Deterministic Python code performs scoring. The input and output prices saved in code are estimates, not an account-wide billing cap. A live run consumes the operator's authorized credits or funds.

The prepared synthetic 40-case diagnostic is included as data/diagnostic-40.json with its manifest and provenance note. It has mixed review provenance and cannot clear the current all-human-review gate. Import it with reviewed unchecked; use it only for a deliberate diagnostic, and do not invent fixture outputs. Labels and examples are published synthetic examples, not an undisclosed generalization benchmark.

## Rebuild and verify

From the extracted patchproof folder:

    .venv/bin/python -B -m pytest -q
    .venv/bin/ruff check backend tests deployment
    sh -n deployment/preview/gateway-entrypoint.sh
    cd frontend
    npm ci
    npm run typecheck
    npm run lint
    npm test
    npm run build

At the local-preview milestone on 30 October, verification passed 374 backend tests and 60 frontend tests, Ruff over backend/tests/deployment, shell syntax, TypeScript, frontend lint and build. The private-preview integration passed 127 real Docker/HTTP checks. Later hosted-package verification is summarized in the [README](README.md). The provider path in those suites is mocked. Separate real testing made 84 accounted inference requests, including the original rejected diagnostic and an instruction-only follow-up, with zero unknown usage. The relocated-package smoke check reused the existing Python environment, so it is not evidence of an empty-cache dependency install or another platform.

## Source, license and notices

LICENSE and REUSE.md preserve the MIT foundation and copied canonical helper attribution. THIRD-PARTY-NOTICES.txt includes notices for the bundled frontend runtime libraries. The original README/docs preserve dated engineering history; sibling work/audit paths described there are not part of this clean source distribution. Use this quickstart for the delivered layout.

Watch [PatchProof: Catching a Prompt Regression with Nebius and NVIDIA](https://youtu.be/97ETxB-mhGs), the public 52.109-second browser-tab screencast of the saved rejected result. It has synthesized English narration and a published English caption track that follows the spoken script. The included `demo/PatchProof-live-evidence-draft.mp4` is unchanged; its embedded captions and `demo/captions.srt` summarize the screen. See the [recording notes](demo/README.md) for playback verification and its limits. The recording duration is not the experiment runtime.

This is a single-user local workspace. Do not bind it directly to a public network as a hosted multi-user service. The rules permit a test build. Public source and video publication are complete; the hosted judge-access route and final Devpost submission remain pending.

## Password-protected local judge review

The optional deployment/preview package wraps the unchanged app in an authenticated gateway and seeds the actual rejected result for historical review. It uses fixtures for new runs and mounts no real provider key. Its 127 real Docker/HTTP checks passed. The approved narrow exception allows safe top-level navigation to the landing page through the same login gate; cross-site API and write requests remain blocked.

Chrome testing verified native sign-in, landing/workspace access, the saved real result, JSON/report downloads, a completed 150-observation fixture, history after reload and blocked cross-site API/form requests. Hosted TLS and funded judge access are not established. Read deployment/preview/README.md and LIVE-CUTOVER.md before use. Free judge access must remain available through 24 December 2026 at 04:00 China/Singapore time under the rules checked on 30 October.
