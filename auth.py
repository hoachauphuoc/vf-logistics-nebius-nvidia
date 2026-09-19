"""
Authentication and authorization middleware for VF Logistics.

Implements Google IAP (Identity-Aware Proxy) JWT verification for Cloud Run,
with RBAC (Role-Based Access Control) for fine-grained permissions.

IAP Flow:
1. User authenticates via Google IAP (configured in GCP Console)
2. IAP adds X-Goog-IAP-JWT-Assertion header with signed JWT
3. This middleware verifies the JWT signature using Google's public keys
4. User email and roles are extracted and attached to the request context

Roles:
- viewer: Read-only access to dashboard and case details
- reviewer: Can approve/reject cases in review queue
- operator: Can run simulations, reset board, trigger processing
- governance_admin: Can modify delegation boundaries and permissions
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from flask import Request, g, jsonify, request

# IAP audience is the Cloud Run service URL
IAP_AUDIENCE = os.getenv("IAP_AUDIENCE", "")
# Bypass IAP in development
IAP_ENABLED = os.getenv("IAP_ENABLED", "false").lower() == "true"


class Role(str, Enum):
    """User roles for RBAC."""
    VIEWER = "viewer"
    REVIEWER = "reviewer"
    OPERATOR = "operator"
    GOVERNANCE_ADMIN = "governance_admin"


# Role hierarchy: higher roles include lower role permissions
ROLE_HIERARCHY = {
    Role.VIEWER: {Role.VIEWER},
    Role.REVIEWER: {Role.VIEWER, Role.REVIEWER},
    Role.OPERATOR: {Role.VIEWER, Role.REVIEWER, Role.OPERATOR},
    Role.GOVERNANCE_ADMIN: {Role.VIEWER, Role.REVIEWER, Role.OPERATOR, Role.GOVERNANCE_ADMIN},
}


@dataclass
class AuthContext:
    """Authenticated user context attached to request."""
    email: str
    roles: set[Role]
    iap_subject: str | None = None

    def has_role(self, required: Role) -> bool:
        """Check if user has the required role (including inherited)."""
        for user_role in self.roles:
            if required in ROLE_HIERARCHY.get(user_role, set()):
                return True
        return False


def _verify_iap_jwt(token: str) -> dict | None:
    """
    Verify Google IAP JWT and return claims.

    Returns None if verification fails.
    """
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claims = id_token.verify_token(
            token,
            google_requests.Request(),
            audience=IAP_AUDIENCE,
            certs_url="https://www.gstatic.com/iap/verify/public_key",
        )
        return claims
    except Exception:
        return None


def _get_user_roles(email: str) -> set[Role]:
    """
    Get roles for a user email.

    In production, this would query Firestore or a role management service.
    For now, uses environment-based configuration.
    """
    # Admin emails from environment (comma-separated)
    admin_emails = os.getenv("ADMIN_EMAILS", "").split(",")
    operator_emails = os.getenv("OPERATOR_EMAILS", "").split(",")
    reviewer_emails = os.getenv("REVIEWER_EMAILS", "").split(",")

    roles = {Role.VIEWER}  # Everyone gets viewer by default

    if email in admin_emails:
        roles.add(Role.GOVERNANCE_ADMIN)
    if email in operator_emails:
        roles.add(Role.OPERATOR)
    if email in reviewer_emails:
        roles.add(Role.REVIEWER)

    return roles


def get_auth_context() -> AuthContext | None:
    """Get the current request's auth context, or None if not authenticated."""
    return getattr(g, "auth_context", None)


def authenticate_request() -> tuple[dict, int] | None:
    """
    Authenticate the current request using IAP JWT.

    Returns an error response tuple if authentication fails, None if successful.
    Sets g.auth_context on success.
    """
    if not IAP_ENABLED:
        # Development mode: grant full access so dev workflow is unimpeded.
        # In production, IAP_ENABLED must be "true" and real JWT verification kicks in.
        g.auth_context = AuthContext(
            email="dev@localhost",
            roles={Role.GOVERNANCE_ADMIN},
            iap_subject=None,
        )
        return None

    # Get IAP JWT from header
    token = request.headers.get("X-Goog-IAP-JWT-Assertion")
    if not token:
        return jsonify({"error": "Missing IAP JWT header"}), 401

    # Verify JWT
    claims = _verify_iap_jwt(token)
    if not claims:
        return jsonify({"error": "Invalid IAP JWT"}), 401

    email = claims.get("email", "")
    if not email:
        return jsonify({"error": "No email in IAP claims"}), 401

    # Build auth context
    g.auth_context = AuthContext(
        email=email,
        roles=_get_user_roles(email),
        iap_subject=claims.get("sub"),
    )
    return None


def require_auth(f: Callable) -> Callable:
    """Decorator: require authentication for an endpoint."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        error = authenticate_request()
        if error:
            return error
        return f(*args, **kwargs)
    return decorated


def require_role(required_role: Role) -> Callable:
    """Decorator: require a specific role for an endpoint."""
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def decorated(*args, **kwargs):
            error = authenticate_request()
            if error:
                return error

            ctx = get_auth_context()
            if not ctx or not ctx.has_role(required_role):
                return jsonify({
                    "error": f"Insufficient permissions. Required role: {required_role.value}",
                    "user_roles": [r.value for r in (ctx.roles if ctx else [])],
                }), 403

            return f(*args, **kwargs)
        return decorated
    return decorator


# Convenience decorators for common role requirements
require_viewer = require_role(Role.VIEWER)
require_reviewer = require_role(Role.REVIEWER)
require_operator = require_role(Role.OPERATOR)
require_governance_admin = require_role(Role.GOVERNANCE_ADMIN)
