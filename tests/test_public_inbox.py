import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

from inbox_links import load_links, save_link
from public_inbox import publish_inbox_link


class PublicInboxTest(unittest.TestCase):
    def test_lost_registration_response_reuses_the_same_opaque_link(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "links.json"
            record = save_link("one@icloud.com", "one@fastaiapi.cloud",
                               "https://webmail.fastaiapi.cloud/?jwt=upstream-token", path=path)
            config = {"admin_token": "a" * 43, "base_url": "https://webmail.fastaiapi.cloud"}
            http = Mock()
            http.put.side_effect = requests.Timeout()
            with self.assertRaises(RuntimeError):
                publish_inbox_link(record, registry=path, config=config, http=http)
            first_url = http.put.call_args.args[0]
            first_hash = http.put.call_args.kwargs["json"]["token_hash"]
            http.put.side_effect = None
            http.put.return_value = Mock(status_code=200, json=lambda: {"ok": True, "alias": "one@icloud.com"})
            result = publish_inbox_link(load_links(path)["one@icloud.com"], registry=path, config=config, http=http)
            self.assertEqual(http.put.call_args.args[0], first_url)
            self.assertEqual(http.put.call_args.kwargs["json"]["token_hash"], first_hash)
            self.assertRegex(result["inbox_url"], r"^https://webmail\.fastaiapi\.cloud/m/mbx_\d{9}\.[A-Za-z0-9_-]{43}$")
            self.assertNotIn("jwt=", result["inbox_url"])
            self.assertEqual(result["forward_inbox_url"], record["inbox_url"])
            self.assertNotIn("cookies", http.put.call_args.kwargs["json"])

    def test_short_link_validator_rejects_extra_queries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "links.json"
            url = "https://webmail.fastaiapi.cloud/m/mbx_123456789." + "a" * 43
            save_link("one@icloud.com", "one@fastaiapi.cloud", url, path=path)
            for changed in (url + "?email=other@icloud.com", url.replace("webmail.fastaiapi.cloud", "evil.example")):
                with self.assertRaises(ValueError):
                    save_link("one@icloud.com", "one@fastaiapi.cloud", changed, path=path)


if __name__ == "__main__":
    unittest.main()
