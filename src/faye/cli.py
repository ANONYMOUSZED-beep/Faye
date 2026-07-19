from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _default_hermes_home() -> Path:
    configured = os.environ.get("HERMES_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".hermes"


def _migrate_hermes(argv: list[str]) -> None:
    from faye.runtime import (
        bootstrap_faye_home,
        default_faye_home,
        migrate_hermes_state,
        validate_migration_paths,
    )

    parser = argparse.ArgumentParser(
        prog="faye migrate-hermes",
        description=(
            "Copy Hermes state into Faye without modifying Hermes or overwriting Faye files."
        ),
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=_default_hermes_home(),
        help="Hermes state directory (default: HERMES_HOME or ~/.hermes)",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=default_faye_home(),
        help="Faye state directory (default: FAYE_HOME or the platform default)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report copy/skip counts without writing files",
    )
    args = parser.parse_args(argv)
    validate_migration_paths(args.source, args.destination)
    if not args.dry_run:
        bootstrap_faye_home(args.destination)
    result = migrate_hermes_state(args.source, args.destination, dry_run=args.dry_run)
    verb = "Would copy" if args.dry_run else "Copied"
    print(f"{verb} {result.copied} file(s); skip {result.skipped} existing file(s).")
    print(f"Hermes source unchanged: {args.source.expanduser().resolve()}")
    print(f"Faye state: {args.destination.expanduser().resolve()}")


def main() -> None:
    """Launch Faye or handle a Faye distribution command."""
    if len(sys.argv) > 1 and sys.argv[1] == "migrate-hermes":
        _migrate_hermes(sys.argv[2:])
        return

    from faye.runtime import run_engine

    run_engine()


if __name__ == "__main__":
    main()
