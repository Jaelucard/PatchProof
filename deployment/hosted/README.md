# Hosted judge deployment on Render

This package runs the existing app and protected gateway in one container. It
uses one paid 512 MB instance, one 1 GB persistent disk and Render's managed
HTTPS endpoint. It does not add a public health route or change app behavior.
The default configuration refuses to start without an existing state pair.

Render's expected base charge is approximately US$7.25/month. This estimate is
not a hard billing cap. Keep automatic deploys, previews and scaling off; use a
free workspace and review usage against the separately approved hosting budget.

## Private inputs

Create these explicit Render secret files, never environment variables or files
in the repository:

- `judge-users`: one username and bcrypt hash (cost 12–16), matching the local
  gateway format. Keep the plaintext judge password separately.
- `patchproof-state.b64`: the one-time full canonical database transfer below.
- `nebius-tokenfactory.key`: the explicitly approved raw key, only for funded
  activation after current available credits have been checked.

Render places secret files in the Docker build context as well as at runtime in
`/etc/secrets/`. The build allowlist explicitly excludes all three names. The
Dockerfile copies individual public inputs and never uses a build secret.
Runtime mounted files must be regular files; symlinks are refused. Render's
secret-file access requires group 1000. The container runs as UID 10001:GID 1000
and copies credentials to private, app-owned mode-600 files outside all served
roots. It does not weaken the existing provider-key reader or gateway guard.

Both processes run as the same user in this single container, so Caddy can read
the provider file at the filesystem level. This differs from the local preview's
separate mounts. The gateway has no route to that directory, its admin API is
disabled, and its logs/configuration never contain the raw provider key.

## One-time state transfer

Stop every process that can write the canonical app database or usage ledger.
Keep them stopped after transfer: the hosted service becomes the sole writer.
Use the existing Python environment to run:

```sh
python deployment/hosted/create_seed.py \
  --database /absolute/private/canonical/review.sqlite3 \
  --output /absolute/private/transfer/patchproof-state.b64 \
  --confirm-source-stopped
```

The output directory must already exist with mode 700 and the current owner.
The source launcher lock must exist and be idle. The helper holds that lock,
checks that neither source changes, backs up both databases with SQLite, and
prints only hashes, sizes and counts. It never reads a key. Keep the resulting
file private and retain its `seed_sha256` receipt.

Bundle format: ASCII base64 of gzip-compressed JSON, with one final newline. The
approved SHA-256 covers the complete encoded file, including that newline. JSON
has `version: 1` and `files`, whose exact keys are `review.sqlite3` and
`provider-usage.sqlite3`. Each entry contains `base64`, `bytes`, `sha256` and
`summary`. The helper computes exact table counts and ledger amounts. This
transfers all experiments, datasets, exposure and provider accounting; a public
result export is insufficient. Encoded seed size is capped at 990,000 bytes so
the seed plus the bounded key and judge file remain below Render's combined
1 MB secret-file limit.

The initial transfer also limits each decoded database to 24 MiB. This bound is
only for preparing and decoding the seed; normal persisted history can grow
beyond it. Normal startup still checks file identity, ownership, schema,
integrity and the ledger's retained accounting.

Create one service from `render.yaml`, using the Dockerfile in this directory.
Before first deployment, configure:

- `PORT=8780` and the platform-provided `RENDER_EXTERNAL_URL` HTTPS origin.
- `PATCHPROOF_BOOTSTRAP=1` and `PATCHPROOF_LIVE_ENABLED=0`.
- `PATCHPROOF_SEED_SHA256` equal to the private transfer receipt.
- The two non-provider secret files above. A provider key is not required yet.

The runtime validates the full seed, writes both databases into one private
staging directory, and atomically installs `/data/state`. It preserves failed
staging directories for operator inspection. It starts the backend first and
opens the gateway only after local readiness succeeds. Either child exiting
stops both, and shutdown has a bounded grace period.

Check the restored counts, totals, saved real result, login, cross-site boundary
and storage persistence before funded activation. Confirm the actual Render
mount allows the configured non-root user to write `/data`; build-time ownership
does not guarantee platform-mounted disk ownership. Startup fails closed if it
cannot write. Never add a privileged fallback to bypass that check.

## Normal operation and funded activation

Set `PATCHPROOF_BOOTSTRAP=0`, remove the seed file and seed hash, and redeploy in
fixture mode first. Confirm restart preserves later results and the ledger.
Normal mode refuses missing/partial state, even if an old seed is still present.
An empty or replaced volume must never silently reset cumulative spending.

After current credits and the cumulative cap have been verified, add the raw
provider secret and explicitly set:

```text
PATCHPROOF_LIVE_ENABLED=1
PATCHPROOF_CONFIRM_NEBIUS_ACCESS=1
PATCHPROOF_CONFIRM_LIVE_CAP=1
PATCHPROOF_LIVE_CAP_USD=1
```

The hosted cap cannot exceed the existing US$1 app subcap and includes the
transferred usage. Bootstrap and live activation are mutually exclusive. Do not
reset or remove the ledger to regain budget. Unknown usage reservations remain
charged to the cap and block further calls under the existing app rules.

Run one bounded live smoke check and account for it in this same ledger. Verify
public HTTPS, exact host/origin handling, login, exports, prior exposure and
restart persistence. Render supplies TLS; only Caddy's port 8780 is public. The
backend remains on loopback 8770. Omit an HTTP health-check path: the default TCP
probe works with authentication on every route.

## Local verification

```sh
python -B -m pytest -q tests/test_hosted_runtime.py
ruff check deployment/hosted tests/test_hosted_runtime.py
docker build --pull=false -f deployment/hosted/Dockerfile -t patchproof-hosted:local .
python -B deployment/hosted/integration_test.py --output /absolute/private/hosted-checks.json
```

Use synthetic seed files and no real key for local container tests. The hosted
landing page states whether live inference is enabled. Saved evidence and
fixture mode remain usable when the inference cap is exhausted. All judges
share the workspace; use synthetic tickets only.

The integration runner also checks live-enabled startup with an unusable
synthetic key and the container's network disabled. It reads status only, checks
the private file ownership and preserved usage, and sends no model request.
This does not replace a separately authorized real hosted smoke test.

Primary platform references: [Docker](https://render.com/docs/docker),
[secret files](https://render.com/docs/configure-environment-variables),
[build-time secrets](https://render.com/docs/docker-secrets),
[persistent disks](https://render.com/docs/disks),
[health checks](https://render.com/docs/health-checks), and
[Blueprint configuration](https://render.com/docs/blueprint-spec).
