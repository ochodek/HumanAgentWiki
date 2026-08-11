"""Unit tests for the pure helpers (no database or model needed).

Run:  pip install -r requirements-dev.txt  &&  pytest
"""
import os
import pytest

import index
import web


# ---------- index.py ----------
def test_parse_frontmatter_basic():
    fm, body = index.parse_frontmatter("---\ntitle: Hello\ncategory: Books\n---\n\nBody text")
    assert fm["title"] == "Hello"
    assert fm["category"] == "Books"
    assert body.strip() == "Body text"


def test_parse_frontmatter_strips_quotes():
    fm, _ = index.parse_frontmatter('---\ntitle: "Quoted"\n---\nx')
    assert fm["title"] == "Quoted"


def test_parse_frontmatter_none():
    fm, body = index.parse_frontmatter("No frontmatter here")
    assert fm == {}
    assert body == "No frontmatter here"


def test_split_blocks_on_headings():
    blocks = index.split_blocks("intro\n## Alpha\naaa\n### Beta\nbbb")
    headers = [h for h, _ in blocks]
    assert "Alpha" in headers and "Beta" in headers


def test_category_of():
    assert index.category_of(os.path.join("Books", "x.md")) == "Books"
    assert index.category_of("root.md") == os.path.basename(index.NOTES_DIR.rstrip(os.sep))


def test_link_regex():
    assert index.LINK_RE.findall("see [[Alpha]] and [[Beta]]") == ["Alpha", "Beta"]


def test_prepare_files_fails_before_embedding_when_any_note_is_invalid(monkeypatch):
    processed = []

    def process_file(path):
        processed.append(path)
        if path == "bad.md":
            raise UnicodeError("invalid note")
        return [{"emb_text": "valid"}]

    monkeypatch.setattr(index, "process_file", process_file)
    monkeypatch.setattr(index, "embed", lambda *_args, **_kwargs: pytest.fail("embed must not run"))

    with pytest.raises(UnicodeError, match="invalid note"):
        index.prepare_files(["good.md", "bad.md"])

    assert processed == ["good.md", "bad.md"]


# ---------- web.py ----------
def test_health_endpoint_proves_database_readability(monkeypatch):
    statements = []

    class Connection:
        def execute(self, statement):
            statements.append(statement)

        def close(self):
            statements.append("closed")

    monkeypatch.setattr(web, "connect", lambda: Connection())

    assert web.healthz() == {"service": "HumanAgentWiki", "status": "ok"}
    assert statements == ["SELECT 1", "closed"]


def test_slugify():
    assert web.slugify("Hello, World!") == "hello-world"
    assert web.slugify("   ") == "note"


@pytest.mark.parametrize("bad", ["../evil.md", "/abs/x.md", "notes.txt", "a/../../x.md"])
def test_safe_md_path_rejects(bad):
    with pytest.raises(Exception):
        web.safe_md_path(bad)


def test_safe_md_path_accepts_relative_md():
    p = web.safe_md_path("Books/note.md")
    assert p.endswith(os.path.join("Books", "note.md"))
