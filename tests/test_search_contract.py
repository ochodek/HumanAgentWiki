from cli import build_parser
from server import _filters, _hit


def test_confirmed_global_preferences_use_structured_filters():
    clause, params = _filters("Preferences", "", "confirmed", "global")

    assert "category = %s" in clause
    assert "meta->>'memory_status' = %s" in clause
    assert "meta->>'memory_scope' = %s" in clause
    assert params == ["Preferences", "confirmed", "global"]


def test_search_result_carries_file_and_evidence_metadata_as_provenance():
    hit = _hit({
        "id": 1,
        "file": "Preferences/example.md",
        "category": "Preferences",
        "node_type": "note",
        "title": "Example",
        "links": [],
        "text": "Confirmed preference",
        "meta": {"memory_status": "confirmed", "memory_scope": "global"},
    })

    assert hit["file"] == "Preferences/example.md"
    assert hit["meta"]["memory_status"] == "confirmed"


def test_option_like_query_is_not_parsed_as_a_cli_option_after_separator():
    args = build_parser().parse_args([
        "search",
        "--category", "Preferences",
        "--memory-status", "confirmed",
        "--json",
        "--",
        "--help",
    ])

    assert args.query == "--help"
    assert args.memory_status == "confirmed"
    assert args.json is True
