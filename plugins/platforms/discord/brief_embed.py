"""Render Hermes infra cron briefs as native Discord embeds (local patch).

This lives in its own module on purpose: ``adapter.py`` is a 7000-line file upstream churns
constantly, and a 90-line block inserted there conflicted on nearly every ``hermes update``.
A new file never conflicts, so the adapter carries only a few hook lines that call in here.

Two entry points, one per delivery path:

- ``rest_payload`` — the cron standalone REST sender (no gateway running) posts this JSON body.
- ``send`` — the live gateway adapter sends a ``discord.Embed`` through the channel object.

Both return ``None`` for content that is not a wrapped cron brief, and the caller falls through
to its normal plain-text path.
"""
import re
from typing import Optional

from gateway.platforms.base import SendResult

# Cron wraps every job response as "Cronjob Response: <title>\n(job_id: <id>)\n----\n\n<body>".
_WRAPPED = re.compile(r'Cronjob Response:\s*[^\n]+\n\(job_id:\s*\w+\)\n[-]+\n\n(.*)', re.DOTALL)
_TITLE = re.compile(r'Cronjob Response:\s*(.+)')
_WEATHER = re.compile(r'(🌤️|☀️|🌙)\s*(.+?)(?:\n\n|\n\n\*\*)')
_SECTION_HEADER = re.compile(r'^\*\*(.+?)\*\*$')
_FOOTER = re.compile(r'(next brief|next run|next [0-9:]+|[0-9]+ other services.*\d+h\b)')
_CRITICAL = re.compile(r'(DOWN|🔴|Critical|critical)')
_ISSUES = re.compile(r'(down|DOWN|⚠️|drift|conflict|Drift|Conflict)')
_RECOVERY = re.compile(r'(🟢|recovered|back)')

_RED, _GREEN, _AMBER, _BLURPLE = 0xE04343, 0x4F9E5F, 0xE0A343, 0x5865F2
_FIELD_VALUE_LIMIT = 1024  # Discord's per-field cap


def parse_brief_content(content: str) -> Optional[dict]:
    """Split a wrapped cron brief into embed parts.

    Returns ``{'weather', 'title', 'fields', 'color', 'footer'}`` — ``fields`` is a list of
    ``(name, value, inline)`` tuples, one per ``**Section**`` header — or ``None`` when
    ``content`` is not a cron-wrapped brief.
    """
    wrapped = _WRAPPED.match(content)
    if not wrapped:
        return None
    body = re.split(r'\n\nTo stop or manage this job', wrapped.group(1))[0].strip()
    if '## Response' in body:
        body = body.split('## Response\n', 1)[-1].strip()
    elif '## Prompt' in body:
        body = body.split('## Prompt\n', 1)[0].strip()

    weather = None
    weather_match = _WEATHER.search(body)
    if weather_match:
        weather = f"{weather_match.group(1)} {weather_match.group(2).strip()}"
        body = body[:weather_match.start()] + body[weather_match.end():]

    # Severity drives the embed's side color: red beats green beats amber beats default.
    has_issues = bool(_ISSUES.search(body))
    if _CRITICAL.search(body):
        color = _RED
    elif _RECOVERY.search(body) and not has_issues:
        color = _GREEN
    elif has_issues:
        color = _AMBER
    else:
        color = _BLURPLE

    fields = []
    section, lines = None, []
    for line in body.split('\n'):
        stripped = line.strip()
        header = _SECTION_HEADER.match(stripped)
        if header and not stripped.startswith('-'):
            if section and lines:
                fields.append((section, '\n'.join(lines), False))
            section, lines = header.group(1), []
        elif stripped:
            lines.append(stripped)
    if section and lines:
        fields.append((section, '\n'.join(lines), False))

    title_match = _TITLE.match(content)
    footer_match = _FOOTER.search(content)
    return {
        'weather': weather,
        'title': title_match.group(1).strip() if title_match else None,
        'fields': fields,
        'color': color,
        'footer': footer_match.group(1).strip() if footer_match else None,
    }


def rest_payload(content: str, job_id: Optional[str] = None) -> Optional[dict]:
    """Build the Discord REST message body for a brief: weather as ``content``, the rest as one embed.

    ``job_id`` is the footer fallback when the brief names no next run. Returns ``None`` when
    ``content`` is not a brief or has no sections, so the caller posts it as plain text.
    """
    parsed = parse_brief_content(content)
    if not parsed or not parsed['fields']:
        return None
    embed = {
        'title': parsed['title'] or "Hermes Brief",
        'color': parsed['color'],
        'fields': [
            {'name': name,
             'value': value if len(value) <= _FIELD_VALUE_LIMIT else value[:_FIELD_VALUE_LIMIT - 3] + "...",
             'inline': inline}
            for name, value, inline in parsed['fields']
        ],
    }
    footer = parsed['footer'] or (f"job_id: {job_id}" if job_id else None)
    if footer:
        embed['footer'] = {'text': footer}
    payload = {'embeds': [embed]}
    if parsed['weather']:
        payload['content'] = parsed['weather']
    return payload


async def send(adapter, channel, content: str, metadata: Optional[dict], reply_to) -> Optional[SendResult]:
    """Live-adapter path: send ``content`` as a native embed through ``channel``.

    ``adapter`` supplies the reply anchor via its ``_reply_reference_for_send``. Returns the
    ``SendResult`` on success, or ``None`` when ``content`` is not a brief (nothing is sent and
    the adapter continues with its normal plain-text path).
    """
    import discord  # optional dependency; only importable where the Discord platform is installed

    payload = rest_payload(content, (metadata or {}).get("job_id"))
    if payload is None:
        return None
    msg = await channel.send(
        content=payload.get('content'),
        embed=discord.Embed.from_dict(payload['embeds'][0]),
        reference=adapter._reply_reference_for_send(reply_to, channel),
    )
    return SendResult(success=True, message_id=str(msg.id), raw_response={"message_ids": [str(msg.id)]})
