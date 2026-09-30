"""Vendor-minted tool-call ids must not wedge a session on replay.

Some OpenAI-compatible gateways mint ``chatcmpl-tool-<hex>`` ids and then 502 the replay of any
assistant turn holding two or more of them ("JSON error injected into SSE stream"). The ids are
persisted, so every later request re-sends them and fails identically — retries and provider
switches cannot recover. Assert the RELATIONSHIP between the turn's ids and the wire shape, never
a literal id value (ids feed prompt-cache prefixes and are deterministic by contract).
"""

import logging

from agent.message_sanitization import (
    _VENDOR_TOOL_CALL_ID_PREFIXES,
    normalize_vendor_tool_call_ids,
)

VENDOR = _VENDOR_TOOL_CALL_ID_PREFIXES[0]


def _tc(call_id, *, response_item_id=None):
    ident = f"{call_id}|{response_item_id}" if response_item_id else call_id
    entry = {"id": ident, "type": "function",
             "function": {"name": "read_file", "arguments": '{"path":"/x"}'}}
    if response_item_id:
        entry["call_id"] = ident
    return entry


def _ids(calls):
    return [tc["id"] for tc in calls]


def test_parallel_vendor_ids_are_rekeyed():
    calls = [_tc(VENDOR + "a" * 32), _tc(VENDOR + "b" * 32)]
    normalize_vendor_tool_call_ids(calls)
    assert all(cid.startswith("call_") for cid in _ids(calls)), _ids(calls)
    assert len(set(_ids(calls))) == 2, "renaming must keep ids distinct"


def test_rewrite_is_deterministic():
    """Same input twice yields the same ids, so the cache prefix stays stable."""
    first = [_tc(VENDOR + "a" * 32), _tc(VENDOR + "b" * 32)]
    second = [_tc(VENDOR + "a" * 32), _tc(VENDOR + "b" * 32)]
    normalize_vendor_tool_call_ids(first)
    normalize_vendor_tool_call_ids(second)
    assert _ids(first) == _ids(second)


def test_single_vendor_call_is_byte_identical():
    """One provider id replays fine — leave it alone so the cached prefix is untouched."""
    call_id = VENDOR + "a" * 32
    calls = [_tc(call_id)]
    normalize_vendor_tool_call_ids(calls)
    assert _ids(calls) == [call_id]


def test_hermes_shaped_batch_untouched():
    calls = [_tc("call_00_aaaaaaaaaaaaaaaaaaaaaa"), _tc("call_01_bbbbbbbbbbbbbbbbbbbbbb")]
    normalize_vendor_tool_call_ids(calls)
    assert _ids(calls) == ["call_00_aaaaaaaaaaaaaaaaaaaaaa", "call_01_bbbbbbbbbbbbbbbbbbbbbb"]


def test_mixed_batch_untouched():
    """Only an all-vendor batch trips the endpoint; a mixed one is accepted, so leave it."""
    vendor = VENDOR + "a" * 32
    calls = [_tc(vendor), _tc("call_01_bbbbbbbbbbbbbbbbbbbbbb")]
    normalize_vendor_tool_call_ids(calls)
    assert _ids(calls) == [vendor, "call_01_bbbbbbbbbbbbbbbbbbbbbb"]


def test_composite_response_item_half_survives():
    """A Responses-bridge ``call_id|item_id`` keeps its item half — dropping it breaks pairing."""
    calls = [_tc(VENDOR + "a" * 32, response_item_id="fc_9"),
             _tc(VENDOR + "b" * 32, response_item_id="fc_8")]
    normalize_vendor_tool_call_ids(calls)
    assert _ids(calls)[0].endswith("|fc_9"), _ids(calls)
    assert _ids(calls)[1].endswith("|fc_8"), _ids(calls)


def test_rename_is_logged(caplog):
    """A silent rewrite would be unexplainable in the field; one WARNING names the cause."""
    calls = [_tc(VENDOR + "a" * 32), _tc(VENDOR + "b" * 32)]
    with caplog.at_level(logging.WARNING, logger="agent.message_sanitization"):
        normalize_vendor_tool_call_ids(calls)
    assert any(VENDOR.rstrip("-") in r.getMessage() or "vendor prefix" in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in caplog.records]


def test_empty_and_single_inputs_are_noops():
    assert normalize_vendor_tool_call_ids([]) == []
    only = [_tc(VENDOR + "a" * 32)]
    assert normalize_vendor_tool_call_ids(only) is not None
