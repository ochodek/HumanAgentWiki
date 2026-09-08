"""Production browser gate using only a disposable wiki."""
import os
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright, expect


EXPECTED_STATIC_ASSETS = {
    "/static/3d-force-graph.min.js",
    "/static/marked.min.js",
}


def test_notes_remain_searchable_when_their_category_is_hidden_from_the_graph():
    """Saving, hiding and restoring a category must preserve its searchable notes."""
    base_url = os.environ.get("HAW_BROWSER_BASE_URL")
    if not base_url:
        pytest.skip("browser gate requires HAW_BROWSER_BASE_URL")
    base_url = base_url.rstrip("/")
    browser_failures = []
    api_failures = []
    server_failures = []
    static_failures = []
    static_assets = set()
    origin = urlsplit(base_url).netloc
    username = os.environ.get("HAW_BROWSER_HTTP_USERNAME")
    password = os.environ.get("HAW_BROWSER_HTTP_PASSWORD")
    assert bool(username) == bool(password), (
        "browser HTTP username and password must be configured together"
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context_options = {}
        if username and password:
            context_options["http_credentials"] = {
                "username": username,
                "password": password,
            }
        context = browser.new_context(**context_options)
        page = context.new_page()
        page.on("pageerror", lambda error: browser_failures.append(str(error)))
        page.on(
            "console",
            lambda message: browser_failures.append(message.text)
            if message.type == "error"
            else None,
        )

        def record_response(response):
            parsed = urlsplit(response.url)
            if parsed.netloc != origin:
                return
            if response.status >= 500:
                server_failures.append(f"{response.status} {parsed.path}")
            if parsed.path.startswith("/api/") and response.status >= 400:
                api_failures.append(f"{response.status} {parsed.path}")
            if parsed.path.startswith("/static/"):
                static_assets.add(parsed.path)
                if response.status >= 400:
                    static_failures.append(f"{response.status} {parsed.path}")

        def record_failed_request(request):
            parsed = urlsplit(request.url)
            if parsed.netloc == origin and parsed.path.startswith("/static/"):
                static_failures.append(f"request failed {parsed.path}: {request.failure}")

        page.on("response", record_response)
        page.on("requestfailed", record_failed_request)
        response = page.goto(base_url, wait_until="networkidle")

        assert response is not None, "the UI entry point did not return a response"
        assert response.ok, f"the UI entry point returned HTTP {response.status}"
        assert page.locator("h1", has_text="HumanAgentWiki").count() == 1
        page.locator("#graph canvas").wait_for(state="attached", timeout=15_000)
        page.locator("#leg-edit").click()
        page.locator("#newcat").fill("Gate fixture")
        with page.expect_response(
            lambda response: response.url.endswith("/api/categories") and response.request.method == "POST"
        ) as added:
            page.locator("#newcat").press("Enter")
        assert added.value.ok
        expect(page.locator('#legend .lname', has_text="Gate fixture")).to_be_visible()
        page.locator("#newnote").click()
        page.locator("#edit-title").fill("Synthetic delivery note")
        page.locator("#edit-cat").select_option(label="Gate fixture")
        page.locator("#edit-area").fill("A synthetic note for the production delivery gate.")
        with page.expect_response(
            lambda response: response.url.endswith("/api/note") and response.request.method == "POST",
            timeout=180_000,
        ) as saved:
            page.locator("#edit-save").click()
        assert saved.value.ok
        note_file = saved.value.json()["file"]
        expect(page.locator("#note-body")).to_contain_text("synthetic note", timeout=30_000)
        graph = context.request.get(f"{base_url}/api/graph").json()
        assert any(node["id"] == note_file for node in graph["nodes"])

        toggle = page.locator('[data-gtog="Gate fixture"]')
        with page.expect_response("**/api/category-graph") as hidden:
            toggle.click()
        assert hidden.value.ok
        page.reload(wait_until="networkidle")
        graph = context.request.get(f"{base_url}/api/graph").json()
        assert not any(node["id"] == note_file for node in graph["nodes"])
        page.locator("#search").fill("Synthetic delivery note")
        result = page.locator("#results .res", has_text="Synthetic delivery note")
        expect(result).to_be_visible(timeout=60_000)
        result.click()
        expect(page.locator("#note-body")).to_contain_text("synthetic note")
        search = context.request.get(f"{base_url}/api/search", params={"q": "Synthetic delivery note"})
        assert search.ok
        assert any(hit["file"] == note_file and hit["updated"] for hit in search.json())

        if page.locator('[data-gtog="Gate fixture"]').count() == 0:
            page.locator("#leg-edit").click()
        with page.expect_response("**/api/category-graph") as restored:
            page.locator('[data-gtog="Gate fixture"]').click()
        assert restored.value.ok
        page.reload(wait_until="networkidle")
        graph = context.request.get(f"{base_url}/api/graph").json()
        assert any(node["id"] == note_file for node in graph["nodes"])
        assert EXPECTED_STATIC_ASSETS <= static_assets, (
            f"missing static assets: {sorted(EXPECTED_STATIC_ASSETS - static_assets)}"
        )
        assert not browser_failures, f"browser errors: {browser_failures}"
        assert not server_failures, f"same-origin HTTP 5xx responses: {server_failures}"
        assert not static_failures, f"failed static assets: {static_failures}"
        assert not api_failures, f"unexpected API failures: {api_failures}"
        browser.close()
