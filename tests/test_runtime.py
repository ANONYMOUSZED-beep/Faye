from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from faye import __version__
from faye.runtime import (
    ENGINE_VERSION,
    FAYE_DIGITAL_HERO,
    FAYE_IDENTITY,
    LEGACY_FAYE_HERO,
    bootstrap_faye_home,
    default_faye_home,
    isolate_engine_imports,
    migrate_hermes_state,
    patch_engine_parser,
    patch_engine_skin,
    patch_engine_startup_content,
    patch_engine_subprocesses,
    prepare_environment,
)


def test_faye_identity_uses_openbench_branding():
    assert "Openbench" in FAYE_IDENTITY
    assert "Nous Research" not in FAYE_IDENTITY


def test_prepare_environment_owns_isolated_state(tmp_path):
    home = tmp_path / "faye-home"
    env = {
        "FAYE_HOME": str(home),
        "HERMES_HOME": str(tmp_path / "must-not-be-used"),
    }

    resolved = prepare_environment(env)

    assert resolved == home.absolute()
    assert env["FAYE_HOME"] == str(home.absolute())
    assert env["HERMES_HOME"] == str(home.absolute())
    assert (home / "SOUL.md").read_text(encoding="utf-8").startswith("# Faye Identity")
    assert "agent_name: \"Faye\"" in (home / "skins" / "faye.yaml").read_text(
        encoding="utf-8"
    )
    assert (home / "config.yaml").read_text(encoding="utf-8") == (
        "display:\n  skin: faye\n"
    )
    marker = json.loads((home / ".faye-distribution.json").read_text(encoding="utf-8"))
    assert marker == {
        "distribution": "faye-agent",
        "engine": "hermes-agent",
        "engine_version": ENGINE_VERSION,
        "version": __version__,
    }


def test_bootstrap_never_overwrites_user_customization(tmp_path):
    home = tmp_path / "home"
    (home / "skins").mkdir(parents=True)
    (home / "SOUL.md").write_text("custom soul", encoding="utf-8")
    (home / "config.yaml").write_text("model:\n  provider: custom\n", encoding="utf-8")
    (home / "skins" / "faye.yaml").write_text("custom skin", encoding="utf-8")

    bootstrap_faye_home(home)

    assert (home / "SOUL.md").read_text(encoding="utf-8") == "custom soul"
    assert (home / "config.yaml").read_text(encoding="utf-8") == (
        "model:\n  provider: custom\n"
    )
    assert (home / "skins" / "faye.yaml").read_text(encoding="utf-8") == "custom skin"


def test_default_home_prefers_explicit_faye_home(tmp_path):
    assert default_faye_home({"FAYE_HOME": str(tmp_path)}) == tmp_path.absolute()


def test_default_home_is_dot_faye_even_when_local_app_data_exists(tmp_path):
    assert default_faye_home({"LOCALAPPDATA": str(tmp_path)}) == (
        Path.home() / ".faye"
    ).absolute()


def test_engine_isolation_preserves_unrelated_python_paths(tmp_path, monkeypatch):
    unrelated = tmp_path / "custom-python"
    unrelated.mkdir()
    foreign = tmp_path / "foreign-engine"
    (foreign / "hermes_cli").mkdir(parents=True)
    monkeypatch.setattr(sys, "path", [str(foreign), str(unrelated), *sys.path])
    env = {"PYTHONPATH": os.pathsep.join((str(foreign), str(unrelated)))}

    engine_root = isolate_engine_imports(env)

    assert Path(sys.path[0]).resolve() == engine_root
    assert str(foreign) not in sys.path
    assert str(unrelated) in sys.path
    assert env["PYTHONPATH"] == str(unrelated)


def test_migration_copies_state_without_overwriting_faye_customization(tmp_path):
    source = tmp_path / "hermes"
    destination = tmp_path / "faye"
    (source / "skills" / "custom").mkdir(parents=True)
    (source / "skills" / "custom" / "SKILL.md").write_text("source skill", encoding="utf-8")
    (source / "config.yaml").write_text("model:\n  provider: source\n", encoding="utf-8")
    destination.mkdir()
    (destination / "config.yaml").write_text("display:\n  skin: faye\n", encoding="utf-8")

    result = migrate_hermes_state(source, destination)

    assert result.copied == 1
    assert result.skipped == 1
    assert (destination / "skills" / "custom" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "source skill"
    assert (destination / "config.yaml").read_text(encoding="utf-8") == (
        "display:\n  skin: faye\n"
    )
    assert (source / "config.yaml").read_text(encoding="utf-8") == (
        "model:\n  provider: source\n"
    )


def test_migration_dry_run_writes_nothing(tmp_path):
    source = tmp_path / "hermes"
    destination = tmp_path / "faye"
    source.mkdir()
    (source / "auth.json").write_text("{}", encoding="utf-8")

    result = migrate_hermes_state(source, destination, dry_run=True)

    assert result.copied == 1
    assert result.skipped == 0
    assert not destination.exists()


def test_migration_rejects_missing_or_overlapping_source(tmp_path):
    destination = tmp_path / "faye"
    destination.mkdir()

    with pytest.raises(FileNotFoundError):
        migrate_hermes_state(tmp_path / "missing", destination)
    with pytest.raises(ValueError, match="must be different"):
        migrate_hermes_state(destination, destination)


def test_migration_rejects_destination_symlink_escape(tmp_path):
    source = tmp_path / "hermes"
    destination = tmp_path / "faye"
    outside = tmp_path / "outside"
    (source / "secrets").mkdir(parents=True)
    destination.mkdir()
    outside.mkdir()
    (source / "secrets" / "auth.json").write_text("secret", encoding="utf-8")
    try:
        (destination / "secrets").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")

    with pytest.raises(ValueError, match="symlink or reparse point"):
        migrate_hermes_state(source, destination)

    assert not (outside / "auth.json").exists()


def test_engine_parser_is_rebranded_and_keeps_all_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("FAYE_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    patch_engine_parser()
    from hermes_cli._parser import build_top_level_parser

    parser, subparsers, _chat = build_top_level_parser()

    assert parser.prog == "faye"
    assert parser.description == "Faye - production autonomous AI assistant"
    assert "chat" in subparsers.choices
    assert "migrate-hermes" in subparsers.choices


def test_engine_startup_content_is_rebranded(monkeypatch):
    import agent.onboarding as onboarding
    import hermes_cli.tips as tips

    monkeypatch.setattr(
        tips,
        "TIPS",
        ["hermes dashboard embeds the full Hermes TUI from ~/.hermes."],
    )
    monkeypatch.setattr(
        onboarding,
        "openclaw_residue_hint_cli",
        lambda: "Port data to Hermes with `hermes claw migrate`.",
    )

    patch_engine_startup_content()

    assert tips.TIPS == ["faye dashboard embeds the full Faye TUI from ~/.faye."]
    assert onboarding.openclaw_residue_hint_cli() == (
        "Port data to Faye with `faye claw migrate`."
    )


def test_digital_faye_portrait_is_terminal_safe_and_preserves_custom_art():
    from importlib import resources

    import hermes_cli.skin_engine as skin_engine
    import yaml
    from rich.cells import cell_len
    from rich.text import Text

    packaged = yaml.safe_load(
        resources.files("faye.assets").joinpath("faye.yaml").read_text(encoding="utf-8")
    )
    assert packaged["banner_hero"] == FAYE_DIGITAL_HERO

    rendered = Text.from_markup(FAYE_DIGITAL_HERO).plain
    assert "F A Y E // 01" in rendered
    assert "ONLINE" in rendered
    assert len(rendered.splitlines()) == 13
    assert max(cell_len(line) for line in rendered.splitlines()) <= 24

    patch_engine_skin()
    upgraded = skin_engine._build_skin_config(
        {"name": "faye", "banner_hero": LEGACY_FAYE_HERO}
    )
    custom = skin_engine._build_skin_config(
        {"name": "custom", "banner_hero": "CUSTOM USER ART"}
    )
    assert upgraded.banner_hero == FAYE_DIGITAL_HERO
    assert custom.banner_hero == "CUSTOM USER ART"


def test_engine_children_route_through_faye(tmp_path, monkeypatch):
    monkeypatch.setenv("FAYE_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    patch_engine_subprocesses()

    import hermes_cli.gateway as gateway
    import hermes_cli.gateway_windows as gateway_windows
    import hermes_cli.relaunch as relaunch

    assert relaunch.build_relaunch_argv(["status"])[1:3] == [
        "-m",
        "faye.child_entry",
    ]
    assert "faye.child_entry" in gateway._gateway_run_args_for_profile("demo")
    assert "faye.child_entry" in gateway._gateway_run_command()

    systemd_unit = gateway.generate_systemd_unit()
    launchd_plist = gateway.generate_launchd_plist()
    assert "-m faye.child_entry" in systemd_unit
    assert "-m hermes_cli.main" not in systemd_unit
    assert "<string>faye.child_entry</string>" in launchd_plist
    assert "<string>hermes_cli.main</string>" not in launchd_plist

    script = gateway_windows._build_gateway_cmd_script(
        sys.executable, str(tmp_path), str(tmp_path), ""
    )
    assert "-m faye.child_entry" in script
    assert "-m hermes_cli.main" not in script

    if sys.platform == "win32":
        argv, _working_dir, env = gateway_windows._build_gateway_argv()
        assert "faye.child_entry" in argv
        assert env["FAYE_HOME"] == env["HERMES_HOME"]

        elevated: dict[str, str] = {}

        def shell_execute(_hwnd, _verb, executable, parameters, cwd, _show):
            elevated.update(
                executable=executable,
                parameters=parameters,
                cwd=cwd,
            )
            return 42

        monkeypatch.setattr(
            gateway_windows.ctypes.windll.shell32,
            "ShellExecuteW",
            shell_execute,
        )
        assert gateway_windows._launch_elevated_gateway_command("install")
        assert "faye.child_entry" in elevated["parameters"]
        assert "hermes_cli.main" not in elevated["parameters"]


def test_engine_lifecycle_commands_fail_closed(capsys):
    import hermes_cli.main as engine_main

    from faye.runtime import patch_engine_runtime

    patch_engine_runtime(engine_main)
    for command in (engine_main.cmd_update, engine_main.cmd_uninstall):
        with pytest.raises(SystemExit) as error:
            command(object())
        assert error.value.code == 2
    assert "uv tool upgrade faye-agent" in capsys.readouterr().err


def test_child_entry_recovers_root_from_named_profile():
    from faye.child_entry import _faye_root_from_effective_home

    root = Path("root").absolute()
    assert _faye_root_from_effective_home(str(root)) == str(root)
    assert _faye_root_from_effective_home(str(root / "profiles" / "work")) == str(root)


def test_migrate_hermes_cli_dry_run(tmp_path):
    source = tmp_path / "hermes"
    destination = tmp_path / "faye"
    source.mkdir()
    (source / "auth.json").write_text("{}", encoding="utf-8")
    env = os.environ.copy()
    env["FAYE_HOME"] = str(destination)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "faye.cli",
            "migrate-hermes",
            "--source",
            str(source),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr
    assert "Would copy 1 file(s); skip 0 existing file(s)." in result.stdout
    assert not destination.exists()


def test_migrate_hermes_cli_validates_overlap_before_bootstrap(tmp_path):
    source = tmp_path / "hermes"
    source.mkdir()
    env = os.environ.copy()
    env["FAYE_HOME"] = str(source)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "faye.cli",
            "migrate-hermes",
            "--source",
            str(source),
            "--destination",
            str(source),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=90,
    )

    assert result.returncode != 0
    assert "must be different" in result.stderr
    assert list(source.iterdir()) == []


def test_unconfigured_interactive_start_uses_faye_setup_guidance(tmp_path):
    from hermes_cli.auth import PROVIDER_REGISTRY

    env = os.environ.copy()
    provider_env_vars = {
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_TOKEN",
        "OPENAI_BASE_URL",
    }
    for provider in PROVIDER_REGISTRY.values():
        if provider.auth_type == "api_key":
            provider_env_vars.update(provider.api_key_env_vars)
    for variable in provider_env_vars:
        env.pop(variable, None)

    isolated_user = tmp_path / "user"
    env.update(
        {
            "FAYE_HOME": str(tmp_path / "state"),
            "HOME": str(isolated_user),
            "USERPROFILE": str(isolated_user),
            "APPDATA": str(isolated_user / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(isolated_user / "AppData" / "Local"),
            "GH_CONFIG_DIR": str(isolated_user / "gh"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "faye.cli", "--cli"],
        input="/exit\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=90,
    )

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "Faye isn't configured yet" in output
    assert "Faye Setup" in output
    assert "faye setup" in output
    assert "Hermes Setup" not in output
    assert "hermes setup" not in output


def test_status_recommends_faye_commands(tmp_path):
    env = os.environ.copy()
    env["FAYE_HOME"] = str(tmp_path / "state")
    result = subprocess.run(
        [sys.executable, "-m", "faye.cli", "status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "run: hermes " not in output
    assert "Run 'hermes " not in output
    assert "run: faye " in output or "Run 'faye " in output


@pytest.mark.parametrize("arguments", [["--help"], ["--version"], ["status", "--help"]])
def test_real_faye_cli_smoke(arguments, tmp_path):
    env = os.environ.copy()
    env["FAYE_HOME"] = str(tmp_path / "state")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "faye.cli", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert "Faye" in output or "faye" in output
    assert str(tmp_path / "state") in os.environ.get("FAYE_HOME", "") or (
        tmp_path / "state" / "SOUL.md"
    ).exists()
