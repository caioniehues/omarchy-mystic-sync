# Mystic Sync

An Omarchy bar widget and user service that colours your RGB by temperature or
load: MSI Mystic Light ARGB headers and, directly over I²C, the graphics card.
Everything goes through OpenRGB's SDK server; the daemon is plain Python
(stdlib only).

- Each zone follows one source: `cpu-temp`, `gpu-temp`, `cpu-load`,
  `gpu-load`, `hottest`, `busiest` or `off`.
- The value is mapped through a palette (`thermal`, `ice-fire`, `traffic`,
  `violet`) and smoothed, so colours drift instead of flickering.
- When Hyprland turns every screen off (Omarchy does this 5 s after locking),
  the lights go dark; they come back within a quarter second of the screen.
- Past a critical temperature (CPU 90 °C, GPU hotspot 100 °C by default)
  every zone flashes red.
- The bar icon takes the colour of the hottest zone; its panel shows each
  zone's reading and lets you change source, palette and brightness, and has
  a palette composer: drag a stop's colour and the lights show it live.
- Right-click the icon to pause. Paused or stopped, the daemon loads the OpenRGB
  profile named in `restore_profile`.

Built and tested on an MSI B650 GAMING PLUS WIFI (MS-7E26, a 185-byte Mystic
Light board) with a Sapphire Radeon RX 7800 XT Nitro+.

## How it works

```
 /sys (k10temp, amdgpu)  ─►  mystic-sync.service  ──SDK──►  openrgb-server.service  ─►  MSI board (USB HID)
 /proc/stat                  (every 0.05 s)                 (openrgb --server)         Sapphire GPU (I²C)
                                    │
                                    └─►  $XDG_RUNTIME_DIR/mystic-sync/state.json  ─►  bar widget (Panel.qml)
```

Colours are only sent when a channel moves by 3 or more, plus every 5 s as a
keepalive in case another OpenRGB client overwrote them.

## Install

Needs `openrgb` (with its udev rules, so your user can open the board's
hidraw device and the GPU's I²C bus) and `python3`.

```sh
git clone https://github.com/caioniehues/omarchy-mystic-sync ~/Projects/omarchy-mystic-sync
cd ~/Projects/omarchy-mystic-sync

ln -s "$PWD" ~/.config/omarchy/plugins/caioniehues.mystic-sync
ln -s "$PWD"/systemd/*.service ~/.config/systemd/user/
mkdir -p ~/.config/mystic-sync && cp config.example.json ~/.config/mystic-sync/config.json

systemctl --user daemon-reload
systemctl --user enable --now openrgb-server mystic-sync
```

Then add the **Mystic Sync** widget to the bar. Before enabling, save your
current lighting in OpenRGB as a profile named `pre-mystic-sync` (or set
`restore_profile` to `""` to leave the lights as they are when paused).

## Configuration

`~/.config/mystic-sync/config.json`, merged over the defaults in
`bin/mysticlib.py`. The daemon re-reads it when it changes. Either edit it or
use the CLI, which validates before writing:

```sh
bin/mystic-sync set zones.GPU.source=gpu-load brightness=60 palette=thermal
bin/mystic-sync get       # effective config
bin/mystic-sync status    # live readings, colours, connection state
```

| Key | Meaning |
|---|---|
| `enabled` | `false` pauses and loads `restore_profile` |
| `brightness` | 0–100 % |
| `palette` | default palette: `thermal`, `ice-fire`, `traffic`, `violet` or a custom one |
| `palettes.<name>` | a custom palette: 2–8 stops `[position, "#rrggbb"]`, rising from 0 to 1; `null` deletes it (refused while in use) |
| `smoothing` | weight of a sample above the smoothed reading (20 per second), (0, 1]; 0.5 settles in about 0.2 s, 1 = no smoothing |
| `decay` | the same for a sample below it; 0.05 fades out over about 3 s, so heat shows at once and cooling drifts |
| `critical_flash`, `critical` | flash red at these raw readings |
| `ranges.<source>` | `[low, high]` mapped to the palette's start and end |
| `zones.<name>` | see below |

A zone:

```json
"GPU": { "label": "Nitro+", "source": "gpu-temp", "device": "Sapphire", "index": 0, "leds": 1, "palette": "ice-fire" }
```

- `palette` (optional): this zone's palette instead of the default one;
  `bin/mystic-sync set zones.GPU.palette=null` goes back to the default.
- `device`: part of the OpenRGB controller name. Leave it out for the MSI
  board (`"MSI"`).
- `index`: zone number on that controller. On the MS-7E26: 0 JRGB1,
  1 JRGB2, 2 JRAINBOW1, 3 JRAINBOW2. The Nitro+ has a single zone, 0.
- `leds`: LED count. Only MSI zones are resized (JRAINBOW1 up to 200,
  JRAINBOW2 up to 240), but 40 or fewer is far faster (see below); other
  controllers have a fixed size, so give their real count.

## The setup this repo is configured for

- **JRAINBOW1** drives all six case fans and follows CPU temperature.
- **JRAINBOW2 is physically dead.** It is a zone with source `off` anyway, so
  the daemon holds it at 1 LED (see "40 LEDs or fewer" below).
- **The GPU** used to take its lighting from the motherboard through its
  "External Control" mode. With that header gone it is driven directly: the
  Nitro+ has no Direct mode, so OpenRGB's custom mode falls back to its per-LED
  Static mode, one LED for the whole card.

## Things learned the hard way

- **Resize before custom mode.** On 185-byte MSI boards the header lengths
  only reach the hardware in the "enable per-LED" packet that `SETCUSTOMMODE`
  sends. Resizing afterwards changes OpenRGB's idea of the zone but not the
  board's. Custom mode also re-initialises the headers, which blinks anything
  attached, so the daemon only sends it at connect, after a config change that
  resizes a zone, after resume and when un-pausing.
- **Daisy-chained fans may not be in series.** The six fans here are
  chained, but every fan receives the same data from LED 1 (the chain cable is
  a parallel pass-through). Per-fan colours are impossible on such a chain, and
  raising the LED count past the longest fan (about 15 here) changes nothing.
- **Keep every MSI header at 40 LEDs or fewer, even unused ones.** OpenRGB 1.1
  then sends each update as one HID report (~1 ms). If any header is longer, it
  sends one report per header with a 13 ms sleep after each (~29 ms per update,
  measured with strace). OpenRGB queues those writes in order, so at 20 updates
  a second the slow path would fall behind. A header left out of `zones` keeps
  whatever size OpenRGB last saved, so list it with source `off`. If a zone is
  over 40, the daemon slows its loop to keep up.
- **Mixed fan models render colours differently.** Fans 4–6 are a different
  model with a much stronger blue. Pure red, green, blue, blue-violet, purple
  and magenta look the same on both models; anything mixing green, or red with
  a little blue, comes out bluer or more purple on fans 4–6. No amount of green
  boost fixed it, so the `violet` palette uses only the colours matched by eye:
  blue → blue-violet → purple → magenta, then a short step to red at 85–90 % of
  the range.
- **Don't order the OpenRGB server after `graphical-session.target`.**
  mystic-sync is wanted by that target and ordered after the server, so the
  server must not also be ordered after the target. That loop made systemd
  silently drop both jobs at login.
- **OpenRGB takes ~10–25 s to detect the MSI board.** The GPU shows up first.
  The daemon keeps retrying (up to every 5 s) and reports which controller is
  still missing.
- **Stopping the daemon loads `restore_profile`.** If that profile has the GPU
  in External Control and the header is gone, the card goes dark while paused.
  Save the profile again with a GPU colour.

## Tests

```sh
python3 -I -m unittest discover -s tests
```

## License

MIT
