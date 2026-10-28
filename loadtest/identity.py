# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Keycloak users and tokens for the reference stack: one test user per virtual user.

Local use only: the admin and user passwords are the throwaway ones of the development realm.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

KEYCLOAK = "http://127.0.0.1:8180"
REALM = "neuron"
ADMIN_PASSWORD = "admin-local-only"  # noqa: S105  # nosec B105
ROLE = "neuron-user"
CLIENT_ID = "neuron-dev-test"
_RENEW_BEFORE_SECONDS = 30.0


def username(index: int) -> str:
    return f"load-{index:04d}"


def password(name: str) -> str:
    return f"dev-only-{name}"


def provision_users(count: int, base_url: str = KEYCLOAK) -> None:
    """Create `load-0000` onwards with the `neuron-user` role; existing users are kept."""
    session = requests.Session()
    session.trust_env = False
    token = session.post(
        f"{base_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": ADMIN_PASSWORD,
        },
        timeout=30,
    ).json()["access_token"]
    session.headers["Authorization"] = f"Bearer {token}"
    admin = f"{base_url}/admin/realms/{REALM}"
    role = session.get(f"{admin}/roles/{ROLE}", timeout=30).json()
    for index in range(count):
        name = username(index)
        created = session.post(
            f"{admin}/users",
            json={
                "username": name,
                "enabled": True,
                "email": f"{name}@example.test",
                "emailVerified": True,
                "firstName": "Load",
                "lastName": name,
                "credentials": [{"type": "password", "value": password(name), "temporary": False}],
            },
            timeout=30,
        )
        if created.status_code == 409:
            continue
        created.raise_for_status()
        user_id = created.headers["Location"].rsplit("/", 1)[1]
        session.post(
            f"{admin}/users/{user_id}/role-mappings/realm", json=[role], timeout=30
        ).raise_for_status()


@dataclass
class TokenSource:
    """An access token for one user, renewed shortly before it expires."""

    name: str
    base_url: str = KEYCLOAK
    _token: str = ""
    _expires: float = 0.0

    def get(self) -> str:
        if time.monotonic() >= self._expires - _RENEW_BEFORE_SECONDS:
            response = requests.post(
                f"{self.base_url}/realms/{REALM}/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": CLIENT_ID,
                    "username": self.name,
                    "password": password(self.name),
                },
                timeout=30,
                proxies={"http": "", "https": ""},
            )
            response.raise_for_status()
            body = response.json()
            self._token = body["access_token"]
            self._expires = time.monotonic() + float(body["expires_in"])
        return self._token
