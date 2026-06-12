"""Refresh-token rotation handling (platform loop 3, S4).

The platform's /api/auth/desktop/token refresh grant now ROTATES: each
successful refresh revokes the presented refresh token and returns a new
one. The client must adopt the replacement — keeping the old token means
the NEXT refresh fails with invalid_grant and the user is forced back
through the browser login.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from racecraft.auth import AuthenticationService


def _service_with_response(status_code=200, payload=None):
    svc = AuthenticationService("http://api.test")
    svc._bearer_token = "old-access"
    svc._refresh_token = "old-refresh"
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload or {}
    svc.client = MagicMock()
    svc.client.post = AsyncMock(return_value=resp)
    return svc


def test_refresh_adopts_rotated_refresh_token():
    svc = _service_with_response(200, {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
    })
    assert asyncio.run(svc.refresh()) is True
    assert svc._bearer_token == "new-access"
    assert svc._refresh_token == "new-refresh"


def test_refresh_keeps_old_token_when_server_sends_none():
    # Defensive: a server that doesn't rotate (or omits the field) must
    # not wipe the stored token.
    svc = _service_with_response(200, {"access_token": "new-access"})
    assert asyncio.run(svc.refresh()) is True
    assert svc._refresh_token == "old-refresh"


def test_failed_refresh_changes_nothing():
    svc = _service_with_response(400, {"detail": "invalid_grant"})
    assert asyncio.run(svc.refresh()) is False
    assert svc._bearer_token == "old-access"
    assert svc._refresh_token == "old-refresh"


def test_refresh_without_stored_token_is_a_noop():
    svc = AuthenticationService("http://api.test")
    svc.client = MagicMock()
    svc.client.post = AsyncMock()
    assert asyncio.run(svc.refresh()) is False
    svc.client.post.assert_not_called()
