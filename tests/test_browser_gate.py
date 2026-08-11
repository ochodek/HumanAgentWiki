"""Production browser smoke test for the empty HumanAgentWiki UI."""
import os
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright


EXPECTED_STATIC_ASSETS = {
    "/static/3d-force-graph.min.js",
    "/static/marked.min.js",
}


def test_empty_wiki_ui_loads_without_browser_or_api_failures():
    """An empty, disposable wiki must still render its heading and 3D graph."""
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
        response = page.goto(f"{base_url}/static/index.html", wait_until="networkidle")

        assert response is not None, "the UI entry point did not return a response"
        assert response.ok, f"the UI entry point returned HTTP {response.status}"
        assert page.locator("h1", has_text="HumanAgentWiki").count() == 1
        page.locator("#graph canvas").wait_for(state="attached", timeout=15_000)
        assert EXPECTED_STATIC_ASSETS <= static_assets, (
            f"missing static assets: {sorted(EXPECTED_STATIC_ASSETS - static_assets)}"
        )
        assert not browser_failures, f"browser errors: {browser_failures}"
        assert not server_failures, f"same-origin HTTP 5xx responses: {server_failures}"
        assert not static_failures, f"failed static assets: {static_failures}"
        assert not api_failures, f"unexpected API failures: {api_failures}"
        browser.close()
