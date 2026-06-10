"""Authentication service for RaceCraft Desktop"""

import httpx
from typing import Optional
import keyring
import uuid
from racecraft.models import AuthCredentials


class AuthenticationService:
    """Handle authentication with remote server"""

    def __init__(self, api_base_url: str):
        self.api_base_url = api_base_url
        self.client = httpx.AsyncClient(timeout=10.0)
        self._credentials: Optional[AuthCredentials] = None

    async def validate_on_startup(self) -> Optional[AuthCredentials]:
        """
        Called on app startup to validate stored credentials.
        If no credentials exist, prompt user to login.
        """
        # Try to load stored credentials
        stored_key = keyring.get_password("racecraft", "api_key")

        if not stored_key:
            # First run - need to authenticate
            return await self._initial_authentication()

        # Validate existing credentials
        try:
            response = await self.client.get(
                f"{self.api_base_url}/api/auth/validate",
                headers={"X-API-Key": stored_key}
            )

            if response.status_code == 200:
                data = response.json()
                self._credentials = AuthCredentials(
                    user_id=data['user_id'],
                    api_key=stored_key,
                    license_tier=data['license_tier']
                )
                return self._credentials
            else:
                # Invalid credentials - need to re-authenticate
                keyring.delete_password("racecraft", "api_key")
                return await self._initial_authentication()

        except Exception as e:
            print(f"Validation error: {e}")
            return None

    async def _initial_authentication(self) -> Optional[AuthCredentials]:
        """
        First-time authentication flow.
        Generate device_id, request API key from server.
        """
        device_id = self._get_or_create_device_id()

        try:
            # Request authentication
            response = await self.client.post(
                f"{self.api_base_url}/api/auth/device/register",
                json={"device_id": device_id}
            )

            if response.status_code == 200:
                data = response.json()

                # Store API key securely
                keyring.set_password("racecraft", "api_key", data['api_key'])

                self._credentials = AuthCredentials(
                    user_id=data['user_id'],
                    api_key=data['api_key'],
                    license_tier=data.get('license_tier', 'free')
                )

                return self._credentials
            elif response.status_code == 403:
                # Device/user not authorized
                print("Authorization required. Visit dashboard to enable this device.")
                return None
            else:
                print(f"Authentication failed: {response.status_code}")
                return None

        except Exception as e:
            print(f"Authentication error: {e}")
            return None

    def _get_or_create_device_id(self) -> str:
        """Get or create unique device ID"""
        device_id = keyring.get_password("racecraft", "device_id")

        if not device_id:
            device_id = str(uuid.uuid4())
            keyring.set_password("racecraft", "device_id", device_id)

        return device_id

    @property
    def user_id(self) -> Optional[str]:
        return self._credentials.user_id if self._credentials else None

    @property
    def is_authenticated(self) -> bool:
        return self._credentials is not None
