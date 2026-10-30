#!/bin/sh
set -eu
APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
TASK_DIR=$(CDPATH= cd -- "$APP_DIR/../.." && pwd -P)
RUNTIME_DIR="$TASK_DIR/work"
mkdir -p "$RUNTIME_DIR"
if [ ! -x "$RUNTIME_DIR/venv/bin/python" ]; then
  uv venv "$RUNTIME_DIR/venv" --python 3.13
fi
if ! "$RUNTIME_DIR/venv/bin/python" -B -c 'import fastapi, httpx, uvicorn' >/dev/null 2>&1; then
  uv pip install --python "$RUNTIME_DIR/venv/bin/python" -r "$APP_DIR/requirements.txt"
fi
frontend_ready() {
  "$RUNTIME_DIR/venv/bin/python" -B - "$APP_DIR/frontend/dist" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.modules = []
        self.styles = []
        self.has_base = False

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "base" and "href" in attributes:
            self.has_base = True
        if tag == "script" and (attributes.get("type") or "").strip().lower() == "module":
            self.modules.append(attributes.get("src"))
        if tag == "link" and "stylesheet" in (attributes.get("rel") or "").lower().split():
            self.styles.append(attributes.get("href"))

def ready():
    dist = Path(sys.argv[1]).resolve()
    index = (dist / "index.html").resolve()
    if not index.is_relative_to(dist) or not index.is_file():
        return False
    content = index.read_text(encoding="utf-8")
    if not content.strip():
        return False
    assets = Assets()
    assets.feed(content)
    if assets.has_base or not assets.modules or not assets.styles:
        return False
    for reference, extensions in [(ref, (".js", ".mjs")) for ref in assets.modules] + [(ref, (".css",)) for ref in assets.styles]:
        if not reference:
            return False
        url = urlsplit(reference)
        if url.scheme or url.netloc or not url.path:
            return False
        asset = (dist / unquote(url.path).lstrip("/")).resolve()
        if not asset.is_relative_to(dist) or asset.suffix.lower() not in extensions or not asset.is_file() or asset.stat().st_size == 0:
            return False
    return True

try:
    sys.exit(0 if ready() else 1)
except (OSError, ValueError, RuntimeError):
    sys.exit(1)
PY
}
if ! frontend_ready; then
  (cd "$APP_DIR/frontend" && npm ci && npm run build)
  if ! frontend_ready; then
    printf '%s\n' 'PatchProof frontend build is incomplete: index.html or its local JavaScript/CSS assets are missing or invalid. The server was not started.' >&2
    exit 1
  fi
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$APP_DIR/backend"
exec "$RUNTIME_DIR/venv/bin/python" -m patchproof --database "$RUNTIME_DIR/patchproof.sqlite3" --port 8766
