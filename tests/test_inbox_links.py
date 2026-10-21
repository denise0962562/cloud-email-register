import tempfile
import unittest
from pathlib import Path

from inbox_links import export_lines, save_link


class InboxLinksTest(unittest.TestCase):
    def test_only_verified_matching_aliases_are_exported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "links.json"
            url = "https://webmail.fastaiapi.cloud/?jwt=test-token"
            save_link("first@icloud.com", "one@fastaiapi.cloud", url, path=path)
            self.assertEqual(export_lines(["first@icloud.com"], path), [])
            save_link("first@icloud.com", "one@fastaiapi.cloud", url, verified=True, path=path)
            self.assertEqual(export_lines(["second@icloud.com"], path), [])
            self.assertEqual(export_lines(["first@icloud.com"], path), ["first@icloud.com----" + url])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_rejects_other_origins_and_non_https_links(self):
        for url in ("http://webmail.fastaiapi.cloud/?jwt=x", "https://evil.example/?jwt=x",
                    "https://webmail.fastaiapi.cloud/", "https://webmail.fastaiapi.cloud@evil.example/?jwt=x"):
            with self.assertRaises(ValueError):
                save_link("first@icloud.com", "one@fastaiapi.cloud", url)


if __name__ == "__main__":
    unittest.main()
