# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Create the Keycloak test users the load scenarios sign in as: `python -m loadtest.provision`.

LOAD_USERS chat users from `load-0000`; LOAD_KNOWLEDGE_USERS knowledge users from `load-0900`.
"""

from __future__ import annotations

import os

from loadtest.identity import KNOWLEDGE_FIRST_USER, provision_users

if __name__ == "__main__":
    count = int(os.environ.get("LOAD_USERS", "50"))
    provision_users(count)
    knowledge = int(os.environ.get("LOAD_KNOWLEDGE_USERS", "0"))
    provision_users(knowledge, first=KNOWLEDGE_FIRST_USER)
    print(f"provisioned {count} load users and {knowledge} knowledge users")
