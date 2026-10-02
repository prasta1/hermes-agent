"""Tests: skills.manage search path (tui_gateway/methods_tools.py::_skills_search).

The RPC returns `results` built from the `SkillMeta` objects `unified_search`
yields. `SkillMeta` is a plain dataclass with a `description` FIELD — it has no
`describe()` method, so the handler must read the attribute. The i18n language-pack
commit (#126296) rewrote `r.description` to `r.describe()` here, which made every
`/skills search <query>` from the TUI/Desktop die with
`AttributeError: 'SkillMeta' object has no attribute 'describe'`.
"""

import tui_gateway.server as srv
from tools.skills_hub_models import SkillMeta


def _search(params):
    return srv._methods["skills.manage"](1, params)


def _stub_unified_search(monkeypatch, metas):
    """Patch unified_search at the module the RPC resolves it from."""
    import tools.skills_hub_search as search_mod

    def fake_unified_search(query, router, source_filter="all", limit=10):
        return list(metas)

    monkeypatch.setattr(search_mod, "unified_search", fake_unified_search)
    monkeypatch.setattr(search_mod, "create_source_router", lambda auth: object())


def test_search_returns_name_and_description(monkeypatch):
    """Each result carries the meta's name + description, read off the dataclass."""
    _stub_unified_search(
        monkeypatch,
        [SkillMeta(name="home-assistant", description="Control HA devices",
                   source="official", identifier="official/home-assistant",
                   trust_level="builtin")],
    )

    out = _search({"action": "search", "query": "home assistant"})

    assert "error" not in out
    assert out["result"]["results"] == [
        {"name": "home-assistant", "description": "Control HA devices"}
    ]


def test_search_result_shape_matches_skillmeta_fields(monkeypatch):
    """The handler reads real SkillMeta fields, not a method the type doesn't have.

    A plain attribute access can only work against the dataclass fields; anything
    the i18n commit reached for is absent, so this fails loudly if it returns.
    """
    metas = [
        SkillMeta(name="a", description="first", source="official",
                  identifier="official/a", trust_level="builtin"),
        SkillMeta(name="b", description="second", source="github",
                  identifier="org/b", trust_level="community"),
    ]
    _stub_unified_search(monkeypatch, metas)

    out = _search({"action": "search", "query": "a b"})

    for meta, row in zip(metas, out["result"]["results"]):
        assert row["name"] == meta.name
        assert row["description"] == meta.description
