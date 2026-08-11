import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "scripts" / "ensure-runtime.sh"


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _run_watchdog(tmp_path: Path, colima_ready: bool) -> str:
    state = tmp_path / "colima-ready"
    calls = tmp_path / "calls.log"
    if colima_ready:
        state.touch()

    colima = tmp_path / "colima"
    launchctl = tmp_path / "launchctl"
    docker = tmp_path / "docker"
    nc = tmp_path / "nc"
    sleep = tmp_path / "sleep"
    plist = tmp_path / "colima.plist"
    plist.touch()

    _write_executable(
        colima,
        'printf "colima %s\\n" "$*" >> "$CALLS_FILE"\n'
        'if [[ "${1:-}" == "status" ]]; then test -f "$STATE_FILE"; exit; fi\n'
        'if [[ "${1:-}" == "stop" ]]; then rm -f "$STATE_FILE"; fi\n',
    )
    _write_executable(
        launchctl,
        'printf "launchctl %s\\n" "$*" >> "$CALLS_FILE"\n'
        'if [[ "${1:-}" == "bootstrap" ]]; then touch "$STATE_FILE"; fi\n',
    )
    _write_executable(docker, 'printf "docker %s\\n" "$*" >> "$CALLS_FILE"\n')
    _write_executable(nc, 'printf "nc %s\\n" "$*" >> "$CALLS_FILE"\n')
    _write_executable(sleep, ':\n')

    env = os.environ | {
        "HAW_PROJECT_DIR": str(ROOT),
        "COLIMA_BIN": str(colima),
        "DOCKER_BIN": str(docker),
        "LAUNCHCTL_BIN": str(launchctl),
        "NC_BIN": str(nc),
        "SLEEP_BIN": str(sleep),
        "COLIMA_PLIST": str(plist),
        "HAW_RUNTIME_ATTEMPTS": "1",
        "HAW_RUNTIME_INTERVAL_SECONDS": "0",
        "STATE_FILE": str(state),
        "CALLS_FILE": str(calls),
    }
    result = subprocess.run(
        [str(WATCHDOG)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return calls.read_text(encoding="utf-8") + result.stdout


def test_watchdog_keeps_a_healthy_runtime_and_reconciles_the_database(tmp_path: Path) -> None:
    output = _run_watchdog(tmp_path, colima_ready=True)

    assert "launchctl bootout" not in output
    assert "docker compose up -d db" in output
    assert "docker compose exec -T db pg_isready" in output
    assert "HumanAgentWiki runtime is healthy." in output


def test_watchdog_recovers_stale_colima_before_starting_the_database(tmp_path: Path) -> None:
    output = _run_watchdog(tmp_path, colima_ready=False)

    assert "launchctl bootout" in output
    assert "colima stop --force" in output
    assert "launchctl bootstrap" in output
    assert "launchctl kickstart" in output
    assert output.index("launchctl bootstrap") < output.index("docker compose up -d db")
