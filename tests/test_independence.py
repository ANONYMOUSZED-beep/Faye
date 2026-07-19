from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "faye"
FORBIDDEN_RUNTIME = "".join(("her", "mes"))


def test_package_has_no_external_runtime_dependency() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    dependencies = [dependency.lower() for dependency in project.get("dependencies", [])]

    assert all(
        not dependency.startswith(f"{FORBIDDEN_RUNTIME}-agent")
        for dependency in dependencies
    )
    assert FORBIDDEN_RUNTIME not in project["description"].lower()


def test_faye_source_does_not_import_external_runtime_modules() -> None:
    forbidden: list[str] = []
    for source in PACKAGE.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if (
                    name == FORBIDDEN_RUNTIME
                    or name.startswith(f"{FORBIDDEN_RUNTIME}_")
                    or name.startswith(f"{FORBIDDEN_RUNTIME}.")
                ):
                    forbidden.append(f"{source.relative_to(ROOT)} imports {name}")

    assert forbidden == []


def test_wrapper_only_modules_and_assets_are_absent() -> None:
    forbidden_paths = (
        PACKAGE / "runtime.py",
        PACKAGE / "child_entry.py",
        PACKAGE / "assets" / "SOUL.md",
        PACKAGE / "assets" / "faye.yaml",
    )

    assert [str(path.relative_to(ROOT)) for path in forbidden_paths if path.exists()] == []
