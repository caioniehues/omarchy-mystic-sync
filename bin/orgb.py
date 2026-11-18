"""Minimal OpenRGB SDK client (stdlib only): enough to find controllers, resize zones and push colours.

Protocol: https://gitlab.com/CalcProgrammer1/OpenRGB/-/blob/master/Documentation/OpenRGBSDK.md
Packet = header ("ORGB", device_index u32, packet_id u32, payload_size u32) + payload, little-endian.
"""
import socket, struct

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
RESIZEZONE = 1000
UPDATEZONELEDS = 1051
SETCUSTOMMODE = 1100
REQUEST_LOAD_PROFILE = 152
CLIENT_PROTOCOL = 4


class OpenRGB:
    def __init__(self, host="127.0.0.1", port=6742, name="mystic-sync", timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._send(0, REQUEST_PROTOCOL_VERSION, struct.pack("<I", CLIENT_PROTOCOL))
        server = struct.unpack("<I", self._recv(REQUEST_PROTOCOL_VERSION))[0]
        self.protocol = min(server, CLIENT_PROTOCOL)
        self._send(0, SET_CLIENT_NAME, name.encode() + b"\0")

    def close(self):
        self.sock.close()

    def _send(self, dev, pid, payload=b""):
        self.sock.sendall(b"ORGB" + struct.pack("<III", dev, pid, len(payload)) + payload)

    def _exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("OpenRGB server closed the connection")
            buf += chunk
        return buf

    def _recv(self, want):
        while True:
            hdr = self._exact(16)
            if hdr[:4] != b"ORGB":
                raise ConnectionError("bad OpenRGB packet header")
            _, pid, size = struct.unpack("<III", hdr[4:])
            body = self._exact(size)
            if pid == want:
                return body            # other packets (e.g. device-list-updated notices) are skipped

    def count(self):
        self._send(0, REQUEST_CONTROLLER_COUNT)
        return struct.unpack("<I", self._recv(REQUEST_CONTROLLER_COUNT))[0]

    def name(self, dev):
        """Controller name: blob = data_size u32, type i32, name (u16 len + bytes incl. NUL)."""
        self._send(dev, REQUEST_CONTROLLER_DATA, struct.pack("<I", self.protocol))
        blob = self._recv(REQUEST_CONTROLLER_DATA)
        n = struct.unpack_from("<H", blob, 8)[0]
        return blob[10:10 + n].rstrip(b"\0").decode(errors="replace")

    def find(self, needle):
        for i in range(self.count()):
            if needle.lower() in self.name(i).lower():
                return i
        return None

    def custom_mode(self, dev):
        """Switch to the controller's Direct/custom mode so per-LED updates apply live."""
        self._send(dev, SETCUSTOMMODE)

    def resize_zone(self, dev, zone, size):
        self._send(dev, RESIZEZONE, struct.pack("<ii", zone, size))

    def load_profile(self, name):
        """Apply a saved OpenRGB profile (protocol >= 2)."""
        self._send(0, REQUEST_LOAD_PROFILE, name.encode() + b"\0")

    def ping(self):
        """Round trip, so earlier fire-and-forget packets are known to have reached the server."""
        return self.count()

    def zone_colors(self, dev, zone, colors):
        """colors: list of (r, g, b)."""
        body = struct.pack("<IH", zone, len(colors)) + b"".join(struct.pack("<BBBx", *c) for c in colors)
        self._send(dev, UPDATEZONELEDS, struct.pack("<I", len(body) + 4) + body)
