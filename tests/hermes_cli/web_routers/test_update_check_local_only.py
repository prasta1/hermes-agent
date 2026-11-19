"""A branch the official origin does not advertise is not an unreachable server.

Regression for #135182 (the earlier attempt at this, closed when the updates overlay was
rewritten upstream): source_check answers `behind: null` with `error="branch-local-only",
localOnly=True` for a checkout pinned to a branch that exists nowhere upstream. The endpoint
discarded that verdict and collapsed every null into "Couldn't reach the update source", and the
Desktop's `can_apply && behind === null` gate turned it into `check-failed` — so the update panel
showed a permanent connectivity error over a checkout that is simply carrying its own commits.
"""

from __future__ import annotations

import pytest

FORK_ONLY_STATUS = {
    "supported": True,
    "behind": None,
    "commits": [],
    "currentSha": "a" * 40,
    "currentBranch": "local",
    "dirty": False,
    "branch": "local",
    "error": "branch-local-only",
    "localOnly": True,
    "message": (
        "Branch 'local' is gone from the remote but has commits that are not in main;"
        " keeping it instead of switching to main."
    ),
}


@pytest.fixture
def client(_isolate_hermes_home):
    """A dashboard TestClient carrying the session header the routes expect."""
    TestClient = pytest.importorskip("starlette.testclient").TestClient

    from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    test_client = TestClient(app)
    test_client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return test_client


@pytest.fixture
def git_install(monkeypatch):
    """Make the endpoint take the applyable git path instead of the managed/apt refusals."""
    import hermes_cli.config as _cfg_mod
    import hermes_cli.web_server_files as _web_server_files

    monkeypatch.setattr(_web_server_files, "_dashboard_local_update_managed_externally", lambda: False)
    monkeypatch.setattr(_cfg_mod, "detect_install_method", lambda _root: "git")


def test_a_fork_only_branch_is_not_reported_as_a_failed_check(client, git_install, monkeypatch):
    """The source check's own verdict and reason survive to the payload."""
    from hermes_cli import source_check

    monkeypatch.setattr(source_check, "check_for_updates", lambda **_kwargs: dict(FORK_ONLY_STATUS))

    data = client.get("/api/hermes/update/check").json()

    assert data["can_apply"] is True
    assert data["behind"] is None
    assert data["localOnly"] is True
    assert data["currentBranch"] == "local"
    assert data["message"] == FORK_ONLY_STATUS["message"]


def test_a_genuine_probe_failure_keeps_the_outage_copy(client, git_install, monkeypatch):
    """A real reachability failure is still an outage, and is not flagged local-only."""
    from hermes_cli import source_check

    monkeypatch.setattr(
        source_check,
        "check_for_updates",
        lambda **_kwargs: {
            "supported": True,
            "behind": None,
            "commits": [],
            "error": "fetch-failed",
            "message": "Could not resolve the remote branch tip.",
        },
    )

    data = client.get("/api/hermes/update/check").json()

    assert data["localOnly"] is False
    assert data["message"] == "Couldn't reach the update source — try again later."
