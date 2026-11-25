import unittest

from shirdal import DeviceProfile


class TestPhase18DeviceProfile(unittest.TestCase):
    def test_device_profile_presets_are_clean(self) -> None:
        win = DeviceProfile.desktop()
        mac = DeviceProfile.macos()
        self.assertEqual(win.device_model, "Desktop")
        self.assertEqual(win.system_version, "Windows 11")
        self.assertEqual(mac.device_model, "MacBook Pro")
        self.assertIn("macOS", mac.system_version)
