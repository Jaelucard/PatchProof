# Private judge preview: local review package

This adds a password-protected gateway around the existing single-user app. It is
**local deployment preparation**, not a public deployment or completed free live
judge access. The backend, evaluator, provider configuration and frontend are
unchanged. The review is fixture-only and mounts no provider key.

The authenticated landing page explains that this is a shared workspace for
synthetic tickets. It links to the app and the saved actual NVIDIA-on-Nebius
evidence. Every page, asset, API, report and documentation route requires the
same judge login. This is not multi-user data isolation.

## Prepare and start

Use an installed Docker engine with Docker Compose and the existing Python 3.13
application environment. Tested local versions are recorded in the handoff;
no system-wide installation is performed by the helper.

Build the small derived gateway image once, from the pinned official Caddy base:

```sh
docker pull caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f
docker build -f deployment/preview/Caddy.Dockerfile -t patchproof-preview-caddy:2.11.7 .
```

From the application directory, choose a **new absolute private directory outside
the source tree**, with an existing parent, and an unused local port:

```sh
python3 deployment/preview/prepare.py --output-dir /absolute/private/preview-review --port 8780
```

The derived image removes Caddy's unused low-port file capability, preserving
the preview's non-root, dropped-capability policy on port 8780. It adds no runtime
capability. The helper requires this image already built and never pulls or
builds it implicitly.

The helper prints the review URL, username and paths. It never prints a password
or password hash. Read the generated `password.txt` privately when signing in.
Do not paste it into chat, source, video or a public submission. The password is
generated for this local review only, and only its bcrypt hash enters Caddy.

Build and start with the printed Compose path. The explicit empty environment
file and control below prevent automatic environment-file loading:

```sh
COMPOSE_DISABLE_ENV_FILE=1 docker compose --env-file /dev/null -f /absolute/private/preview-review/compose.json build app
COMPOSE_DISABLE_ENV_FILE=1 docker compose --env-file /dev/null -f /absolute/private/preview-review/compose.json up -d --no-build --pull never
```

Open `http://127.0.0.1:8780` and sign in as the printed username. Open the workspace
from the landing page. In Experiment history, select the completed live run from
29 October at 01:38 to inspect its real rejected result. New runs in this review
are fixtures and use no provider credit.

Stop and remove the two owned review containers with:

```sh
COMPOSE_DISABLE_ENV_FILE=1 docker compose --env-file /dev/null -f /absolute/private/preview-review/compose.json down
```

The private directory persists for review/restart. Do not overwrite it or reuse
its empty fixture ledger for funded inference. Use a different new directory for
another disposable review. The source helper refuses existing output directories
and source-tree destinations.

## Boundary and persistence

- The only host publication is `127.0.0.1:8780` (or the chosen local port).
  The backend remains bound to `127.0.0.1:8770` inside its container network
  namespace. Caddy shares that namespace; backend port 8770 is never published.
  Caddy's administration API is disabled.
- Exact original Host, Origin and cross-site fetch checks run **before** Basic
  authentication and header translation. Joined duplicate Origins and ambiguous
  duplicate Authorization are rejected. Invalid Host does not reach the app.
- A cross-site top-level navigation may reach the landing page only when its
  path is exactly `/`, its method is `GET` or `HEAD`, and its Fetch Metadata is
  exactly `cross-site`, `navigate` and `document`. The same login still applies.
  This permits opening an external link, including programmatic navigation
  without a user-activation header. Cross-site API, workspace, asset, embedded
  page, fetch and write requests remain blocked. Joined duplicate Site values
  are rejected; duplicate Mode or Destination values cannot match the exception.
  Clients without Fetch Metadata retain the Host, Origin and login checks.
- After authentication, the gateway translates Host/Origin for the unchanged
  backend and removes Authorization and forwarding headers. Internal redirect
  locations are rewritten to the configured external origin. Security headers
  supply defaults without overriding backend values; a separate gateway-error
  route covers authentication failures and preserves the login challenge. Error
  bodies contain standard status text, without internal diagnostics.
- Both services are configured for the current non-root UID/GID, with a read-only
  root filesystem and dropped capabilities. The gateway entrypoint checks its
  actual identity against the generated expected UID/GID before starting Caddy;
  missing, invalid, root or altered identities fail closed. It also verifies a
  bounded, regular hash file with private mode and exactly one valid user/hash
  line, returning a generic error before a bad file can enter Caddy's parser.
  The reserved username `import` is rejected by both the preparer and guard.
  The preparer checks private host ownership and modes. Docker Desktop may
  virtualize bind-file UID metadata, so an in-container file UID is not treated
  as proof of ownership. Only the app's review data directory is a writable host
  bind mount. The raw password is never mounted into either container; the
  gateway sees only its hash file.
- The preparer seeds only the bundled, hash-verified completed synthetic run.
  It preserves its exact saved result and dataset identity and reserves all 40
  case exposure identities. It does not read the canonical database, usage ledger
  or any provider key. The local fixture ledger starts at zero because live
  inference is disabled; that is not new authorized spending headroom.
- Keep one app instance. Existing process/database locking remains authoritative.
  The private data volume retains saved results through service recreation.

The supplied Dockerfile uses a pinned official Python image and explicit copies
of runtime source, compiled assets, data and the existing pinned dependency lock.
The build context excludes environment files, credentials, databases and caches.
No Node build is needed to run the already compiled interface.

## Before any public or funded cutover

Do not expose this loopback HTTP review publicly. Basic authentication requires
TLS for a public site. A real host/domain, TLS termination, persistent storage,
access duration, shared-workspace privacy and cumulative funding limits need a
concrete deployment review and final approval.

The optional `--origin https://preview.example.test` renders a future-origin
boundary for local testing; it does not configure DNS, obtain a certificate or
publish a listener. The host port stays loopback-bound. See
[LIVE-CUTOVER.md](LIVE-CUTOVER.md) for the required continuity and approval gates.

Official references: [Caddy Basic authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth),
[ordered route handlers](https://caddyserver.com/docs/caddyfile/directives/route),
[reverse proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[Compose shared network namespaces](https://docs.docker.com/reference/compose-file/services/#network_mode),
[Compose environment-file controls](https://docs.docker.com/compose/how-tos/environment-variables/envvars/).
