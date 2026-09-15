import os
import plistlib
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "scripts" / "ensure-runtime.sh"
OPS = ROOT / "ops"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run_watchdog(
    tmp_path: Path,
    colima_ready: bool,
    *,
    mcp_ready: bool = True,
    web_ready: bool = True,
    web_recovers: bool = True,
    docker_ready: bool = True,
    docker_recovers: bool = True,
    database_ready: bool = True,
    database_recovers: bool = True,
    runtime_service_mode: str | None = None,
    allow_failure: bool = False,
) -> str:
    state = tmp_path / "colima-ready"
    docker_state = tmp_path / "docker-ready"
    database_state = tmp_path / "database-ready"
    mcp_state = tmp_path / "mcp-ready"
    web_state = tmp_path / "web-ready"
    calls = tmp_path / "calls.log"
    if colima_ready:
        state.touch()
    if docker_ready:
        docker_state.touch()
    if database_ready:
        database_state.touch()
    if mcp_ready:
        mcp_state.touch()
    if web_ready:
        web_state.touch()

    colima = tmp_path / "colima"
    launchctl = tmp_path / "launchctl"
    docker = tmp_path / "docker"
    nc = tmp_path / "nc"
    curl = tmp_path / "curl"
    sleep = tmp_path / "sleep"
    plist = tmp_path / "colima.plist"
    plist.touch()

    _write_executable(
        colima,
        'printf "colima %s\\n" "$*" >> "$CALLS_FILE"\n'
        'if [[ "${1:-}" == "status" ]]; then test -f "$STATE_FILE"; exit; fi\n'
        'if [[ "${1:-}" == "stop" ]]; then rm -f "$STATE_FILE"; fi\n'
        'if [[ "${1:-}" == "restart" && "$DOCKER_RECOVERS" == "1" ]]; then\n'
        '  touch "$STATE_FILE" "$DOCKER_STATE_FILE"\n'
        'fi\n',
    )
    _write_executable(
        launchctl,
        'printf "launchctl %s\\n" "$*" >> "$CALLS_FILE"\n'
        'if [[ "${1:-}" == "bootstrap" ]]; then touch "$STATE_FILE"; fi\n'
        'case "$*" in\n'
        '  *homebrew.mxcl.colima*) touch "$STATE_FILE" ;;\n'
        '  *humanagentwiki.mcp*) touch "$MCP_STATE_FILE" ;;\n'
        '  *humanagentwiki.web*)\n'
        '    if [[ "$WEB_RECOVERS" == "1" ]]; then touch "$WEB_STATE_FILE"; fi ;;\n'
        'esac\n',
    )
    _write_executable(
        docker,
        'printf "docker %s\\n" "$*" >> "$CALLS_FILE"\n'
        'if [[ "$*" == "info" ]]; then test -f "$DOCKER_STATE_FILE"; exit; fi\n'
        'if [[ "$*" == *"pg_isready"* ]]; then test -f "$DATABASE_STATE_FILE"; exit; fi\n'
        'if [[ "$*" == "compose restart db" && "$DATABASE_RECOVERS" == "1" ]]; then\n'
        '  touch "$DATABASE_STATE_FILE"\n'
        'fi\n',
    )
    _write_executable(
        nc,
        'printf "nc %s\\n" "$*" >> "$CALLS_FILE"\n'
        'case "${3:-}" in\n'
        '  8802) test -f "$MCP_STATE_FILE" ;;\n'
        '  8808) test -f "$WEB_STATE_FILE" ;;\n'
        '  *) exit 1 ;;\n'
        'esac\n',
    )
    _write_executable(
        curl,
        'printf "curl %s\\n" "$*" >> "$CALLS_FILE"\n'
        'test -f "$WEB_STATE_FILE"\n'
        'printf \'{"service":"HumanAgentWiki","status":"ok"}\'\n',
    )
    _write_executable(sleep, ':\n')

    env = os.environ | {
        "HAW_PROJECT_DIR": str(ROOT),
        "COLIMA_BIN": str(colima),
        "DOCKER_BIN": str(docker),
        "LAUNCHCTL_BIN": str(launchctl),
        "NC_BIN": str(nc),
        "CURL_BIN": str(curl),
        "SLEEP_BIN": str(sleep),
        "COLIMA_PLIST": str(plist),
        "HAW_RUNTIME_ATTEMPTS": "1",
        "HAW_RUNTIME_INTERVAL_SECONDS": "0",
        "STATE_FILE": str(state),
        "DOCKER_STATE_FILE": str(docker_state),
        "DATABASE_STATE_FILE": str(database_state),
        "MCP_STATE_FILE": str(mcp_state),
        "WEB_STATE_FILE": str(web_state),
        "WEB_RECOVERS": "1" if web_recovers else "0",
        "DOCKER_RECOVERS": "1" if docker_recovers else "0",
        "DATABASE_RECOVERS": "1" if database_recovers else "0",
        "CALLS_FILE": str(calls),
    }
    if runtime_service_mode is not None:
        env["HAW_RUNTIME_SERVICE_MODE"] = runtime_service_mode

    result = subprocess.run(
        [str(WATCHDOG)],
        check=not allow_failure,
        capture_output=True,
        text=True,
        env=env,
    )
    if allow_failure and result.returncode == 0:
        raise AssertionError("watchdog unexpectedly reported a healthy runtime")

    return calls.read_text(encoding="utf-8") + result.stdout


def test_watchdog_keeps_a_healthy_runtime_and_reconciles_the_database(tmp_path: Path) -> None:
    output = _run_watchdog(tmp_path, colima_ready=True)

    assert "launchctl bootout" not in output
    assert "docker compose up -d db" in output
    assert "docker compose exec -T db pg_isready" in output
    assert "humanagentwiki.mcp" not in output
    assert "humanagentwiki.web" not in output
    assert "HumanAgentWiki runtime is healthy." in output


def test_watchdog_recovers_stale_colima_before_starting_the_database(tmp_path: Path) -> None:
    output = _run_watchdog(tmp_path, colima_ready=False)

    assert "launchctl bootout" not in output
    assert "colima stop --force" not in output
    assert "launchctl kickstart" in output
    assert output.index("launchctl kickstart") < output.index("docker compose up -d db")


def test_watchdog_gracefully_recovers_docker_when_colima_is_running(tmp_path: Path) -> None:
    output = _run_watchdog(tmp_path, colima_ready=True, docker_ready=False)

    assert "colima restart" in output
    assert "colima stop --force" not in output
    assert output.count("docker info") >= 2
    assert output.index("colima restart") < output.index("docker compose up -d db")


def test_watchdog_fails_loud_when_docker_does_not_recover(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _run_watchdog(
            tmp_path,
            colima_ready=True,
            docker_ready=False,
            docker_recovers=False,
        )


def test_watchdog_restarts_an_unhealthy_database_without_recreating_its_volume(
    tmp_path: Path,
) -> None:
    output = _run_watchdog(tmp_path, colima_ready=True, database_ready=False)

    assert "docker compose restart db" in output
    assert "docker compose down" not in output
    assert "docker volume" not in output


def test_watchdog_fails_loud_when_the_database_does_not_recover(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _run_watchdog(
            tmp_path,
            colima_ready=True,
            database_ready=False,
            database_recovers=False,
        )


def test_watchdog_restarts_the_web_ui_when_its_port_is_unavailable(tmp_path: Path) -> None:
    output = _run_watchdog(tmp_path, colima_ready=True, web_ready=False)

    assert "HumanAgentWiki web UI is unavailable" in output
    assert "launchctl kickstart -k gui/" in output
    assert "com.jarvis.humanagentwiki.web" in output
    assert "com.jarvis.humanagentwiki.mcp" not in output


def test_watchdog_restarts_each_unavailable_agent_interface(tmp_path: Path) -> None:
    output = _run_watchdog(
        tmp_path,
        colima_ready=True,
        mcp_ready=False,
        web_ready=False,
    )

    assert "com.jarvis.humanagentwiki.mcp" in output
    assert "com.jarvis.humanagentwiki.web" in output


def test_watchdog_fails_loud_when_the_web_ui_does_not_recover(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _run_watchdog(
            tmp_path,
            colima_ready=True,
            web_ready=False,
            web_recovers=False,
        )


def test_watchdog_rejects_an_unknown_runtime_service_mode(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        _run_watchdog(
            tmp_path,
            colima_ready=True,
            runtime_service_mode="invalid",
        )


def test_system_mode_never_invokes_launchctl_for_a_healthy_runtime(tmp_path: Path) -> None:
    output = _run_watchdog(
        tmp_path,
        colima_ready=True,
        runtime_service_mode="system",
    )

    assert "launchctl" not in output
    assert "colima restart" not in output
    assert "docker compose up -d db" in output


@pytest.mark.parametrize(
    ("colima_ready", "docker_ready", "mcp_ready", "web_ready", "expected_message"),
    [
        (False, True, True, True, "Colima did not become ready"),
        (True, False, True, True, "Docker did not become ready"),
        (True, True, False, True, "MCP is unavailable; system launchd must restore it."),
        (True, True, True, False, "web UI is unavailable; system launchd must restore it."),
    ],
)
def test_system_mode_fails_without_restarting_launchd_owned_services(
    tmp_path: Path,
    colima_ready: bool,
    docker_ready: bool,
    mcp_ready: bool,
    web_ready: bool,
    expected_message: str,
) -> None:
    output = _run_watchdog(
        tmp_path,
        colima_ready=colima_ready,
        docker_ready=docker_ready,
        mcp_ready=mcp_ready,
        web_ready=web_ready,
        runtime_service_mode="system",
        allow_failure=True,
    )

    assert expected_message in output
    assert "launchctl" not in output
    assert "colima restart" not in output


def test_launch_agents_keep_both_agent_interfaces_running() -> None:
    expected_commands = {
        "mcp": "serve",
        "web": "web",
    }

    for interface, command in expected_commands.items():
        path = OPS / f"com.jarvis.humanagentwiki.{interface}.plist"
        with path.open("rb") as file:
            config = plistlib.load(file)

        assert config["RunAtLoad"] is True
        assert config["KeepAlive"] is True
        assert config["ProgramArguments"][-1] == command


def test_launch_agent_templates_do_not_embed_a_checkout_owner() -> None:
    for path in OPS.glob("com.jarvis.humanagentwiki.*.plist"):
        source = path.read_text(encoding="utf-8")

        assert "/Users/jarvis" not in source
