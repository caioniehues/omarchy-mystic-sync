"""Pure logic for mystic-sync: sensors, palettes, config. No hardware I/O here except sysfs reads and one Hyprland query."""
import copy, glob, json, os, re, socket, time

SOURCES = ("cpu-temp", "gpu-temp", "cpu-load", "gpu-load", "hottest", "busiest", "off")
PALETTES = {
    # stops: (position 0..1, (r, g, b))
    "thermal": [(0.0, (0, 90, 255)), (0.35, (0, 220, 200)), (0.55, (0, 255, 60)),
                (0.75, (255, 200, 0)), (0.88, (255, 90, 0)), (1.0, (255, 0, 0))],
    "ice-fire": [(0.0, (0, 160, 255)), (0.5, (170, 0, 255)), (1.0, (255, 0, 30))],
    "traffic": [(0.0, (0, 255, 40)), (0.6, (255, 210, 0)), (1.0, (255, 0, 0))],
    # No green, and blue stays at full until the last step: the second fan model on JRAINBOW1 has a far
    # stronger blue, so green mixes and red-with-a-little-blue look different on it. These stops were
    # matched by eye on both models; the magenta -> red step is kept short because its middle doesn't match.
    "violet": [(0.0, (0, 0, 255)), (0.3, (90, 0, 255)), (0.6, (180, 0, 255)), (0.85, (255, 0, 255)),
               (0.9, (255, 0, 0)), (1.0, (255, 0, 0))],
}
DEFAULTS = {
    "enabled": True,
    "brightness": 100,            # percent
    "palette": "thermal",         # built-in or custom; a zone may set its own
    "palettes": {},               # custom palettes: name -> [[position 0..1, "#rrggbb"], ...], first at 0, last at 1
    "smoothing": 0.5,             # EMA weight of a sample above the smoothed reading (1 = no smoothing)
    "decay": 0.05,                # ... and of one below it: heat shows at once, cooling fades out
    "critical_flash": True,
    "restore_profile": "pre-mystic-sync",   # OpenRGB profile applied when disabled/stopped ("" = leave as is)
    "ranges": {                   # value mapped to palette start..end
        "cpu-temp": [40, 90], "gpu-temp": [35, 85], "cpu-load": [0, 100], "gpu-load": [0, 100],
    },
    "critical": {"cpu-temp": 90, "gpu-hotspot": 100},
    # device: substring of the OpenRGB controller name (default "MSI"); index: zone number on that controller.
    # JRAINBOW2 (zone 3) is physically dead on this board; it stays "off" so it is held at 1 LED (see MSI_SYNC_MAX).
    "zones": {
        "JRAINBOW1": {"label": "Fans", "source": "cpu-temp", "leds": 40, "index": 2},
        "JRAINBOW2": {"label": "Dead header", "source": "off", "leds": 1, "index": 3},
        "GPU": {"label": "Nitro+", "source": "gpu-temp", "leds": 1, "index": 0, "device": "Sapphire"},
    },
}
MSI = "MSI"                       # the Mystic Light controller: its ARGB header zones are resizable
UNITS = {"cpu-temp": "°C", "gpu-temp": "°C", "cpu-load": "%", "gpu-load": "%"}


def merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def validate(cfg):
    """Raise ValueError on anything the daemon can't use."""
    if not isinstance(cfg.get("enabled"), bool):
        raise ValueError("enabled must be true/false")
    if not (isinstance(cfg.get("brightness"), (int, float)) and 0 <= cfg["brightness"] <= 100):
        raise ValueError("brightness must be 0-100")
    pals = cfg.get("palettes")
    if not isinstance(pals, dict):
        raise ValueError("palettes must be a map of name to stops")
    for name, st in pals.items():
        if name in PALETTES or not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError(f"palettes.{name}: names are lowercase letters, digits and -, and not a built-in name")
        if not (isinstance(st, list) and 2 <= len(st) <= 8 and all(
                isinstance(s, list) and len(s) == 2 and isinstance(s[0], (int, float)) and isinstance(s[1], str)
                and re.fullmatch(r"#[0-9a-fA-F]{6}", s[1]) for s in st)):
            raise ValueError(f"palettes.{name} must be 2-8 stops of [position, \"#rrggbb\"]")
        pos = [s[0] for s in st]
        if pos[0] != 0 or pos[-1] != 1 or pos != sorted(pos):
            raise ValueError(f"palettes.{name}: positions must rise from 0 to 1")
    known = list(PALETTES) + list(pals)
    if cfg.get("palette") not in known:
        raise ValueError("palette must be one of " + ", ".join(known))
    if not (isinstance(cfg.get("smoothing"), (int, float)) and 0 < cfg["smoothing"] <= 1):
        raise ValueError("smoothing must be in (0, 1]")
    if not (isinstance(cfg.get("decay"), (int, float)) and 0 < cfg["decay"] <= 1):
        raise ValueError("decay must be in (0, 1]")
    for src, rng in cfg["ranges"].items():
        if not (isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, (int, float)) for x in rng) and rng[0] < rng[1]):
            raise ValueError(f"ranges.{src} must be [low, high] with low < high")
    for name, z in cfg["zones"].items():
        if z.get("source") not in SOURCES:
            raise ValueError(f"zones.{name}.source must be one of " + ", ".join(SOURCES))
        if not (isinstance(z.get("leds"), int) and 1 <= z["leds"] <= 240):
            raise ValueError(f"zones.{name}.leds must be 1-240")
        if not (isinstance(z.get("index"), int) and z["index"] >= 0):
            raise ValueError(f"zones.{name}.index must be a zone number")
        if "palette" in z and z["palette"] not in known:
            raise ValueError(f"zones.{name}.palette: no palette named {z['palette']!r} (" + ", ".join(known) + ")")
        z.setdefault("device", MSI)
        if not (isinstance(z["device"], str) and z["device"].strip()):
            raise ValueError(f"zones.{name}.device must be part of an OpenRGB controller name")
    return cfg


def config_path():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "mystic-sync", "config.json")


def state_path():
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mystic-sync", "state.json")


def load_config(path=None):
    path = path or config_path()
    try:
        with open(path) as f:
            user = json.load(f)
    except FileNotFoundError:
        user = {}
    return validate(merge(DEFAULTS, user))


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def parse_value(raw):
    """CLI value: JSON when it parses (true, 60, [40,90]), else a plain string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def set_key(cfg, dotted, value):
    """Set an existing setting. palettes.<name> and zones.<zone>.palette may also be created; null removes them."""
    keys = dotted.split(".")
    optional = (len(keys) == 2 and keys[0] == "palettes") or (len(keys) == 3 and keys[0] == "zones" and keys[2] == "palette")
    node = cfg
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            raise ValueError(f"unknown setting {dotted}")
        node = node[k]
    if keys[-1] not in node and not optional:
        raise ValueError(f"unknown setting {dotted}")
    if value is None and optional:
        if keys[0] == "palettes":
            users = (["palette"] if cfg.get("palette") == keys[1] else []) + [
                f"zones.{n}" for n, z in cfg.get("zones", {}).items() if z.get("palette") == keys[1]]
            if users:
                raise ValueError(f"palette {keys[1]} is in use by " + ", ".join(users) + "; pick another there first")
        node.pop(keys[-1], None)
    else:
        node[keys[-1]] = value


# ---------- colour ----------

def rgb(hexstr):
    return tuple(int(hexstr[i:i + 2], 16) for i in (1, 3, 5))


def stops(name, custom):
    """A palette's stops as (position, (r, g, b)): built-in, else from the config's palettes."""
    return PALETTES[name] if name in PALETTES else [(p, rgb(h)) for p, h in custom[name]]


def palette_color(stops, t):
    t = max(0.0, min(1.0, t))
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if t <= p1:
            f = 0 if p1 == p0 else (t - p0) / (p1 - p0)
            return tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
    return stops[-1][1]


def scale(color, brightness):
    return tuple(round(c * brightness / 100) for c in color)


def hexcolor(c):
    return "#%02x%02x%02x" % tuple(c)


def normalize(value, rng):
    lo, hi = rng
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


# ---------- sensors ----------

class Sensors:
    """Reads sysfs; 'root' lets tests point it at a fake tree."""

    def __init__(self, root="/"):
        self.root = root
        self._prev_cpu = None
        self.hwmon = {}
        for d in glob.glob(os.path.join(root, "sys/class/hwmon/hwmon*")):
            name = _read(os.path.join(d, "name"))
            if name and name not in self.hwmon:
                self.hwmon[name] = d
        self.gpu_busy = None
        for p in sorted(glob.glob(os.path.join(root, "sys/class/drm/card*/device/gpu_busy_percent"))):
            if _read(os.path.join(os.path.dirname(p), "vendor")) == "0x1002":
                self.gpu_busy = p
                break

    def _temp(self, chip, label):
        d = self.hwmon.get(chip)
        if not d:
            return None
        for lab in glob.glob(os.path.join(d, "temp*_label")):
            if _read(lab) == label:
                v = _read(lab.replace("_label", "_input"))
                return int(v) / 1000 if v and v.lstrip("-").isdigit() else None
        return None

    def cpu_load(self):
        line = _read(os.path.join(self.root, "proc/stat")).splitlines()[0].split()
        vals = [int(x) for x in line[1:]]
        idle, total = vals[3] + (vals[4] if len(vals) > 4 else 0), sum(vals)
        prev, self._prev_cpu = self._prev_cpu, (idle, total)
        if not prev or total == prev[1]:
            return None
        return 100 * (1 - (idle - prev[0]) / (total - prev[1]))

    def read(self):
        busy = _read(self.gpu_busy) if self.gpu_busy else ""
        return {
            "cpu-temp": self._temp("k10temp", "Tctl"),
            "gpu-temp": self._temp("amdgpu", "edge"),
            "gpu-hotspot": self._temp("amdgpu", "junction"),
            "cpu-load": self.cpu_load(),
            "gpu-load": float(busy) if busy.isdigit() else None,
        }


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def zone_level(source, metrics, ranges):
    """(value, unit, fraction 0..1) for a zone source; None fraction when unreadable or off."""
    if source == "off":
        return None, "", None
    if source in ("hottest", "busiest"):
        pool = ("cpu-temp", "gpu-temp") if source == "hottest" else ("cpu-load", "gpu-load")
        best = None
        for s in pool:
            if metrics.get(s) is not None:
                f = normalize(metrics[s], ranges[s])
                if best is None or f > best[2]:
                    best = (metrics[s], UNITS[s], f)
        return best or (None, "", None)
    v = metrics.get(source)
    if v is None:
        return None, UNITS.get(source, ""), None
    return v, UNITS[source], normalize(v, ranges[source])


def smooth(prev, value, rise, fall):
    """One EMA step that follows a rising reading with weight rise and a falling one with weight fall."""
    if prev is None:
        return value
    return prev + (rise if value > prev else fall) * (value - prev)


def screens_off(runtime=None):
    """True when Hyprland reports every monitor DPMS-off. False when it can't be asked, so the lights stay on."""
    runtime = runtime or os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    for path in glob.glob(os.path.join(runtime, "hypr", "*", ".socket.sock")):   # stale instances just fail to connect
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(0.5)
                s.connect(path)
                s.sendall(b"j/monitors")
                data = b""
                while chunk := s.recv(65536):
                    data += chunk
            monitors = json.loads(data)
        except (OSError, ValueError):
            continue
        return bool(monitors) and not any(m.get("dpmsStatus", True) for m in monitors)
    return False


def read_preview(path=None, max_age=3.0):
    """(zone, (r, g, b)) the panel is previewing, or None. A preview not refreshed within max_age is ignored,
    so a crashed panel can't leave a zone stuck on it."""
    path = path or os.path.join(os.path.dirname(state_path()), "preview.json")
    try:
        if time.time() - os.stat(path).st_mtime > max_age:
            return None
        with open(path) as f:
            p = json.load(f)
        return (p["zone"], rgb(p["color"])) if re.fullmatch(r"#[0-9a-fA-F]{6}", p.get("color", "")) else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def is_critical(metrics, limits):
    return any(metrics.get(k) is not None and metrics[k] >= limit for k, limit in limits.items())
