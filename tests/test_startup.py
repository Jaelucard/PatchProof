"""Startup preserves existing data and survives incomplete local setup."""

import fcntl
import os
from pathlib import Path
import shutil
import select
import signal
import socket
import sqlite3
import subprocess
import sys
import time

import pytest

from patchproof.store import Store
from patchproof import sqlite_inspection
from patchproof.providers import UsageLedger

APP_ROOT = Path(__file__).resolve().parents[1]


def launch(database, port):
    return subprocess.run(
        [sys.executable, "-B", "-m", "patchproof", "--database", str(database), "--port", str(port)],
        env={**os.environ, "PYTHONPATH": str(APP_ROOT / "backend")},
        capture_output=True, text=True, timeout=10,
    )


def active_store(path):
    store = Store(path)
    store.save({"id": "active", "status": "running", "phase": "development", "comparisons": []})
    return store


def test_occupied_port_does_not_recover_existing_experiment(tmp_path):
    database = tmp_path / "run.sqlite3"
    store = active_store(database)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        result = launch(database, listener.getsockname()[1])
    assert result.returncode != 0
    assert "address already in use" in result.stderr.lower()
    assert store.get("active")["status"] == "running"


def test_database_lock_blocks_another_port_before_recovery(tmp_path):
    database = tmp_path / "run.sqlite3"
    store = active_store(database)
    with database.with_name(database.name + ".lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = launch(database, 0)
    assert result.returncode != 0
    assert "database is already in use" in result.stderr.lower()
    assert store.get("active")["status"] == "running"


def test_cli_owns_database_until_clean_shutdown(tmp_path):
    database = tmp_path / "owned.sqlite3"
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "patchproof", "--database", str(database), "--port", "0"],
        env={**os.environ, "PYTHONPATH": str(APP_ROOT / "backend")},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        readable, _, _ = select.select([process.stdout], [], [], 5)
        assert readable, "Local CLI did not report its reserved socket"
        line = process.stdout.readline()
        assert line.startswith("PatchProof: http://127.0.0.1:")
        assert not line.strip().endswith(":0")
        startup = b""
        deadline = time.monotonic() + 5
        while b"Application startup complete" not in startup:
            readable, _, _ = select.select([process.stderr], [], [], max(0, deadline - time.monotonic()))
            assert readable, "Local CLI did not finish its initial startup recovery"
            chunk = os.read(process.stderr.fileno(), 4096)
            assert chunk, startup.decode()
            startup += chunk
        # Initial recovery has finished and the process owns the file lock. A second CLI on a
        # different free port must fail without performing restart recovery.
        store = active_store(database)
        result = launch(database, 0)
        assert result.returncode != 0
        assert "database is already in use" in result.stderr.lower()
        assert store.get("active")["status"] == "running"
        process.send_signal(signal.SIGINT)
        _, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    with database.with_name(database.name + ".lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("schema", [
    "CREATE TABLE unrelated_records (value TEXT)",
    "CREATE TABLE sqliteBackup (value TEXT)",
    "CREATE TABLE experiments (id TEXT, payload INTEGER)",
])
def test_foreign_database_is_rejected_before_any_change(tmp_path, schema):
    database = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(schema)
    before = database.read_bytes()
    with pytest.raises(ValueError, match="not a PatchProof database"):
        Store(database)
    assert database.read_bytes() == before
    assert not database.with_name(database.name + "-wal").exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_corrupt_database_is_rejected_without_changes(tmp_path):
    database = tmp_path / "bad.sqlite3"
    original = b"This file is not a SQLite database."
    database.write_bytes(original)
    with pytest.raises(ValueError, match="not a PatchProof database"):
        Store(database)
    assert database.read_bytes() == original


@pytest.mark.parametrize("live", [False, True])
def test_foreign_wal_database_and_sidecars_are_unchanged_on_rejection(tmp_path, live):
    database = tmp_path / "foreign-wal.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE foreign_records (value TEXT)")
    connection.execute("INSERT INTO foreign_records VALUES ('preserve')")
    connection.commit()
    if not live:
        connection.close()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    if live:
        assert database.name + "-wal" in before
    else:
        assert set(before) == {database.name}
    try:
        with pytest.raises(ValueError, match="not a PatchProof database"):
            Store(database)
        assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
    finally:
        connection.close()


def test_valid_uncheckpointed_wal_database_is_not_mistaken_for_empty(tmp_path):
    database = tmp_path / "live-valid.sqlite3"
    # Keep a connection open so the schema and record remain in WAL, not main.
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript("""
        CREATE TABLE experiments (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE datasets (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE exposure (version_hash TEXT PRIMARY KEY, count INTEGER NOT NULL);
        CREATE TABLE case_exposure (case_hash TEXT PRIMARY KEY, count INTEGER NOT NULL);
        INSERT INTO experiments VALUES ('from-wal', '{"id":"from-wal","status":"completed"}');
    """)
    try:
        assert database.with_name(database.name + "-wal").stat().st_size > 0
        store = Store(database)
        assert store.get("from-wal") == {"id": "from-wal", "status": "completed"}
    finally:
        connection.close()


@pytest.mark.parametrize("fault", ["copy_failure", "source_changed"])
def test_schema_snapshot_failure_or_race_fails_closed(tmp_path, monkeypatch, fault):
    database = tmp_path / "source.sqlite3"
    store = Store(database)
    store.save({"id": "saved", "status": "completed"})
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    copy = sqlite_inspection.copyfile

    def faulty_copy(source, destination):
        if fault == "copy_failure":
            raise OSError("Injected copy failure")
        result = copy(source, destination)
        if Path(source) == database:
            stat = database.stat()
            os.utime(database, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        return result

    monkeypatch.setattr(sqlite_inspection, "copyfile", faulty_copy)
    with pytest.raises(ValueError, match="not a PatchProof database") as error:
        Store(database)
    assert isinstance(error.value.__cause__, OSError)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("constructor", [Store, UsageLedger])
def test_hot_rollback_journal_blocks_both_stores_without_recovery(tmp_path, constructor):
    database = tmp_path / "foreign-hot.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA page_size=1024")
    connection.execute("CREATE TABLE foreign_records (value BLOB)")
    connection.executemany("INSERT INTO foreign_records VALUES (?)", [(b"x" * 2000,)] * 20)
    connection.commit()
    connection.close()
    crash = subprocess.run(
        [sys.executable, "-B", "-c", """
import os, sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA cache_size=1")
connection.execute("PRAGMA cache_spill=ON")
connection.execute("BEGIN IMMEDIATE")
connection.execute("DROP TABLE foreign_records")
os._exit(0)
""", str(database)],
        capture_output=True, timeout=5,
    )
    assert crash.returncode == 0, crash.stderr
    journal = database.with_name(database.name + "-journal")
    assert journal.stat().st_size > 0
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match="rollback journal"):
        constructor(database)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("contents", [b"", b"pending rollback"])
def test_journal_appearing_during_copy_blocks_inspection(tmp_path, monkeypatch, contents):
    database = tmp_path / "journal-race.sqlite3"
    Store(database)
    original = database.read_bytes()
    journal = database.with_name(database.name + "-journal")
    copy = sqlite_inspection.copyfile

    def create_journal(source, destination):
        result = copy(source, destination)
        if Path(source) == database:
            journal.write_bytes(contents)
        return result

    monkeypatch.setattr(sqlite_inspection, "copyfile", create_journal)
    with pytest.raises((ValueError, OSError), match="rollback journal|changed during"):
        with sqlite_inspection.inspect_database(database):
            pytest.fail("Inspection must not accept a changing journal state")
    assert database.read_bytes() == original
    assert journal.read_bytes() == contents


@pytest.mark.parametrize("constructor", [Store, UsageLedger])
@pytest.mark.parametrize("empty_main", [False, True])
def test_orphan_journal_blocks_missing_or_empty_main_file(tmp_path, constructor, empty_main):
    database = tmp_path / "empty.sqlite3"
    if empty_main:
        database.touch()
    journal = database.with_name(database.name + "-journal")
    journal.write_bytes(b"preserve pending rollback")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match="rollback journal"):
        constructor(database)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("constructor", [Store, UsageLedger])
@pytest.mark.parametrize("empty_main", [False, True])
@pytest.mark.parametrize("sidecars", [("-wal", "-shm"), ("-shm",)])
def test_orphan_wal_or_shm_preserves_all_files(tmp_path, constructor, empty_main, sidecars):
    source = tmp_path / "source.sqlite3"
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE foreign_records (value TEXT)")
        connection.execute("INSERT INTO foreign_records VALUES ('preserve')")
        connection.commit()
        contents = {suffix: source.with_name(source.name + suffix).read_bytes() for suffix in sidecars}
        assert all(contents.values())
    finally:
        connection.close()
    destination = tmp_path / "orphan"
    destination.mkdir()
    database = destination / "missing.sqlite3"
    if empty_main:
        database.touch()
    for suffix, value in contents.items():
        database.with_name(database.name + suffix).write_bytes(value)
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    with pytest.raises(ValueError, match="main database file is missing or empty"):
        constructor(database)
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == before


def test_empty_and_existing_patchproof_database_still_work(tmp_path):
    database = tmp_path / "empty.sqlite3"
    database.touch()
    initial = Store(database)
    initial.save({"id": "saved", "status": "completed", "evidence": "preserve"})
    reopened = Store(database)
    assert reopened.get("saved") == {"id": "saved", "status": "completed", "evidence": "preserve"}


def test_launcher_retries_failed_install_without_replacing_venv(tmp_path):
    task = tmp_path / "task"
    app = task / "outputs/app"
    (app / "frontend/dist/assets").mkdir(parents=True)
    (app / "frontend/dist/index.html").write_text(
        '<script type="module" src="/assets/main.js"></script>'
        '<link rel="stylesheet" href="/assets/main.css">'
    )
    (app / "frontend/dist/assets/main.js").write_text("console.log('fixture');")
    (app / "frontend/dist/assets/main.css").write_text("body { color: black; }")
    shutil.copy2(APP_ROOT / "start.sh", app / "start.sh")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log, installed, fail = (tmp_path / name for name in ("calls", "installed", "fail"))
    fail.touch()
    python = tmp_path / "fake-python"
    python.write_text(
        '#!/bin/sh\nprintf "python %s\\n" "$*" >> "$CALL_LOG"\n'
        'if [ ! -f "$INSTALLED" ]; then exit 42; fi\n'
        'if [ "$1" = -B ] && [ "$2" = - ]; then exec "$VALIDATOR_PYTHON" "$@"; fi\n'
    )
    uv = binaries / "uv"
    uv.write_text(
        '#!/bin/sh\nprintf "uv %s\\n" "$*" >> "$CALL_LOG"\n'
        'if [ "$1" = venv ]; then mkdir -p "$2/bin"; '
        'cp "$PYTHON_STUB" "$2/bin/python"; chmod +x "$2/bin/python"; fi\n'
        'if [ "$1" = pip ]; then if [ -f "$FAIL_INSTALL" ]; then exit 19; fi; '
        'touch "$INSTALLED"; fi\n'
    )
    uv.chmod(0o755)
    env = {
        **os.environ, "PATH": str(binaries) + ":" + os.environ["PATH"],
        "CALL_LOG": str(log), "INSTALLED": str(installed),
        "FAIL_INSTALL": str(fail), "PYTHON_STUB": str(python),
        "VALIDATOR_PYTHON": sys.executable,
    }
    first = subprocess.run([str(app / "start.sh")], cwd="/", env=env, timeout=10)
    assert first.returncode == 19
    fail.unlink()
    second = subprocess.run([str(app / "start.sh")], cwd="/", env=env, timeout=10)
    assert second.returncode == 0
    calls = log.read_text().splitlines()
    assert sum(line.startswith("uv venv ") for line in calls) == 1
    assert sum(line.startswith("uv pip ") for line in calls) == 2
    # Healthy startup via the provided directory symlink skips installation.
    alias = tmp_path / "alias"
    alias.symlink_to(app, target_is_directory=True)
    third = subprocess.run([str(alias / "start.sh")], cwd="/", env=env, timeout=10)
    assert third.returncode == 0
    calls = log.read_text().splitlines()
    assert sum(line.startswith("uv pip ") for line in calls) == 2
    assert str(task.resolve() / "work/patchproof.sqlite3") in calls[-1]
