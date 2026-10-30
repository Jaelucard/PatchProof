"""Inspect SQLite schemas without creating or modifying source WAL sidecars."""

from contextlib import closing, contextmanager
from pathlib import Path
from shutil import copyfile
import sqlite3
from tempfile import TemporaryDirectory


def _signature(path: Path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _database_state(path: Path):
    state = tuple(
        _signature(path.with_name(path.name + suffix)) for suffix in ("", "-wal", "-journal")
    )
    if state[2] is not None and state[2][2] > 0:
        raise ValueError(
            "Database has a nonempty rollback journal. Close or recover it with its owning "
            "application before starting PatchProof; leave the journal file in place."
        )
    if state[0] is None or state[0][2] == 0:
        shm = _signature(path.with_name(path.name + "-shm"))
        if any(sidecar is not None and sidecar[2] > 0 for sidecar in (state[1], shm)):
            raise ValueError(
                "Nonempty WAL or SHM files exist but the main database file is missing or empty. "
                "Restore or recover the database with its owning application; leave the sidecars in place."
            )
    return state


def check_database_sidecars(path: Path):
    """Check sidecars even before creating a missing or zero-byte main file."""
    _database_state(path)


@contextmanager
def inspect_database(path: Path):
    """Yield a read-only snapshot including uncheckpointed WAL, or fail closed.

    SQLite mode=ro can still create/change WAL sidecars. Copy first and let SQLite
    rebuild only the temporary SHM file. Detect source changes during the copy
    instead of trusting a mixture of database generations. A rollback journal
    requires its owning application's recovery; never silently inspect past it.
    """
    wal = path.with_name(path.name + "-wal")
    before = _database_state(path)
    with TemporaryDirectory(prefix="patchproof-schema-") as temporary:
        snapshot = Path(temporary) / "database.sqlite3"
        copyfile(path, snapshot)
        if before[1] is not None:
            copyfile(wal, snapshot.with_name(snapshot.name + "-wal"))
        if before != _database_state(path):
            raise OSError("Database changed during schema inspection; retry when it is idle.")
        with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as connection:
            yield connection
