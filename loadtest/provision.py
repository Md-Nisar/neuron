# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Create the Keycloak test users the load scenarios sign in as: `python -m loadtest.provision`."""

from __future__ import annotations

import os

from loadtest.identity import provision_users

if __name__ == "__main__":
    count = int(os.environ.get("LOAD_USERS", "50"))
    provision_users(count)
    print(f"provisioned {count} load users")
