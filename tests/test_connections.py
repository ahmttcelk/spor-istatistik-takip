import io
import unittest
import urllib.error
from unittest.mock import patch
from scripts.check_connections import SafeError, request_json, valid_api, run

class SecurityTests(unittest.TestCase):
    def test_api_errors_are_not_echoed(self):
        with self.assertRaises(SafeError) as ctx:
            valid_api({"errors": {"token": "PRIVATE_TEST_VALUE"}})
        self.assertNotIn("PRIVATE_TEST_VALUE", str(ctx.exception))

    def test_url_in_network_errors_is_not_echoed(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("PRIVATE_TEST_TOKEN")):
            with self.assertRaises(SafeError) as ctx:
                request_json("https://api.telegram.org", "/botPRIVATE_TEST_TOKEN/sendMessage")
        self.assertNotIn("PRIVATE_TEST_TOKEN", str(ctx.exception))

    def test_missing_credentials_fail_before_network(self):
        with patch.dict("os.environ", {}, clear=True), patch("urllib.request.urlopen") as net:
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(run(), 1)
            net.assert_not_called()

if __name__ == "__main__":
    unittest.main()
