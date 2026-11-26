"""Tests for local console operator authentication."""

import unittest

from opskestrel.operators import (
    OperatorAuthenticator,
    OperatorError,
    OperatorRole,
)


class OperatorAuthenticatorTests(unittest.TestCase):
    def test_valid_token_returns_configured_identity(self):
        authenticator = OperatorAuthenticator(
            "operator-a",
            "secret-token",
            OperatorRole.REVIEWER,
        )

        identity = authenticator.require(
            "Bearer secret-token",
            OperatorRole.REVIEWER,
        )

        self.assertEqual(identity.name, "operator-a")
        self.assertEqual(identity.role, OperatorRole.REVIEWER)

    def test_invalid_token_is_rejected(self):
        authenticator = OperatorAuthenticator(
            "operator-a",
            "secret-token",
        )

        with self.assertRaisesRegex(OperatorError, "invalid"):
            authenticator.require("Bearer wrong-token")

    def test_role_threshold_is_enforced(self):
        authenticator = OperatorAuthenticator(
            "viewer-a",
            "secret-token",
            OperatorRole.VIEWER,
        )

        with self.assertRaisesRegex(OperatorError, "reviewer role"):
            authenticator.require(
                "Bearer secret-token",
                OperatorRole.REVIEWER,
            )

    def test_missing_server_token_disables_authentication(self):
        authenticator = OperatorAuthenticator(
            "operator-a",
            "",
            OperatorRole.REVIEWER,
        )

        self.assertFalse(authenticator.enabled)
        with self.assertRaisesRegex(OperatorError, "not configured"):
            authenticator.authenticate("Bearer anything")


if __name__ == "__main__":
    unittest.main()
