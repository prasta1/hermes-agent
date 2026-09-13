from plugins.platforms.discord.adapter import DiscordAdapter


BRIEF = """Cronjob Response: Morning Brief
(job_id: morning_brief)
--------------------

\U0001f324️ 68F and clear

**Work Priorities**
- Ship the embed PR

**Issues & Blockers**
- gateway drift detected
"""


def test_parse_brief_content_splits_weather_fields_and_severity():
    """A wrapped cron brief becomes weather + embed fields, colored by severity."""
    parsed = DiscordAdapter._parse_brief_content(BRIEF)

    assert parsed is not None
    assert parsed["title"] == "Morning Brief"
    assert parsed["weather"] == "\U0001f324️ 68F and clear"
    assert [name for name, _value, _inline in parsed["fields"]] == [
        "Work Priorities",
        "Issues & Blockers",
    ]
    # 'drift' is a warning signal, not critical -> amber, not red.
    assert parsed["color"] == 0xE0A343


def test_parse_brief_content_is_callable_unbound():
    """Regression: the cron standalone REST path has no adapter instance.

    ``_standalone_send`` calls ``DiscordAdapter._parse_brief_content(message)`` with no
    ``self``. While this was an instance method that call raised TypeError, so every
    cron-delivered brief fell back to plain text (or blew up) instead of rendering.
    """
    assert DiscordAdapter._parse_brief_content(BRIEF) is not None


def test_parse_brief_content_rejects_non_brief():
    """Plain messages must not be coerced into an embed."""
    assert DiscordAdapter._parse_brief_content("just a normal message") is None
