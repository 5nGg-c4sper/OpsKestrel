"""Tests for the basic automation safety policy."""

import unittest

from soc_agent.safety.policy import SafetyPolicy, SafetyViolation
from soc_agent.task_models import TaskStep


class SafetyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = SafetyPolicy()

    def test_allows_normal_open_app(self):
        self.policy.validate(TaskStep(type="open_app", app="计算器"))

    def test_allows_normal_keyboard_shortcut(self):
        self.policy.validate(
            TaskStep(type="press", keys=["command", "l"])
        )

    def test_blocks_command_q(self):
        with self.assertRaisesRegex(SafetyViolation, "Command\\+Q"):
            self.policy.validate(
                TaskStep(type="press", keys=["command", "q"])
            )

    def test_blocks_command_q_case_insensitively(self):
        with self.assertRaises(SafetyViolation):
            self.policy.validate(
                TaskStep(type="press", keys=["Command", "Q"])
            )

    def test_blocks_terminal(self):
        with self.assertRaisesRegex(SafetyViolation, "Terminal"):
            self.policy.validate(
                TaskStep(type="open_app", app="Terminal")
            )

    def test_blocks_activate_terminal(self):
        with self.assertRaisesRegex(SafetyViolation, "Terminal"):
            self.policy.validate(
                TaskStep(type="activate_app", app="Terminal")
            )

    def test_allows_normal_activate_app(self):
        self.policy.validate(
            TaskStep(type="activate_app", app="Safari")
        )

    def test_blocks_system_settings(self):
        with self.assertRaises(SafetyViolation):
            self.policy.validate(
                TaskStep(type="open_app", app="系统设置")
            )

    def test_blocks_close_document_for_terminal(self):
        with self.assertRaisesRegex(SafetyViolation, "Terminal"):
            self.policy.validate(
                TaskStep(type="close_document", app="Terminal")
            )

    def test_supports_custom_blocked_apps(self):
        policy = SafetyPolicy(blocked_apps={"Mail"})

        with self.assertRaises(SafetyViolation):
            policy.validate(TaskStep(type="open_app", app="mail"))


if __name__ == "__main__":
    unittest.main()
