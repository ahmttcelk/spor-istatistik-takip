import unittest
from scripts.probe_coverage import reason

class CoverageTests(unittest.TestCase):
    def test_free_season_restriction(self):
        self.assertEqual(reason({"errors": {"plan": "Free plans do not have access to this season"}}),
                         "FREE_PLAN_ACCESS_RESTRICTED")
    def test_opaque_errors_never_escape(self):
        result = reason({"errors": {"other": "PRIVATE_SENTINEL"}})
        self.assertEqual(result, "API_REJECTED")
        self.assertNotIn("PRIVATE_SENTINEL", result)
    def test_empty_errors_are_success(self):
        self.assertEqual(reason({"errors": []}), "OK")
