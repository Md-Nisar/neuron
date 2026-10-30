# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Print the API settings for the development Keycloak (ADR 0010, decision 5).

Development only. Start the identity provider with
`docker compose --profile keycloak up keycloak`, then:

    make dev-keycloak >> .env

The realm (`deploy/keycloak/neuron-realm.json`) has two throwaway users: `alice` (role
`neuron-user`) and `bob` (role `neuron-reader`). Use this *or* `make dev-auth`, not both.
"""

from __future__ import annotations

import json
import secrets

from neuron_agent.security.authorization import DEV_PERMISSIONS

KEYCLOAK_URL = "http://localhost:8180"
REALM = "neuron"
AUDIENCE = "neuron-api"
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "neuron-user": sorted(DEV_PERMISSIONS),
    "neuron-reader": ["threads:read"],
}


def env_block() -> str:
    """The `.env` lines that make a development API trust the development Keycloak."""
    issuer = f"{KEYCLOAK_URL}/realms/{REALM}"
    return "\n".join(
        [
            "",
            "# Development Keycloak (scripts/dev_keycloak.py). Development only.",
            "APP_AUTH_MODE=jwt",
            f"APP_AUTH_ISSUER={issuer}",
            f"APP_AUTH_AUDIENCE={AUDIENCE}",
            f"APP_AUTH_JWKS_URL={issuer}/protocol/openid-connect/certs",
            'APP_AUTH_ALGORITHMS=["RS256"]',
            f"APP_AUTH_ROLE_PERMISSIONS={json.dumps(ROLE_PERMISSIONS, separators=(',', ':'))}",
            f"APP_IDENTITY_HASH_KEY={secrets.token_urlsafe(32)}",
            "",
        ]
    )


if __name__ == "__main__":
    print(env_block())
