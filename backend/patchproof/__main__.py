"""Loopback-only launcher with an explicit separate database path."""

import argparse
import fcntl
import os
import stat
from decimal import Decimal, InvalidOperation
from pathlib import Path
import socket

import uvicorn

from .app import create_app
from .providers import LiveAuthorization, LiveConfig


def live_configuration(args):
    """Read exactly one explicitly supplied key file, only after both confirmations."""
    if not any((args.live_key_file, args.live_cap_usd, args.confirm_nebius_access, args.confirm_live_cap)):
        return None
    try:
        cap = Decimal(args.live_cap_usd) if args.live_cap_usd else None
    except InvalidOperation as exc:
        raise ValueError("Live cap must be a finite positive USD amount.") from exc
    authorization = LiveAuthorization(args.confirm_nebius_access, args.confirm_live_cap, cap)
    authorization.check()
    if args.live_key_file is None:
        raise ValueError("Live inference requires an explicit private raw-key file.")
    try:
        descriptor = os.open(args.live_key_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Key file must be a private regular file owned by this user (mode 600).")
            data = stream.read(8193)
        key = data.decode("ascii").strip("\r\n")
        if not 1 <= len(key) <= 8192 or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ValueError("Key file must contain only one raw API key, not an environment file.")
    except (OSError, UnicodeError) as exc:
        raise ValueError("Unable to read the explicitly supplied private API-key file.") from exc
    return LiveConfig(authorization=authorization, api_key=key)

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Start PatchProof locally; fixture-only unless all live options are explicitly supplied."
    )
    parser.add_argument(
        "--database", required=True, type=Path,
        help="Explicit PatchProof SQLite file; never point at Eval Lab data.",
    )
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--live-key-file", type=Path, help="Private raw Token Factory key file; never read by default.")
    parser.add_argument("--live-cap-usd", help="Approved cumulative USD inference cap, including credits and cash.")
    parser.add_argument("--confirm-nebius-access", action="store_true", help="Record confirmed usable account access.")
    parser.add_argument("--confirm-live-cap", action="store_true", help="Record explicit approval of the supplied total cap.")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    database = args.database.resolve()
    try:
        live_config = live_configuration(args)
        # Reserve the actual listener before app construction or restart recovery.
        # A second launch must not interrupt saved runs before failing to bind.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", args.port))
            listener.listen(2048)
            listener.setblocking(False)
            database.parent.mkdir(parents=True, exist_ok=True)
            with database.with_name(database.name + ".lock").open("a") as owner:
                try:
                    fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ValueError("This database is already in use by another PatchProof process.") from exc
                port = listener.getsockname()[1]
                config = uvicorn.Config(
                    create_app(database, **({"live_config": live_config} if live_config else {})),
                    host="127.0.0.1", port=port, access_log=False
                )
                print(f"PatchProof: http://127.0.0.1:{port}", flush=True)
                uvicorn.Server(config).run(sockets=[listener])
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
