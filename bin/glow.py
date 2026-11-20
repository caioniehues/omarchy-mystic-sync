"""Sapphire Nitro Glow LED chip on the RX 7800 XT Nitro+ (stdlib only): re-apply what a power loss resets.

A full power loss (a shutdown keeps standby power) resets the chip's strip length to 6 LEDs, lighting a
third of the bar, and its brightness to 0. OpenRGB writes neither register, so they go over I2C here.
"""
import ctypes, fcntl, os, sys

SYSFS = "/sys/class/i2c-dev"
BUS_NAME = "AMDGPU DM i2c OEM bus"
ADDR = 0x28
I2C_SLAVE, I2C_SMBUS = 0x0703, 0x0720                        # linux/i2c-dev.h
I2C_SMBUS_WRITE, I2C_SMBUS_READ, I2C_SMBUS_BYTE_DATA = 0, 1, 2
CARD = ("0x1da2", "0xd475")          # PCI subsystem vendor/device of the RX 7800 XT Nitro+
SETTINGS = {0x27: 36, 0x3E: 100}     # strip length in LEDs (36 lights the whole bar), brightness


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def find_bus(root=SYSFS):
    """/dev/i2c-N of the Nitro+'s OEM bus, or None when that card is absent."""
    buses = sorted(os.listdir(root)) if os.path.isdir(root) else []   # no i2c-dev module, no buses
    for bus in buses:
        pci = os.path.dirname(os.path.realpath(os.path.join(root, bus, "device")))
        if _read(os.path.join(root, bus, "name")) == BUS_NAME and \
                (_read(os.path.join(pci, "subsystem_vendor")), _read(os.path.join(pci, "subsystem_device"))) == CARD:
            return "/dev/" + bus
    return None


def reapply(chip):
    """Write each of SETTINGS that the chip has lost; returns the registers written."""
    wrote = []
    for reg, want in SETTINGS.items():
        if chip.read(reg) != want:
            chip.write(reg, want)
            wrote.append(reg)
    return wrote


class _SMBusArgs(ctypes.Structure):  # struct i2c_smbus_ioctl_data
    _fields_ = [("read_write", ctypes.c_uint8), ("command", ctypes.c_uint8),
                ("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]


class Chip:
    """The chip over SMBus byte-data transfers, the same transactions as i2cget/i2cset."""
    def __init__(self, fd):
        self.fd = fd

    def _xfer(self, rw, reg, value=0):
        data = (ctypes.c_uint8 * 34)(value)                   # union i2c_smbus_data
        fcntl.ioctl(self.fd, I2C_SMBUS, _SMBusArgs(rw, reg, I2C_SMBUS_BYTE_DATA, ctypes.addressof(data)))
        return data[0]

    def read(self, reg):
        return self._xfer(I2C_SMBUS_READ, reg)

    def write(self, reg, value):
        self._xfer(I2C_SMBUS_WRITE, reg, value)


def fix_card(root=SYSFS):
    """Re-apply SETTINGS on the Nitro+ when it is present, logging to stderr; returns the registers written.

    Never raises: the daemon treats any OSError as a lost OpenRGB connection.
    """
    try:
        path = find_bus(root)
        if path is None:
            return []
        fd = os.open(path, os.O_RDWR)
        try:
            fcntl.ioctl(fd, I2C_SLAVE, ADDR)
            wrote = reapply(Chip(fd))
        finally:
            os.close(fd)
    except OSError as e:
        print(f"Nitro+ LED chip: {e}", file=sys.stderr)
        return []
    if wrote:
        print("restored Nitro+ LED registers " + ", ".join(f"0x{r:02X}" for r in wrote), file=sys.stderr)
    return wrote
