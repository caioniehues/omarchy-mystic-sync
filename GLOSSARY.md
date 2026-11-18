# Mystic Sync

Colours PC lighting by hardware temperature or load, and shows the readings in the Omarchy bar.

## Readings

**Reading**:
A raw sensor value in °C or %, such as CPU temperature or GPU load.
_Avoid_: metric, value

**Source**:
What a zone follows: one reading, the hottest or busiest of a pair, or nothing (`off`).

**Range**:
The span of readings, low to high, that is mapped onto a palette.

**Level**:
A reading placed within its range, from 0 at low to 1 at high.
_Avoid_: fraction

**Critical**:
A raw reading at or above its limit; while any reading is critical, every zone flashes red.

## Lighting

**Palette**:
The colour stops a level is mapped through; built-in palettes are fixed, custom ones are composed by the user.

**Stop**:
A position on a palette, from 0 to 1, with its colour.

**Preview**:
A colour held on a zone for a moment while a palette is being composed; never saved.

**Zone**:
A named config entry that colours one OpenRGB zone from one source.

**Header**:
A physical ARGB connector on the motherboard, such as JRAINBOW1.
_Avoid_: zone (for the connector)

**Paused**:
Mystic Sync has stepped back and the lights show the saved OpenRGB profile instead.
_Avoid_: disabled, off

**Dark**:
Every zone is black while Mystic Sync keeps running, because the screens are off; a critical reading still flashes.
_Avoid_: paused, off

**Device**:
An OpenRGB controller, such as the MSI board or the Nitro+.
_Avoid_: controller
