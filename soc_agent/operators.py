"""Local operator authentication and role checks for the console."""

import hmac
from dataclasses import dataclass
from enum import Enum


class OperatorError(ValueError):
    """Raised when console operator authentication fails."""


class OperatorRole(str, Enum):
    VIEWER = "viewer"
    REVIEWER = "reviewer"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return {
            self.VIEWER: 1,
            self.REVIEWER: 2,
            self.ADMIN: 3,
        }[self]


@dataclass(frozen=True)
class OperatorIdentity:
    name: str
    role: OperatorRole


class OperatorAuthenticator:
    def __init__(self, name, token, role=OperatorRole.REVIEWER):
        self.name = str(name).strip()
        self.token = str(token or "")
        self.role = OperatorRole(role)
        if not self.name:
            raise OperatorError("operator name must not be empty")
        if len(self.name) > 100:
            raise OperatorError(
                "operator name must be 100 characters or fewer"
            )

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def authenticate(self, authorization: str = "") -> OperatorIdentity:
        if not self.enabled:
            raise OperatorError(
                "console operator authentication is not configured"
            )
        scheme, separator, supplied = str(
            authorization or ""
        ).partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or not supplied
        ):
            raise OperatorError("missing bearer token")
        if not hmac.compare_digest(supplied, self.token):
            raise OperatorError("invalid operator token")
        return OperatorIdentity(self.name, self.role)

    def require(
        self,
        authorization: str,
        required_role=OperatorRole.VIEWER,
    ) -> OperatorIdentity:
        identity = self.authenticate(authorization)
        if identity.role.rank < OperatorRole(required_role).rank:
            raise OperatorError(
                f"{required_role.value} role is required"
            )
        return identity
