import json, os, socket, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import mysticlib as M


class Palette(unittest.TestCase):
    def test_endpoints_and_clamp(self):
        self.assertEqual(M.palette_color(M.PALETTES["thermal"], 0), (0, 90, 255))
        self.assertEqual(M.palette_color(M.PALETTES["thermal"], 1), (255, 0, 0))
        self.assertEqual(M.palette_color(M.PALETTES["thermal"], -3), (0, 90, 255))
        self.assertEqual(M.palette_color(M.PALETTES["thermal"], 7), (255, 0, 0))

    def test_midpoint_interpolates(self):
        self.assertEqual(M.palette_color(M.PALETTES["ice-fire"], 0.25), (85, 80, 255))

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
                     {"zones": {"GPU": {"device": ""}}}, {"decay": 0}):
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


class CustomPalettes(unittest.TestCase):
    DUSK = [[0, "#0000ff"], [0.5, "#ff00ff"], [1, "#ff0000"]]

    def cfg(self, **over):
        return M.validate(M.merge(M.DEFAULTS, over))

    def test_custom_palette_and_zone_override(self):
        cfg = self.cfg(palettes={"dusk": self.DUSK}, zones={"GPU": {"palette": "dusk"}})
        self.assertEqual(M.palette_color(M.stops("dusk", cfg["palettes"]), 0.25), (128, 0, 255))
        self.assertEqual(M.stops(cfg["palette"], cfg["palettes"]), M.PALETTES["thermal"])

    def test_bad_palettes_rejected(self):
        for pals in ({"thermal": self.DUSK}, {"Bad Name": self.DUSK}, {"x": [[0, "#000000"]]},
                     {"x": [[0.1, "#000000"], [1, "#ffffff"]]}, {"x": [[0, "#000000"], [0.7, "#000000"], [0.5, "#000000"], [1, "#ffffff"]]},
                     {"x": [[0, "red"], [1, "#ffffff"]]}):
            with self.assertRaises(ValueError, msg=pals):
                self.cfg(palettes=pals)
        with self.assertRaises(ValueError):
            self.cfg(zones={"GPU": {"palette": "nope"}})

    def test_create_and_delete_through_set_key(self):
        cfg = M.merge(M.DEFAULTS, {})
        M.set_key(cfg, "palettes.dusk", self.DUSK)
        M.set_key(cfg, "zones.GPU.palette", "dusk")
        M.validate(cfg)
        with self.assertRaisesRegex(ValueError, "in use by zones.GPU"):
            M.set_key(cfg, "palettes.dusk", None)
        M.set_key(cfg, "zones.GPU.palette", None)
        M.set_key(cfg, "palettes.dusk", None)
        self.assertNotIn("dusk", cfg["palettes"])
        self.assertNotIn("palette", M.validate(cfg)["zones"]["GPU"])


class Preview(unittest.TestCase):
    def test_fresh_valid_preview_only(self):
        path = os.path.join(tempfile.mkdtemp(), "preview.json")
        self.assertIsNone(M.read_preview(path))
        with open(path, "w") as f:
            json.dump({"zone": "JRAINBOW1", "color": "#ff8000"}, f)
        self.assertEqual(M.read_preview(path), ("JRAINBOW1", (255, 128, 0)))
        os.utime(path, (0, 0))                        # stale: the panel stopped refreshing it
        self.assertIsNone(M.read_preview(path))
        with open(path, "w") as f:
            f.write("{}")                             # what the panel writes when a stop is deselected
        self.assertIsNone(M.read_preview(path))


class Smoothing(unittest.TestCase):
    def test_rises_fast_falls_slow(self):
        self.assertEqual(M.smooth(None, 70, 0.5, 0.05), 70)        # first sample is taken as is
        self.assertEqual(M.smooth(50, 70, 0.5, 0.05), 60)
        self.assertAlmostEqual(M.smooth(70, 50, 0.5, 0.05), 69)


class Screens(unittest.TestCase):
    def hypr(self, monitors):
        """Fake Hyprland instance answering one j/monitors request; returns the runtime dir."""
        runtime = tempfile.mkdtemp()
        os.makedirs(os.path.join(runtime, "hypr", "stale"))
        open(os.path.join(runtime, "hypr", "stale", ".socket.sock"), "w").close()   # dead socket file: skipped
        os.makedirs(os.path.join(runtime, "hypr", "live"))
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(os.path.join(runtime, "hypr", "live", ".socket.sock"))
        srv.listen(1)
        def serve():
            conn, _ = srv.accept()
            with conn:
                self.assertEqual(conn.recv(64), b"j/monitors")
                conn.sendall(json.dumps(monitors).encode())
            srv.close()
        threading.Thread(target=serve, daemon=True).start()
        return runtime

    def test_dark_only_when_every_monitor_is_off(self):
        self.assertTrue(M.screens_off(self.hypr([{"dpmsStatus": False}, {"dpmsStatus": False}])))
        self.assertFalse(M.screens_off(self.hypr([{"dpmsStatus": False}, {"dpmsStatus": True}])))
        self.assertFalse(M.screens_off(self.hypr([])))

    def test_no_hyprland_keeps_lights_on(self):
        self.assertFalse(M.screens_off(tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()
