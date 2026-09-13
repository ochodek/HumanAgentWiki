from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mcp_dependency_stays_on_the_fastmcp_compatible_major() -> None:
    """The server imports mcp.server.fastmcp, which is not available in MCP 2.x."""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert "mcp>=1.2,<2" in requirements


def test_actions_run_only_on_demand_to_preserve_the_approved_minutes_budget() -> None:
    workflow = (ROOT / ".github/workflows/delivery-gate.yml").read_text(encoding="utf-8")
    assert "  workflow_dispatch:" in workflow
    assert "  push:" not in workflow
    assert "  pull_request:" not in workflow
    assert "tests/test_browser_gate.py" in workflow
