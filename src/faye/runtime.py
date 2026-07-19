from __future__ import annotations

import json
import os
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from importlib import metadata, resources
from io import StringIO
from pathlib import Path
from typing import Any

from faye import __version__

ENGINE_DISTRIBUTION = "hermes-agent"
ENGINE_VERSION = "0.18.2"
FAYE_IDENTITY = (
    "You are Faye, a production autonomous AI assistant. You are helpful, "
    "knowledgeable, direct, and honest about uncertainty. You run on the Faye "
    "distribution by Openbench, powered by the Hermes Agent engine."
)
LEGACY_FAYE_HERO = """[#F472B6]        ✦[/]
[#A78BFA]      ╱   ╲[/]
[#7C3AED]    ◈  FAYE  ◈[/]
[#A78BFA]      ╲   ╱[/]
[#F472B6]        ✦[/]"""
FAYE_DIGITAL_HERO = """[#6D5A8D]╭───────✦───────╮[/]
[#A78BFA]│ ░▒▓ SIGNAL ▓▒░ │[/]
[#A78BFA]│   ╭───────╮   │[/]
[#F472B6]│  ╱▒▒▒▒▒▒▒▒▒╲  │[/]
[#F472B6]│ ╱▒╭─────╮▒╲ │[/]
[#F5E9FF]│ │▒│ ◈   ◈ │▒│ │[/]
[#F5E9FF]│ │▒│   ▴   │▒│ │[/]
[#F5E9FF]│ │▒│ ╰───╯ │▒│ │[/]
[#F472B6]│ ╲▒╰──┬──╯▒╱ │[/]
[#F472B6]│  ╲▒▒╭┴╮▒▒╱  │[/]
[#A78BFA]│   ╰─╯ ╰─╯   │[/]
[bold #F472B6]│ F A Y E // 01 │[/]
[bold #4ADE80]╰── ONLINE ──────╯[/]"""


@dataclass(frozen=True)
class MigrationResult:
    copied: int
    skipped: int


def _is_symlink_or_reparse(path: Path) -> bool:
    """Return whether an existing path can redirect filesystem access."""
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(attributes & 0x400)


def _reject_reparse_components(path: Path) -> None:
    """Reject symlinks and Windows reparse points in an effective path."""
    current = Path(path.anchor) if path.anchor else Path()
    parts = path.parts[1:] if path.anchor else path.parts
    for part in parts:
        current /= part
        if _is_symlink_or_reparse(current):
            raise ValueError(
                f"Faye migration destination contains a symlink or reparse point: {current}"
            )


def validate_migration_paths(source: Path, destination: Path) -> tuple[Path, Path]:
    """Resolve and validate migration roots without creating either path."""
    source = source.expanduser().absolute()
    destination = destination.expanduser().absolute()
    if not source.is_dir():
        raise FileNotFoundError(f"Hermes state directory does not exist: {source}")
    _reject_reparse_components(destination)
    source = source.resolve()
    destination = destination.resolve(strict=False)
    if (
        source == destination
        or source.is_relative_to(destination)
        or destination.is_relative_to(source)
    ):
        raise ValueError(
            "Hermes source and Faye destination must be different, non-overlapping paths"
        )
    return source, destination


def default_faye_home(env: dict[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    configured = values.get("FAYE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().absolute()
    return (Path.home() / ".faye").absolute()


def _asset_text(name: str) -> str:
    return resources.files("faye.assets").joinpath(name).read_text(encoding="utf-8")


def _write_if_missing(path: Path, content: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError:
        return


def bootstrap_faye_home(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    skins = home / "skins"
    skins.mkdir(exist_ok=True)
    _write_if_missing(home / "SOUL.md", _asset_text("SOUL.md"))
    _write_if_missing(skins / "faye.yaml", _asset_text("faye.yaml"))
    _write_if_missing(home / "config.yaml", "display:\n  skin: faye\n")
    marker = home / ".faye-distribution.json"
    if not marker.exists():
        _write_if_missing(
            marker,
            json.dumps(
                {
                    "distribution": "faye-agent",
                    "version": __version__,
                    "engine": ENGINE_DISTRIBUTION,
                    "engine_version": ENGINE_VERSION,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )


def migrate_hermes_state(
    source: Path,
    destination: Path,
    *,
    dry_run: bool = False,
) -> MigrationResult:
    """Copy Hermes state without changing source or existing Faye files."""
    source, destination = validate_migration_paths(source, destination)

    copied = 0
    skipped = 0
    for source_path in source.rglob("*"):
        if source_path.is_symlink() or not source_path.is_file():
            continue
        destination_path = destination / source_path.relative_to(source)
        _reject_reparse_components(destination_path)
        if destination_path.exists():
            skipped += 1
            continue
        copied += 1
        if dry_run:
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        _reject_reparse_components(destination_path)
        shutil.copy2(source_path, destination_path)
    return MigrationResult(copied=copied, skipped=skipped)


def prepare_environment(env: dict[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    home = default_faye_home(values)
    normalized = str(home)
    values["FAYE_HOME"] = normalized
    # The engine deliberately treats HERMES_HOME as its complete state boundary.
    # Faye owns that value, even if a parent Hermes process exported another one.
    values["HERMES_HOME"] = normalized
    values.setdefault(
        "HERMES_ENVIRONMENT_HINT",
        "Runtime distribution: Faye. Identify as Faye. The underlying production "
        "engine is Hermes Agent; Faye is distributed by Openbench and user-facing "
        "commands use `faye`.",
    )
    bootstrap_faye_home(home)
    return home


def _contains_engine(path: str) -> bool:
    if not path:
        return False
    try:
        return (Path(path).resolve() / "hermes_cli").is_dir()
    except OSError:
        return False


def isolate_engine_imports(env: dict[str, str] | None = None) -> Path:
    """Put Faye's pinned engine first and remove only conflicting engine roots."""
    values = os.environ if env is None else env
    matching = [
        distribution
        for distribution in metadata.distributions(name=ENGINE_DISTRIBUTION)
        if distribution.version == ENGINE_VERSION
    ]
    if not matching:
        installed = sorted(
            {
                distribution.version
                for distribution in metadata.distributions(name=ENGINE_DISTRIBUTION)
            }
        )
        found = ", ".join(installed) if installed else "none"
        raise RuntimeError(
            f"Faye requires {ENGINE_DISTRIBUTION}=={ENGINE_VERSION}; found {found}. "
            "Reinstall Faye to restore a supported runtime."
        )

    engine_root = Path(matching[0].locate_file("")).resolve()
    retained = [
        entry
        for entry in sys.path
        if not _contains_engine(entry) or Path(entry).resolve() == engine_root
    ]
    sys.path[:] = [
        str(engine_root),
        *[
            entry
            for entry in retained
            if Path(entry or ".").resolve() != engine_root
        ],
    ]

    python_path = values.get("PYTHONPATH", "")
    if python_path:
        entries = python_path.split(os.pathsep)
        values["PYTHONPATH"] = os.pathsep.join(
            entry
            for entry in entries
            if not _contains_engine(entry) or Path(entry).resolve() == engine_root
        )
    if sys.prefix != sys.base_prefix:
        values["VIRTUAL_ENV"] = sys.prefix
    return engine_root


def _replace_brand(value: str) -> str:
    return value.replace("Hermes Agent", "Faye").replace("hermes", "faye").replace(
        "Hermes", "Faye"
    )


class _FirstRunBrandingStream:
    """Rebrand fixed first-run guidance without touching normal agent output."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def write(self, value: str) -> int:
        self._stream.write(_replace_brand(value))
        return len(value)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def patch_engine_startup_content() -> None:
    """Rebrand fixed engine-authored startup tips and onboarding guidance."""
    import agent.onboarding as onboarding
    import hermes_cli.tips as tips

    tips.TIPS[:] = [_replace_brand(tip) for tip in tips.TIPS]

    current = onboarding.openclaw_residue_hint_cli
    if getattr(current, "__faye_wrapper__", False):
        return

    def openclaw_residue_hint_cli() -> str:
        return _replace_brand(current())

    openclaw_residue_hint_cli.__faye_wrapper__ = True  # type: ignore[attr-defined]
    onboarding.openclaw_residue_hint_cli = openclaw_residue_hint_cli


def patch_engine_skin() -> None:
    """Install Faye's startup portrait without replacing custom user artwork."""
    import hermes_cli.skin_engine as skin_engine

    current = skin_engine._build_skin_config
    if getattr(current, "__faye_wrapper__", False):
        return

    def build_skin_config(data: dict[str, Any]) -> Any:
        skin = current(data)
        if skin.banner_hero.strip() == LEGACY_FAYE_HERO:
            skin.banner_hero = FAYE_DIGITAL_HERO
        return skin

    build_skin_config.__faye_wrapper__ = True  # type: ignore[attr-defined]
    skin_engine._build_skin_config = build_skin_config
    # The engine may have resolved the skin while importing its CLI modules.
    if getattr(skin_engine, "_active_skin", None) is not None:
        active = skin_engine._active_skin
        if active.banner_hero.strip() == LEGACY_FAYE_HERO:
            active.banner_hero = FAYE_DIGITAL_HERO


def patch_engine_parser() -> None:
    import argparse

    from hermes_cli import _parser

    current = _parser.build_top_level_parser
    if getattr(current, "__faye_wrapper__", False):
        return

    def rebrand_parser(parser: Any, *, root: bool = False) -> None:
        parser.prog = _replace_brand(parser.prog)
        if root:
            parser.description = "Faye - production autonomous AI assistant"
        elif parser.description:
            parser.description = _replace_brand(parser.description)
        if parser.epilog:
            parser.epilog = _replace_brand(parser.epilog)
        for action in parser._actions:
            if action.help:
                action.help = _replace_brand(action.help)
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for child in choices.values():
                    if hasattr(child, "_actions"):
                        rebrand_parser(child)

    def build_top_level_parser() -> tuple[Any, Any, Any]:
        parser, subparsers, chat_parser = current()
        if "migrate-hermes" not in subparsers.choices:
            migration = subparsers.add_parser(
                "migrate-hermes",
                help="Copy Hermes state into isolated Faye storage",
            )
            migration.add_argument("--source")
            migration.add_argument("--destination")
            migration.add_argument("--dry-run", action="store_true")
        rebrand_parser(parser, root=True)
        return parser, subparsers, chat_parser

    build_top_level_parser.__faye_wrapper__ = True  # type: ignore[attr-defined]
    _parser.build_top_level_parser = build_top_level_parser

    current_parse_known_args = argparse.ArgumentParser.parse_known_args
    if not getattr(current_parse_known_args, "__faye_wrapper__", False):

        def parse_known_args(self: Any, args: Any = None, namespace: Any = None) -> Any:
            rebrand_parser(self, root=self.prog in {"hermes", "faye"})
            return current_parse_known_args(self, args, namespace)

        parse_known_args.__faye_wrapper__ = True  # type: ignore[attr-defined]
        argparse.ArgumentParser.parse_known_args = parse_known_args


def patch_engine_runtime(engine_main: Any) -> None:
    def print_version(*, check_updates: bool = True) -> None:
        del check_updates
        installed_engine = metadata.version(ENGINE_DISTRIBUTION)
        print(f"Faye v{__version__} (Hermes Agent engine v{installed_engine})")
        print(f"Python: {sys.version.split()[0]}")
        print(f"State: {os.environ['FAYE_HOME']}")

    engine_main._print_version_info = print_version
    engine_main._print_fast_version_info = lambda: print_version(check_updates=False)

    def set_process_title() -> None:
        try:
            import setproctitle

            setproctitle.setproctitle("faye")
        except Exception:
            pass

    engine_main._set_process_title = set_process_title

    original_status = engine_main.cmd_status

    def status(args: Any) -> Any:
        output = StringIO()
        with redirect_stdout(output):
            result = original_status(args)
        rendered = output.getvalue().replace("Hermes Agent", "Faye")
        rendered = rendered.replace("(run: hermes ", "(run: faye ")
        rendered = rendered.replace("'hermes ", "'faye ")
        rendered = rendered.replace("`hermes ", "`faye ")
        print(rendered, end="")
        return result

    engine_main.cmd_status = status

    def unsupported_lifecycle_command(_args: Any) -> None:
        print(
            "Faye manages its exact engine dependency as one tested distribution. "
            "Update with `uv tool upgrade faye-agent` (or reinstall this project); "
            "remove it with `uv tool uninstall faye-agent`.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    engine_main.cmd_update = unsupported_lifecycle_command
    engine_main.cmd_uninstall = unsupported_lifecycle_command


def _replace_child_module(argv: list[str]) -> list[str]:
    return ["faye.child_entry" if value == "hermes_cli.main" else value for value in argv]


def patch_engine_subprocesses() -> None:
    """Route engine-created relaunch and gateway children through Faye."""
    import hermes_cli.gateway as gateway
    import hermes_cli.gateway_windows as gateway_windows
    import hermes_cli.relaunch as relaunch

    current_relaunch = relaunch.build_relaunch_argv
    if not getattr(current_relaunch, "__faye_wrapper__", False):

        def build_relaunch_argv(*args: Any, **kwargs: Any) -> list[str]:
            original = current_relaunch(*args, **kwargs)
            if len(original) >= 3 and original[1:3] == ["-m", "hermes_cli.main"]:
                tail = original[3:]
            else:
                tail = original[1:]
            return [sys.executable, "-m", "faye.child_entry", *tail]

        build_relaunch_argv.__faye_wrapper__ = True  # type: ignore[attr-defined]
        relaunch.build_relaunch_argv = build_relaunch_argv

    for name in ("_gateway_run_args_for_profile", "_gateway_run_command"):
        current = getattr(gateway, name)
        if getattr(current, "__faye_wrapper__", False):
            continue

        def gateway_argv(*args: Any, _current: Any = current, **kwargs: Any) -> list[str]:
            return _replace_child_module(_current(*args, **kwargs))

        gateway_argv.__faye_wrapper__ = True  # type: ignore[attr-defined]
        setattr(gateway, name, gateway_argv)

    for name in ("_build_gateway_cmd_script", "_build_gateway_vbs_script"):
        current = getattr(gateway_windows, name)
        if getattr(current, "__faye_wrapper__", False):
            continue

        def gateway_script(*args: Any, _current: Any = current, **kwargs: Any) -> str:
            return _current(*args, **kwargs).replace(
                "-m hermes_cli.main", "-m faye.child_entry"
            )

        gateway_script.__faye_wrapper__ = True  # type: ignore[attr-defined]
        setattr(gateway_windows, name, gateway_script)

    current_windows_argv = gateway_windows._build_gateway_argv
    if not getattr(current_windows_argv, "__faye_wrapper__", False):

        def build_gateway_argv() -> tuple[list[str], str, dict[str, str]]:
            argv, working_dir, env = current_windows_argv()
            effective_home = Path(env["HERMES_HOME"])
            env["FAYE_HOME"] = str(
                effective_home.parent.parent
                if effective_home.parent.name == "profiles"
                else effective_home
            )
            return _replace_child_module(argv), working_dir, env

        build_gateway_argv.__faye_wrapper__ = True  # type: ignore[attr-defined]
        gateway_windows._build_gateway_argv = build_gateway_argv


def validate_engine() -> None:
    installed = metadata.version(ENGINE_DISTRIBUTION)
    if installed != ENGINE_VERSION:
        raise RuntimeError(
            f"Faye requires {ENGINE_DISTRIBUTION}=={ENGINE_VERSION}; found {installed}. "
            "Reinstall Faye to restore a supported runtime."
        )


def run_engine() -> None:
    prepare_environment()
    isolate_engine_imports()
    validate_engine()
    patch_engine_parser()
    import hermes_cli.main as engine_main

    patch_engine_runtime(engine_main)
    patch_engine_startup_content()
    patch_engine_skin()
    patch_engine_subprocesses()
    sys.argv[0] = "faye"
    if not engine_main._has_any_provider_configured():
        with (
            redirect_stdout(_FirstRunBrandingStream(sys.stdout)),
            redirect_stderr(_FirstRunBrandingStream(sys.stderr)),
        ):
            engine_main.main()
        return
    engine_main.main()
