"""Entry point for engine-created child processes that must retain Faye."""

from __future__ import annotations

import os
from pathlib import Path


def _faye_root_from_effective_home(value: str) -> str:
    """Recover the distribution root from a root or named-profile home."""
    home = Path(value).expanduser().absolute()
    if home.parent.name == "profiles":
        return str(home.parent.parent)
    return str(home)


def main() -> None:
    """Launch a child through Faye's full state and compatibility boundary."""
    # Detached service launchers persist the effective engine home but may not
    # inherit FAYE_HOME. Recover it before run_engine establishes the boundary.
    if not os.environ.get("FAYE_HOME", "").strip():
        inherited_home = os.environ.get("HERMES_HOME", "").strip()
        if inherited_home:
            os.environ["FAYE_HOME"] = _faye_root_from_effective_home(inherited_home)

    from faye.runtime import run_engine

    run_engine()


if __name__ == "__main__":
    main()
