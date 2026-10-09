"""LangGraph Agent Server authentication and owner-scoped authorization."""

from __future__ import annotations

from typing import Any

from langgraph_sdk import Auth

from neuron_agent.config.settings import get_settings
from neuron_agent.errors.base import AuthenticationError, AuthenticationUnavailableError
from neuron_agent.security.auth import (
    Principal,
    get_shared_token_verifier,
    principal_owner_key,
)
from neuron_agent.security.authorization import DEV_PERMISSIONS

settings = get_settings()
token_verifier = get_shared_token_verifier(settings)
auth = Auth()


def _http_error(status_code: int, detail: str) -> Auth.exceptions.HTTPException:
    return Auth.exceptions.HTTPException(status_code=status_code, detail=detail)


def _permissions(user: Any) -> frozenset[str]:
    permissions = getattr(user, "permissions", ())
    return (
        frozenset(permissions)
        if isinstance(permissions, (list, tuple, set, frozenset))
        else frozenset()
    )


def _require(ctx: Auth.types.AuthContext, permission: str) -> str:
    if permission not in _permissions(ctx.user):
        raise _http_error(403, "Forbidden")
    return ctx.user.identity


def _stamp_owner(ctx: Auth.types.AuthContext, value: Any, permission: str) -> dict[str, str]:
    owner = _require(ctx, permission)
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        value["metadata"] = metadata
    metadata["owner"] = owner
    return {"owner": owner}


def _owner_filter(ctx: Auth.types.AuthContext, permission: str) -> dict[str, str]:
    owner = _require(ctx, permission)
    return {"owner": owner}


@auth.authenticate
async def authenticate(authorization: str | None = None) -> Auth.types.MinimalUserDict:
    """Verify bearer credentials and expose only the opaque owner identity."""
    if settings.auth_mode == "none" and settings.env == "development":
        return {
            "identity": "studio:development",
            "is_authenticated": True,
            "permissions": sorted(DEV_PERMISSIONS),
        }
    if settings.auth_mode != "jwt":
        raise _http_error(401, "Bearer authentication required")

    try:
        principal: Principal = await token_verifier.verify(authorization)
    except AuthenticationUnavailableError as exc:
        raise _http_error(503, "Authentication unavailable") from exc
    except AuthenticationError as exc:
        raise _http_error(401, "Invalid bearer token") from exc

    identity_key = settings.identity_hash_key
    if identity_key is None:
        raise _http_error(503, "Authentication unavailable")
    owner = principal_owner_key(principal, identity_key.get_secret_value())
    return {
        "identity": owner,
        "is_authenticated": True,
        "permissions": sorted(principal.scopes),
    }


@auth.on
async def deny_unregistered_actions(ctx: Auth.types.AuthContext, value: Any) -> bool:
    """Deny every Agent Server action without a more-specific policy."""
    return False


@auth.on.threads.create
async def create_thread(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _stamp_owner(ctx, value, "agent:invoke")


@auth.on.threads.create_run
async def create_thread_run(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _owner_filter(ctx, "agent:invoke")


@auth.on.threads.read
async def read_thread(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _owner_filter(ctx, "threads:read")


@auth.on.threads.search
async def search_threads(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _owner_filter(ctx, "threads:read")


@auth.on.threads.update
async def update_thread(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _stamp_owner(ctx, value, "threads:delete")


@auth.on.threads.delete
async def delete_thread(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _owner_filter(ctx, "threads:delete")


@auth.on.assistants.create
async def create_assistant(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _stamp_owner(ctx, value, "assistants:write")


@auth.on.assistants.read
async def read_assistant(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _owner_filter(ctx, "agent:invoke")


@auth.on.assistants.search
async def search_assistants(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _owner_filter(ctx, "agent:invoke")


@auth.on.assistants.update
async def update_assistant(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _stamp_owner(ctx, value, "assistants:write")


@auth.on.assistants.delete
async def delete_assistant(ctx: Auth.types.AuthContext, value: Any) -> dict[str, str]:
    return _owner_filter(ctx, "assistants:delete")
