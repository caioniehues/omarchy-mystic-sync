import contextlib, io, os, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import glow

OEM = "AMDGPU DM i2c OEM bus"


def fake_bus(root, bus, name, subsystem=None):
    """Lay out /sys/class/i2c-dev/<bus> like the kernel: name, and device -> the adapter under its PCI device."""
    cls = os.path.join(root, "class", bus)
    os.makedirs(cls)
    with open(os.path.join(cls, "name"), "w") as f:
        f.write(name + "\n")
    if subsystem:
        pci = os.path.join(root, "devices", bus + "-gpu")
        os.makedirs(os.path.join(pci, bus))
        for key, val in zip(("subsystem_vendor", "subsystem_device"), subsystem):
            with open(os.path.join(pci, key), "w") as f:
                f.write(val + "\n")
        os.symlink(os.path.join(pci, bus), os.path.join(cls, "device"))
    return os.path.join(root, "class")


class FindBus(unittest.TestCase):
    def test_finds_the_nitro_oem_bus(self):
        with tempfile.TemporaryDirectory() as root:
            fake_bus(root, "i2c-3", "AMDGPU DM aux hw bus 0", ("0x1da2", "0xd475"))
            sysfs = fake_bus(root, "i2c-7", OEM, ("0x1da2", "0xd475"))
            self.assertEqual(glow.find_bus(sysfs), "/dev/i2c-7")

    def test_ignores_another_cards_oem_bus(self):
        with tempfile.TemporaryDirectory() as root:
            sysfs = fake_bus(root, "i2c-4", OEM, ("0x1da2", "0xe471"))     # a different Sapphire model
            self.assertIsNone(glow.find_bus(sysfs))

    def test_bus_without_a_pci_device_is_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            sysfs = fake_bus(root, "i2c-0", OEM)
            self.assertIsNone(glow.find_bus(sysfs))

    def test_no_i2c_dev_means_no_card(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(glow.find_bus(os.path.join(root, "i2c-dev")))


class FakeChip:
    def __init__(self, regs):
        self.regs, self.writes = dict(regs), []

    def read(self, reg):
        return self.regs.get(reg, 0)

    def write(self, reg, value):
        self.regs[reg] = value
        self.writes.append((reg, value))


class Reapply(unittest.TestCase):
    def test_restores_what_a_power_loss_reset(self):
        chip = FakeChip({0x27: 6, 0x3E: 0})
        self.assertEqual(glow.reapply(chip), [0x27, 0x3E])
        self.assertEqual(chip.regs, {0x27: 36, 0x3E: 100})

    def test_leaves_a_correct_chip_alone(self):
        chip = FakeChip({0x27: 36, 0x3E: 100})
        self.assertEqual(glow.reapply(chip), [])
        self.assertEqual(chip.writes, [])

    def test_writes_only_the_lost_setting(self):
        chip = FakeChip({0x27: 36, 0x3E: 0})
        self.assertEqual(glow.reapply(chip), [0x3E])
        self.assertEqual(chip.writes, [(0x3E, 100)])


class FixCard(unittest.TestCase):
    def test_a_bus_error_is_logged_not_raised(self):
        # the daemon treats any OSError as a lost OpenRGB connection, so fix_card must swallow its own
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as root, contextlib.redirect_stderr(err), \
                mock.patch.object(glow, "find_bus", return_value=os.path.join(root, "i2c-99")):
            self.assertEqual(glow.fix_card(), [])
        self.assertIn("Nitro+ LED chip", err.getvalue())


if __name__ == "__main__":
    unittest.main()
