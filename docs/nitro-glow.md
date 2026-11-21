# Sapphire Nitro Glow V3 chip (RX 7800 XT Nitro+)

The card's LED microcontroller, as found when a power cut left the light bar
dark and then a third lit. `bin/glow.py` restores the two registers a power cut
resets; everything else here is reference for the next time the LEDs misbehave.

- I²C address `0x28` on the bus sysfs names `AMDGPU DM i2c OEM bus`
  (`/dev/i2c-7` on this machine; find it by name, the number can change).
- PCI `1002:747e`, subsystem `1da2:d475`.
- Read and write with `i2cget -y <bus> 0x28 <reg> b` / `i2cset -y <bus> 0x28 <reg> <value> b`
  (`i2c-tools`); `i2cdump -y -r 0x00-0x7f <bus> 0x28 b` shows them all.

## Registers

"Writes" says who sets the register: OpenRGB 1.1's Nitro Glow V3 controller,
Sapphire's TRIXX 11.2.0, or this daemon.

| Reg | Meaning | TRIXX default | Writes |
|---|---|---|---|
| `0x0F` | external control (follow the motherboard header) | | OpenRGB, TRIXX |
| `0x10` | mode: 0 rainbow, 1 runway, 2 colour cycle, 3 serial, 4 Sapphire blue, 5 audio, 6 custom (static), 7 off, `0xFF` external | | OpenRGB, TRIXX |
| `0x11` | runway speed | 30 | OpenRGB, TRIXX |
| `0x12` | runway repeat count | 1 | OpenRGB, TRIXX |
| `0x13` | colour cycle speed | 2 | OpenRGB, TRIXX |
| `0x15` | rainbow speed | 100 | OpenRGB, TRIXX |
| `0x16` | serial speed | 200 | OpenRGB, TRIXX |
| `0x1A`–`0x1C` | red, green, blue | | OpenRGB, TRIXX |
| `0x20`, `0x21` | written by TRIXX (enums of its newer V4 chip); 0–2 and 3 changed nothing here | | TRIXX |
| `0x27` | LED strip length: 6 lights a third of the bar, 18 more, 36 all of it (exact count not bisected) | | mystic-sync (36) |
| `0x29` | music volume (audio mode) | | |
| `0x3E` | brightness: 6 dim, 100 bright | 6 | TRIXX, mystic-sync (100) |

- TRIXX writes nothing outside `0x0F`–`0x1C`, `0x20`, `0x21` and `0x3E`.
- OpenRGB's driver has a `SetBrightness`, but its RGB controller never calls it.
- A full power loss (not a shutdown: standby power keeps the chip alive) resets
  `0x27` to 6 and `0x3E` to 0. Runway also stayed dark until `0x11`–`0x16` got
  TRIXX's defaults, so those were probably reset as well; only custom mode,
  which the daemon uses, ignores them.

## Telling a firmware setting from dead LEDs

The chip's built-in animations are a split test. Rainbow (`0x10` = 0) lighting
the same third showed the fault was not in custom mode. Runway (`0x10` = 1)
running to the end of the lit third and starting over showed the chip itself
counted too few LEDs: dead LEDs would let the light run on into the dark part.

## Sources

- OpenRGB `Controllers/SapphireGPUController/SapphireNitroGlowV3Controller/`
  (gitlab.com/CalcProgrammer1/OpenRGB): the register and mode names.
- github.com/Yimura/nitroglow-linux, `docs/investigation/02-trixx-reversing.md`:
  how TRIXX hides its code.
- TRIXX 11.2.0 (`TRIXX_11.2.0.zip` from sapphiretech.com): the defaults and the
  list of registers it writes. The .NET program is resource `RCDATA/132` of
  `TRIXX_11.2.0.exe` (`7z e`), encrypted as
  `p[i] = c[i] ^ c[i-1] ^ key[i % 13]` with key `SapphireTrixx` and `c[-1] = 0`.
  Decompile the result with `ilspycmd`. Its names are obfuscated with zero-width
  characters, which `sed -E 's/(\\u[0-9a-f]{4})+/«p»/g'` makes readable.
