"""Authentication for RaceCraft Desktop.

Two ways to obtain a desktop JWT, both ending at the backend's real
OAuth 2.0 PKCE endpoints (backend/app/routers/desktop_auth.py):

1. login_with_password(email, password) — headless. Signs in via
   SuperTokens email/password to get an st-access-token, then drives
   the PKCE flow server-side (/api/auth/desktop/authorize →
   /api/auth/desktop/token). Used by --test / --headless mode and by
   automated E2E environments. Falls back to using the SuperTokens
   access token directly as the Bearer if the PKCE exchange fails
   (streaming endpoints accept both via verify_desktop_or_web_session).

2. login_with_browser() — interactive. Opens the system browser at
   /api/app_login with a PKCE challenge and catches the redirect on a
   localhost callback server. The production desktop flow.
"""

import asyncio
import base64
import hashlib
import secrets
import webbrowser
from typing import Optional

import httpx

from racecraft.models import AuthCredentials

CLIENT_ID = "racecraft-desktop"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


def _pkce_pair() -> tuple[str, str]:
    """Generate (code_verifier, code_challenge) per RFC 7636 S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class AuthenticationService:
    """Handle authentication against the RaceCraft backend."""

    def __init__(self, api_base_url: str):
        self.api_base_url = api_base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=15.0)
        self._credentials: Optional[AuthCredentials] = None
        self._bearer_token: Optional[str] = None
        self._refresh_token: Optional[str] = None

    # -- headless (test / E2E) path ---------------------------------------

    async def login_with_password(self, email: str, password: str,
                                  create_account: bool = True) -> Optional[AuthCredentials]:
        form = {"formFields": [
            {"id": "email", "value": email},
            {"id": "password", "value": password},
        ]}

        if create_account:
            # Idempotent: signup fails harmlessly if the user exists
            try:
                await self.client.post(f"{self.api_base_url}/api/auth/signup", json=form)
            except httpx.HTTPError:
                pass

        resp = await self.client.post(f"{self.api_base_url}/api/auth/signin", json=form)
        resp.raise_for_status()
        st_token = resp.headers.get("st-access-token")
        if not st_token:
            print("Auth: signin succeeded but no st-access-token header")
            return None

        # Ensure the SuperTokens user exists in the app DB
        await self.client.post(
            f"{self.api_base_url}/api/auth/user/sync",
            headers={"Authorization": f"Bearer {st_token}"},
        )

        # Exchange the web session for a desktop JWT via the PKCE endpoints
        try:
            creds = await self._pkce_from_session(st_token, email)
            if creds:
                return creds
        except httpx.HTTPError as e:
            print(f"Auth: PKCE exchange failed ({e}); using web session token")

        # Fallback: streaming endpoints also accept the SuperTokens token
        self._bearer_token = st_token
        self._credentials = AuthCredentials(
            user_id=email, api_key=st_token, license_tier="dev",
        )
        return self._credentials

    async def _pkce_from_session(self, st_token: str, email: str) -> Optional[AuthCredentials]:
        """Authenticated session → auth code → desktop JWT (real PKCE path)."""
        verifier, challenge = _pkce_pair()

        resp = await self.client.post(
            f"{self.api_base_url}/api/auth/desktop/authorize",
            headers={"Authorization": f"Bearer {st_token}"},
            json={
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        resp.raise_for_status()
        code = resp.json()["code"]
        return await self._exchange_code(code, verifier)

    # -- interactive (production) path -------------------------------------

    async def login_with_browser(self, timeout_s: int = 300) -> Optional[AuthCredentials]:
        """Open the system browser for login; catch the localhost redirect."""
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        code_future: asyncio.Future = asyncio.get_running_loop().create_future()

        async def handle_client(reader, writer):
            try:
                request_line = (await reader.readline()).decode()
                path = request_line.split(" ")[1] if " " in request_line else ""
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(path).query)
                body = b"<html><body>RaceCraft login complete. You can close this window.</body></html>"
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                             b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
                await writer.drain()
                if not code_future.done() and qs.get("state", [""])[0] == state and "code" in qs:
                    code_future.set_result(qs["code"][0])
            finally:
                writer.close()

        server = await asyncio.start_server(handle_client, "127.0.0.1", REDIRECT_PORT)
        try:
            auth_url = (
                f"{self.api_base_url}/api/app_login?response_type=code"
                f"&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
                f"&code_challenge={challenge}&code_challenge_method=S256&state={state}"
            )
            webbrowser.open(auth_url)
            code = await asyncio.wait_for(code_future, timeout=timeout_s)
        except asyncio.TimeoutError:
            print("Auth: browser login timed out")
            return None
        finally:
            server.close()
            await server.wait_closed()

        return await self._exchange_code(code, verifier)

    # -- shared -------------------------------------------------------------

    async def _exchange_code(self, code: str, verifier: str) -> Optional[AuthCredentials]:
        resp = await self.client.post(
            f"{self.api_base_url}/api/auth/desktop/token",
            json={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._bearer_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        self._credentials = AuthCredentials(
            user_id=str(data.get("user_id", "")),
            api_key=data["access_token"],
            license_tier=data.get("username") or data.get("user_email", ""),
        )
        print(f"Auth: desktop token issued for {data.get('user_email')}")
        return self._credentials

    async def refresh(self) -> bool:
        """Refresh the desktop access token (refresh_token grant)."""
        if not self._refresh_token:
            return False
        resp = await self.client.post(
            f"{self.api_base_url}/api/auth/desktop/token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": CLIENT_ID,
            },
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        self._bearer_token = data["access_token"]
        # The platform rotates refresh tokens (loop 3, S4): each refresh
        # revokes the presented token and returns its replacement. Keep
        # the old one only if the server didn't send a new one.
        self._refresh_token = data.get("refresh_token") or self._refresh_token
        return True

    @property
    def bearer_token(self) -> Optional[str]:
        return self._bearer_token

    @property
    def user_id(self) -> Optional[str]:
        return self._credentials.user_id if self._credentials else None

    @property
    def is_authenticated(self) -> bool:
        return self._bearer_token is not None
