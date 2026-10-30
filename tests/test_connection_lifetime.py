"""Local SQLite transactions must release their connections on every exit path."""

import sqlite3

import pytest

from patchproof.providers import UsageLedger
from patchproof.store import Store


@pytest.fixture
def connections(monkeypatch):
    original_connect = sqlite3.connect
    opened = []

    class TrackedConnection(sqlite3.Connection):
        close_calls = 0
        fail_pragma = False

        def close(self):
            self.close_calls += 1
            super().close()

        def execute(self, statement, *args, **kwargs):
            if self.fail_pragma and statement == "PRAGMA journal_mode=WAL":
                raise sqlite3.OperationalError("Injected journal setup failure")
            return super().execute(statement, *args, **kwargs)

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=TrackedConnection, **kwargs)
        opened.append(connection)  # Keep references so GC cannot hide a missing close.
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    yield opened, TrackedConnection
    for connection in opened:
        # Cleanup also makes failing-before-fix runs safe for the test process.
        sqlite3.Connection.close(connection)


@pytest.mark.parametrize("constructor", [Store, UsageLedger])
def test_connections_close_after_initialization_and_commit(tmp_path, connections, constructor):
    opened, _ = connections
    owner = constructor(tmp_path / "database.sqlite3")
    assert len(opened) == 1
    assert opened[0].close_calls == 1
    with owner.connect() as db:
        db.execute("CREATE TABLE lifetime_test (value TEXT)")
        db.execute("INSERT INTO lifetime_test VALUES ('committed')")
    assert opened[-1].close_calls == 1
    with owner.connect() as db:
        assert db.execute("SELECT value FROM lifetime_test").fetchall() == [("committed",)]
    assert all(connection.close_calls == 1 for connection in opened)


@pytest.mark.parametrize("constructor", [Store, UsageLedger])
def test_body_error_rolls_back_and_closes_connection(tmp_path, connections, constructor):
    opened, _ = connections
    owner = constructor(tmp_path / "database.sqlite3")
    with owner.connect() as db:
        db.execute("CREATE TABLE lifetime_test (value TEXT)")
        db.execute("INSERT INTO lifetime_test VALUES ('kept')")
    with pytest.raises(RuntimeError, match="Interrupted transaction"):
        with owner.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO lifetime_test VALUES ('rolled back')")
            raise RuntimeError("Interrupted transaction")
    assert opened[-1].close_calls == 1
    with owner.connect() as db:
        assert db.execute("SELECT value FROM lifetime_test").fetchall() == [("kept",)]
    assert all(connection.close_calls == 1 for connection in opened)


@pytest.mark.parametrize("constructor", [Store, UsageLedger])
def test_commit_error_rolls_back_and_closes_connection(tmp_path, connections, constructor):
    opened, _ = connections
    owner = constructor(tmp_path / "database.sqlite3")
    with owner.connect() as db:
        db.execute("CREATE TABLE lifetime_parent (id INTEGER PRIMARY KEY)")
        db.execute(
            "CREATE TABLE lifetime_child (parent_id INTEGER REFERENCES lifetime_parent(id) "
            "DEFERRABLE INITIALLY DEFERRED)"
        )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        with owner.connect() as db:
            db.execute("PRAGMA foreign_keys=ON")
            # The statement succeeds; the deferred constraint fails during commit.
            db.execute("INSERT INTO lifetime_child VALUES (99)")
            assert db.execute("SELECT parent_id FROM lifetime_child").fetchall() == [(99,)]
    assert opened[-1].close_calls == 1
    with owner.connect() as db:
        assert db.execute("SELECT parent_id FROM lifetime_child").fetchall() == []
    assert all(connection.close_calls == 1 for connection in opened)


def test_store_closes_connection_when_journal_setup_fails(tmp_path, connections):
    opened, tracked = connections
    tracked.fail_pragma = True
    with pytest.raises(sqlite3.OperationalError, match="journal setup failure"):
        Store(tmp_path / "database.sqlite3")
    assert len(opened) == 1
    assert opened[0].close_calls == 1
