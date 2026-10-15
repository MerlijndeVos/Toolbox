import unittest
from unittest import mock

from core import updates


def _release(body, assets=None, tag="x"):
    return {
        "tag_name": tag,
        "body": body,
        "html_url": "https://example.test/r",
        "assets": assets if assets is not None else [{"name": "Toolbox-3.6.0-win64.exe", "browser_download_url": "https://example.test/a"}],
    }


class VersionOrderTest(unittest.TestCase):
    def test_experimental_build_is_ahead_of_its_release_only(self):
        self.assertTrue(updates._is_newer("3.6.0-exp.abc1234", "3.6.0"))
        self.assertFalse(updates._is_newer("3.6.0", "3.6.0-exp.abc1234"))
        self.assertTrue(updates._is_newer("3.7.0", "3.6.0-exp.abc1234"))
        self.assertFalse(updates._is_newer("3.6.0-exp.abc1234", "3.7.0"))


class CheckForUpdateTest(unittest.TestCase):
    def _check(self, *, enabled, current, official, experimental):
        def fake_get(url, timeout):
            if url == updates.GITHUB_LATEST:
                return (200, official, None) if official else (404, None, "")
            return (200, experimental, None) if experimental else (404, None, "")

        with mock.patch.object(updates, "_github_get", fake_get), \
             mock.patch.object(updates, "app_version", return_value=current), \
             mock.patch.object(updates, "is_frozen", return_value=True), \
             mock.patch.object(updates, "_pick_asset", lambda a: a[0] if a else None), \
             mock.patch.object(updates, "load_settings", return_value={"experimental_updates": enabled}):
            return updates.check_for_update()

    def test_off_ignores_the_experimental_build(self):
        info = self._check(
            enabled=False, current="3.6.0",
            official=_release("", tag="v3.6.0"),
            experimental=_release("build: 3.6.0-exp.abc1234"),
        )
        self.assertFalse(info.update_available)
        self.assertFalse(info.experimental)

    def test_on_offers_the_experimental_build(self):
        info = self._check(
            enabled=True, current="3.6.0",
            official=_release("", tag="v3.6.0"),
            experimental=_release("build: 3.6.0-exp.abc1234"),
        )
        self.assertTrue(info.update_available)
        self.assertTrue(info.experimental)
        self.assertEqual(info.latest_version, "3.6.0-exp.abc1234")

    def test_same_experimental_build_is_up_to_date(self):
        info = self._check(
            enabled=True, current="3.6.0-exp.abc1234",
            official=_release("", tag="v3.6.0"),
            experimental=_release("build: 3.6.0-exp.abc1234"),
        )
        self.assertFalse(info.update_available)

    def test_newer_official_release_wins(self):
        info = self._check(
            enabled=True, current="3.6.0-exp.abc1234",
            official=_release("", tag="v3.7.0"),
            experimental=_release("build: 3.6.0-exp.abc1234"),
        )
        self.assertFalse(info.experimental)
        self.assertTrue(info.update_available)
        self.assertEqual(info.latest_version, "3.7.0")

    def test_missing_experimental_release_falls_back(self):
        info = self._check(
            enabled=True, current="3.6.0",
            official=_release("", tag="v3.6.0"),
            experimental=None,
        )
        self.assertFalse(info.experimental)


if __name__ == "__main__":
    unittest.main()
