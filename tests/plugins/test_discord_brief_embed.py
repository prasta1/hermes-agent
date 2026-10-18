"""Hermes infra briefs rendered as native Discord embeds (local patch, plugins/platforms/discord/brief_embed.py)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.discord import brief_embed
from plugins.platforms.discord.adapter import DiscordAdapter


WEATHER = "\U0001f324️ 68F and clear"

BRIEF = f"""Cronjob Response: Morning Brief
(job_id: morning_brief)
--------------------

{WEATHER}

**Work Priorities**
- Ship the embed PR

**Issues & Blockers**
- gateway drift detected
"""


def test_parse_brief_content_splits_weather_fields_and_severity():
    """A wrapped cron brief becomes weather + embed fields, colored by severity."""
    parsed = brief_embed.parse_brief_content(BRIEF)

    assert parsed is not None
    assert parsed["title"] == "Morning Brief"
    assert parsed["weather"] == WEATHER
    assert [name for name, _value, _inline in parsed["fields"]] == [
        "Work Priorities",
        "Issues & Blockers",
    ]
    # 'drift' is a warning signal, not critical -> amber, not red.
    assert parsed["color"] == 0xE0A343


def test_parse_brief_content_rejects_non_brief():
    """Plain messages must not be coerced into an embed."""
    assert brief_embed.parse_brief_content("just a normal message") is None


def test_rest_payload_builds_discord_message_body():
    """The cron standalone REST path posts weather as content and the rest as one embed."""
    payload = brief_embed.rest_payload(BRIEF)

    assert payload["content"] == WEATHER
    (embed,) = payload["embeds"]
    assert embed["title"] == "Morning Brief"
    assert embed["color"] == 0xE0A343
    assert [f["name"] for f in embed["fields"]] == ["Work Priorities", "Issues & Blockers"]
    assert embed["fields"][0]["value"] == "- Ship the embed PR"


def test_rest_payload_is_none_for_non_brief():
    """The REST sender falls back to a plain {"content": ...} body for ordinary messages."""
    assert brief_embed.rest_payload("just a normal message") is None


def test_send_delivers_embed_through_the_live_channel():
    """The live adapter path sends weather as content plus a discord.Embed in one message."""
    discord = pytest.importorskip("discord")
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="token"))
    channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=42)))

    result = asyncio.run(brief_embed.send(adapter, channel, BRIEF, {"brief_embed": True}, reply_to=None))

    assert result.success is True
    assert result.message_id == "42"
    kwargs = channel.send.await_args.kwargs
    assert kwargs["content"] == WEATHER
    assert isinstance(kwargs["embed"], discord.Embed)
    assert kwargs["embed"].title == "Morning Brief"
    assert [f.name for f in kwargs["embed"].fields] == ["Work Priorities", "Issues & Blockers"]


def test_send_returns_none_for_non_brief_so_the_adapter_falls_through():
    """Non-brief content is not the embed path's job: return None and send nothing."""
    discord = pytest.importorskip("discord")
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="token"))
    channel = SimpleNamespace(send=AsyncMock())

    assert asyncio.run(brief_embed.send(adapter, channel, "just a normal message", {"brief_embed": True}, reply_to=None)) is None
    channel.send.assert_not_awaited()
