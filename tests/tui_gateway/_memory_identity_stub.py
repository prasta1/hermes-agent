"""Minimal stand-in for a lazily-initialized memory provider.

Several tests assert that a workspace move does NOT rebind the agent's memory
identity. They used to reach for Honcho purely as an observable carrier of
``_session_key`` / ``_lazy_init_kwargs``; Honcho was removed from this install
(2026-10-02) and no remaining bundled provider exposes those internals.

The behavior under test belongs to the agent/gateway, not to any provider, so a
local stub is the honest fixture. It implements the provider protocol that
``MemoryManager`` and ``agent_init`` actually call — derived from the (now
deleted) Honcho implementation and cross-checked against
``plugins/memory/holographic`` — and records the identity it is handed.

``load_memory_provider`` is monkeypatched to return it, so no real provider is
imported, no network call is made, and no credential is touched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class StubMemoryProvider:
    """A provider shell that records its identity and does nothing else."""

    def __init__(self, *, cwd: str | None = None, session_id: str | None = None, **kwargs: Any):
        # Identity is resolved from whichever cwd is available: one passed at
        # construction, or one supplied later to initialize(). agent_init only
        # includes ``cwd`` when ``agent.session_cwd`` is set
        # (agent/agent_init.py:1301), so both paths are real.
        self._init_cwd = str(cwd) if cwd is not None else None
        self._session_key = Path(self._init_cwd).name if self._init_cwd else None
        self._lazy_init_kwargs: dict[str, Any] | None = (
            {"cwd": self._init_cwd, **kwargs} if self._init_cwd else None
        )
        self._initialized_with: dict[str, Any] = {}

    # --- identity ----------------------------------------------------------
    def _adopt_cwd(self, cwd: Any) -> None:
        """Take the identity cwd on first availability, then hold it forever.

        A workspace move must never re-derive identity, so this is guarded by
        ``_session_key is None`` rather than overwriting.
        """
        if self._session_key is None and cwd:
            self._init_cwd = str(cwd)
            self._session_key = Path(self._init_cwd).name
            self._lazy_init_kwargs = {"cwd": self._init_cwd}

    # --- provider protocol -------------------------------------------------
    @property
    def name(self) -> str:
        return "stub"

    @property
    def backup_paths(self) -> list:
        return []

    def is_available(self) -> bool:
        return True

    def get_tool_schemas(self) -> list:
        return []

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs: Any) -> str:
        return ""

    def initialize(self, session_id: str | None = None, **kwargs: Any) -> None:
        self._initialized_with = {"session_id": session_id, **kwargs}
        self._adopt_cwd(kwargs.get("cwd"))

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        return ""

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        return None

    def system_prompt_block(self) -> str:
        return ""

    def identity_signature(self) -> dict:
        return {}

    def on_turn_start(self, turn_number: int, message: str, **kwargs: Any) -> None:
        return None

    def on_session_switch(self, new_session_id: str, **kwargs: Any) -> None:
        return None

    def on_memory_write(self, *a: Any, **k: Any) -> None:
        return None

    def on_session_end(self, messages: list) -> None:
        return None

    def shutdown(self) -> None:
        return None

    # Honcho exposed this name; keep the alias so either close path works.
    close = shutdown