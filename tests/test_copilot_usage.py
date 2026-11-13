import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import collector
import copilot_usage


class CopilotUsageTests(unittest.TestCase):
    def test_parse_quotas_and_reset_dates(self):
        result = copilot_usage.parse_usage({
            "copilot_plan": "individual",
            "quota_reset_date": "2026-12-01",
            "quota_snapshots": {
                "premium_interactions": {"percent_remaining": 37.5, "entitlement": 300},
                "chat": {"unlimited": True},
                "weekly": {"percent_remaining": 20, "reset_at": "2026-11-15T12:00:00Z"},
            },
        })
        self.assertEqual(result["plan"], "individual")
        self.assertEqual(result["quotas"]["premium_interactions"]["utilization"], 62.5)
        self.assertEqual(result["quotas"]["premium_interactions"]["reset_at"],
                         "2026-12-01T00:00:00+00:00")
        self.assertTrue(result["quotas"]["chat"]["unlimited"])
        self.assertEqual(result["quotas"]["weekly"]["reset_at"],
                         "2026-11-15T12:00:00+00:00")
        self.assertEqual(collector._copilot_metrics(result),
                         {"premium_interactions": 62.5, "chat": None, "weekly": 80})

    def test_missing_and_placeholder_quotas_are_not_reported_as_zero_usage(self):
        result = copilot_usage.parse_usage({"quota_snapshots": {
            "placeholder": {"unlimited": True, "entitlement": 0},
            "unknown": {"entitlement": 100},
            "invalid": {"percent_remaining": "nan"},
            "weekly": {"percent_remaining": 90},
        }, "quota_reset_date": "2026-12-01"})
        self.assertEqual(list(result["quotas"]), ["weekly"])
        self.assertIsNone(result["quotas"]["weekly"]["reset_at"])

    def test_token_is_saved_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.json"
            with patch.object(copilot_usage, "TOKEN_FILE", path):
                copilot_usage.save_token(" secret ")
                self.assertEqual(copilot_usage.load_token(), "secret")
                self.assertEqual(json.loads(path.read_text()), {"token": "secret"})
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    @patch("copilot_usage.requests.get")
    def test_authentication_failure_does_not_save_token(self, get):
        get.return_value = Mock(status_code=401)
        with self.assertRaises(copilot_usage.CopilotAuthError):
            copilot_usage.validate_token("bad")

    @patch("copilot_usage.requests.get")
    def test_successful_request_is_parsed(self, get):
        get.return_value = Mock(status_code=200, json=lambda: {
            "quota_snapshots": {"chat": {"percent_remaining": 80}},
        })
        usage = copilot_usage.validate_token("token")
        self.assertEqual(usage["quotas"]["chat"]["utilization"], 20)
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"],
                         "Bearer token")


if __name__ == "__main__":
    unittest.main()
