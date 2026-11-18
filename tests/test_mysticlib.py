import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import mysticlib as M


class Palette(unittest.TestCase):
    def test_endpoints_and_clamp(self):
        self.assertEqual(M.palette_color("thermal", 0), (0, 90, 255))
        self.assertEqual(M.palette_color("thermal", 1), (255, 0, 0))
        self.assertEqual(M.palette_color("thermal", -3), (0, 90, 255))
        self.assertEqual(M.palette_color("thermal", 7), (255, 0, 0))

    def test_midpoint_interpolates(self):
        self.assertEqual(M.palette_color("ice-fire", 0.25), (85, 80, 255))

    def test_brightness(self):
        self.assertEqual(M.scale((255, 100, 0), 50), (128, 50, 0))


class Levels(unittest.TestCase):
    R = M.DEFAULTS["ranges"]

    def test_normalize(self):
        self.assertEqual(M.zone_level("cpu-temp", {"cpu-temp": 65}, self.R), (65, "°C", 0.5))

    def test_missing_and_off(self):
        self.assertIsNone(M.zone_level("gpu-load", {}, self.R)[2])
        self.assertIsNone(M.zone_level("off", {"cpu-temp": 50}, self.R)[2])

    def test_hottest_picks_highest_fraction(self):
        v, unit, f = M.zone_level("hottest", {"cpu-temp": 65, "gpu-temp": 80}, self.R)   # 0.5 vs 0.9
        self.assertEqual((v, round(f, 2)), (80, 0.9))

    def test_critical(self):
        self.assertTrue(M.is_critical({"cpu-temp": 91}, {"cpu-temp": 90}))
        self.assertFalse(M.is_critical({"cpu-temp": None}, {"cpu-temp": 90}))


class Config(unittest.TestCase):
    def test_defaults_valid(self):
        M.validate(M.merge(M.DEFAULTS, {}))

    def test_rejects_bad_values(self):
        for over in ({"brightness": 150}, {"palette": "nope"}, {"zones": {"JRAINBOW1": {"source": "x"}}},
                     {"ranges": {"cpu-temp": [90, 40]}}, {"zones": {"JRAINBOW1": {"leds": 0}}},
                     {"zones": {"GPU": {"device": ""}}}):
            with self.assertRaises(ValueError, msg=over):
                M.validate(M.merge(M.DEFAULTS, over))

    def test_device_defaults_to_msi(self):
        cfg = M.validate(M.merge(M.DEFAULTS, {"zones": {"X": {"label": "x", "source": "off", "leds": 5, "index": 1}}}))
        self.assertEqual(cfg["zones"]["X"]["device"], "MSI")
        self.assertEqual(cfg["zones"]["GPU"]["device"], "Sapphire")

    def test_set_key(self):
        cfg = M.merge(M.DEFAULTS, {})
        M.set_key(cfg, "zones.JRAINBOW1.source", "cpu-load")
        self.assertEqual(cfg["zones"]["JRAINBOW1"]["source"], "cpu-load")
        with self.assertRaises(ValueError):
            M.set_key(cfg, "zones.NOPE.source", "x")
        self.assertEqual(M.parse_value("[40,90]"), [40, 90])
        self.assertEqual(M.parse_value("gpu-temp"), "gpu-temp")


class FakeSysfs(unittest.TestCase):
    def test_reads_temps_and_load(self):
        with tempfile.TemporaryDirectory() as root:
            def put(rel, text):
                p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write(text)
            put("sys/class/hwmon/hwmon0/name", "k10temp\n")
            put("sys/class/hwmon/hwmon0/temp1_label", "Tctl\n"); put("sys/class/hwmon/hwmon0/temp1_input", "55250\n")
            put("sys/class/hwmon/hwmon1/name", "amdgpu\n")
            put("sys/class/hwmon/hwmon1/temp1_label", "edge\n"); put("sys/class/hwmon/hwmon1/temp1_input", "48000\n")
            put("sys/class/drm/card1/device/vendor", "0x1002\n"); put("sys/class/drm/card1/device/gpu_busy_percent", "37\n")
            put("proc/stat", "cpu 100 0 100 800 0 0 0 0 0 0\n")
            s = M.Sensors(root)
            self.assertIsNone(s.read()["cpu-load"])          # needs two samples
            put("proc/stat", "cpu 200 0 200 900 0 0 0 0 0 0\n")
            m = s.read()
            self.assertEqual((m["cpu-temp"], m["gpu-temp"], m["gpu-load"]), (55.25, 48, 37.0))
            self.assertAlmostEqual(m["cpu-load"], 200 / 3)


if __name__ == "__main__":
    unittest.main()
