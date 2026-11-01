"""The web-tool debug record (``WEB_TOOLS_DEBUG``) must name the provider that was asked for and say
when the answer actually came from somewhere else.

Regression for #133473: a rescued call comes back as ``success: true``, so a debug record without the
provider or the rescue provenance reads a degraded call as a healthy one — which is how a real outage
ran for 13 days unnoticed. The response surface is covered separately; this pins the diagnostic one.

Covers:
- search: a healthy call records ``provider`` and no rescue key
- search: a keyless rescue records ``provider`` + ``rescued_from``
- search: a managed fallback (managed Perplexity -> managed Firecrawl) records ``rescued_from``
- extract: a clean batch records ``provider`` and no rescue key
- extract: a rescued batch lifts the per-entry ``metadata.rescued_from``
"""

import json
from unittest.mock import patch

import pytest

from plugins.web import keyless_mcp
from tools import web_tools
from tools.web_result_cache import search_memo


@pytest.fixture(autouse=True)
def _isolate_web_caches():
    """The search memo is a process-global TTL cache, so a previous test's entry would otherwise
    satisfy the next one and hide the dispatch under test."""
    search_memo.clear()
    yield
    search_memo.clear()


class _Provider:
    """Minimal provider double; ``fail`` decides whether ``search`` reports an error."""

    def __init__(self, name="keenable", fail=False):
        self.name = name
        self.display_name = name.title()
        self._fail = fail

    def supports_search(self):
        return True

    def supports_extract(self):
        return True

    def is_available(self):
        return True

    def search(self, query, limit=5):
        if self._fail:
            return {"success": False, "error": "HTTP 500 upstream exploded"}
        return {"success": True, "data": {"web": [{"url": "https://ok.example", "title": "OK"}]}}


class _RecordingDebug:
    """Stands in for the module's DebugSession so a test reads the record it would have written."""

    def __init__(self):
        self.calls = []

    def log_call(self, call_name, call_data):
        self.calls.append((call_name, json.loads(json.dumps(call_data))))

    def save(self):
        pass


@pytest.fixture
def debug_record(monkeypatch):
    """Return the debug record of the most recent dispatch, captured instead of written to disk."""
    recorder = _RecordingDebug()
    monkeypatch.setattr(web_tools, "_debug", recorder)
    monkeypatch.setattr(web_tools, "_ensure_web_plugins_loaded", lambda: None)
    return lambda: recorder.calls[-1][1]


def _keyed_ring_env(monkeypatch, provider):
    """Pin one keyed ring backend as the configured search provider, rescue enabled."""
    monkeypatch.setattr(web_tools, "_load_web_config", lambda: {"backend": provider.name})
    monkeypatch.setattr(web_tools, "_get_search_backend", lambda: provider.name)
    monkeypatch.setattr("agent.web_search_registry.get_provider", lambda name: provider)
    monkeypatch.setattr("agent.web_search_registry.get_active_search_provider", lambda: provider)
    monkeypatch.setattr(
        "agent.web_search_provider.get_provider_env",
        lambda name: "kn-real" if name == "KEENABLE_API_KEY" else "",
    )
    monkeypatch.setattr("agent.web_search_registry._keyless_tier_enabled", lambda: True)


class TestSearchDebugAttribution:
    def test_healthy_search_records_the_provider(self, monkeypatch, debug_record):
        _keyed_ring_env(monkeypatch, _Provider())
        web_tools.web_search_tool("q", limit=2)
        record = debug_record()
        assert record["provider"] == "keenable"
        assert "rescued_from" not in record

    def test_rescued_search_records_provider_and_source(self, monkeypatch, debug_record):
        _keyed_ring_env(monkeypatch, _Provider(fail=True))
        with patch.object(
            keyless_mcp,
            "search_with_failover",
            return_value={"success": True, "data": {"web": [{"url": "https://ring.example"}]}},
        ):
            web_tools.web_search_tool("q", limit=2)
        record = debug_record()
        assert record["provider"] == "keenable"
        assert record["rescued_from"] == "keenable"

    def test_managed_fallback_records_the_serving_vendor(self, monkeypatch, debug_record):
        monkeypatch.setattr(web_tools, "_managed_web_search", lambda: True)
        monkeypatch.setattr(web_tools, "_is_tool_gateway_ready", lambda: True)
        monkeypatch.setattr(web_tools, "_load_web_config", lambda: {"backend": "perplexity"})
        monkeypatch.setattr(web_tools, "_get_search_backend", lambda: "perplexity")
        monkeypatch.setattr("agent.web_search_provider.get_provider_env", lambda name: "")
        monkeypatch.setattr(
            "agent.web_search_registry.get_provider",
            lambda name: (
                _Provider(name="perplexity", fail=True)
                if name == "perplexity"
                else _Provider(name="firecrawl")
            ),
        )
        web_tools.web_search_tool("q", limit=2)
        record = debug_record()
        assert record["provider"] == "perplexity"
        assert record["rescued_from"] == "managed_primary"


@pytest.fixture
def extract_env(monkeypatch):
    """Neutralize URL safety and pin the extract backend, so only attribution is under test."""

    async def _safe(url):
        return True

    monkeypatch.setattr(web_tools, "async_is_safe_url", _safe)
    monkeypatch.setattr(web_tools, "_get_extract_backend", lambda: "firecrawl")
    monkeypatch.setattr(
        web_tools, "_resolve_extract_provider", lambda backend: (_Provider("firecrawl"), None)
    )


class TestExtractDebugAttribution:
    @pytest.mark.asyncio
    async def test_clean_extract_records_the_provider(self, monkeypatch, debug_record, extract_env):
        async def _extract(provider, urls, fmt):
            return [{"url": u, "title": "T", "content": "body"} for u in urls]

        monkeypatch.setattr(web_tools, "_extract_safe_urls", _extract)
        await web_tools.web_extract_tool(["https://a.example"], char_limit=15000)
        record = debug_record()
        assert record["provider"] == "firecrawl"
        assert "rescued_from" not in record

    @pytest.mark.asyncio
    async def test_rescued_extract_lifts_the_entry_marker(self, monkeypatch, debug_record, extract_env):
        async def _extract(provider, urls, fmt):
            return [
                {
                    "url": u,
                    "title": "T",
                    "content": "body",
                    "metadata": {"rescued_from": "firecrawl", "backend_error": "all URLs failed"},
                }
                for u in urls
            ]

        monkeypatch.setattr(web_tools, "_extract_safe_urls", _extract)
        await web_tools.web_extract_tool(["https://b.example"], char_limit=15000)
        record = debug_record()
        assert record["provider"] == "firecrawl"
        assert record["rescued_from"] == "firecrawl"
