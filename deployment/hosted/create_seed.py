"""Create a private transfer bundle only after the operator quiesces the source."""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from runtime import (
    HostedError, MAX_DATABASE_BYTES, MAX_SEED_BYTES, STATE_NAMES, checked_regular_file,
    database_summary, inspect_database, owner_lock, private_directory, private_write, regular_file,
)


def source_signature(paths: list[Path]) -> tuple:
    values = []
    for path in paths:
        for suffix in ("", "-wal", "-shm", "-journal"):
            item = path.with_name(path.name + suffix)
            try:
                info = item.lstat()
                values.append((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            except FileNotFoundError:
                values.append(None)
    return tuple(values)


def create_seed(database: Path, output: Path, *, source_stopped: bool) -> dict:
    if not source_stopped:
        raise HostedError("Explicitly stop all canonical writers before creating a transfer seed.")
    if not database.is_absolute() or database.is_symlink():
        raise HostedError("Use the explicit absolute canonical database path.")
    ledger = database.parent / "provider-usage.sqlite3"
    if not output.is_absolute() or output.is_symlink():
        raise HostedError("Use a new absolute private seed output path.")
    private_directory(output.parent)
    paths = [database, ledger]
    for path, name in zip(paths, STATE_NAMES, strict=True):
        with checked_regular_file(path, limit=MAX_DATABASE_BYTES):
            pass
        database_summary(path, name, private=False)
    # The application's launcher uses this same lock. Never create it here:
    # a nonexistent lock is evidence that the source identity needs checking.
    with owner_lock(database.with_name(database.name + ".lock"), create=False):
        before = source_signature(paths)
        entries = {}
        with tempfile.TemporaryDirectory(prefix="patchproof-transfer-") as temp:
            for path, name in zip(paths, STATE_NAMES, strict=True):
                snapshot = Path(temp) / name
                with inspect_database(path) as source, closing(sqlite3.connect(snapshot)) as target:
                    source.backup(target)
                snapshot.chmod(0o600)
                payload = regular_file(snapshot, limit=MAX_DATABASE_BYTES, private=True)
                entries[name] = {
                    "base64": base64.b64encode(payload).decode("ascii"),
                    "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                    "summary": database_summary(snapshot, name),
                }
        if source_signature(paths) != before:
            raise HostedError("Canonical state changed during backup. Stop every writer and retry.")
        bundle = json.dumps({"version": 1, "files": entries}, sort_keys=True, separators=(",", ":")).encode()
        encoded = base64.b64encode(gzip.compress(bundle, mtime=0)) + b"\n"
        if len(encoded) > MAX_SEED_BYTES:
            raise HostedError("Transfer seed exceeds the Render secret-file budget.")
        private_write(output, encoded)
    return {
        "seed_bytes": len(encoded), "seed_sha256": hashlib.sha256(encoded).hexdigest(),
        "files": {name: {key: value for key, value in entry.items() if key != "base64"}
                  for name, entry in entries.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confirm-source-stopped", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        receipt = create_seed(args.database, args.output, source_stopped=args.confirm_source_stopped)
    except (HostedError, OSError, sqlite3.Error):
        parser.exit(1, "State transfer refused. Check stopped writers, source identity and private output.\n")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
