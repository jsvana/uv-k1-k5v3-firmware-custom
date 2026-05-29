#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyserial>=3.5",
# ]
# ///
"""Minimal client for the F4HWN Fusion CAT extensions."""
import struct
import sys
import time
import serial

OBFUSCATION = bytes([
    0x16, 0x6C, 0x14, 0xE6, 0x2E, 0x91, 0x0D, 0x40,
    0x21, 0x35, 0xD5, 0x40, 0x13, 0x03, 0xE9, 0x80,
])

def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def obfuscate(payload: bytes) -> bytes:
    return bytes(b ^ OBFUSCATION[i % 16] for i, b in enumerate(payload))

def frame(cmd_id: int, body: bytes) -> bytes:
    payload = struct.pack('<HH', cmd_id, len(body)) + body
    obf = obfuscate(payload)
    crc = crc16_xmodem(payload)
    return b'\xAB\xCD' + struct.pack('<H', len(obf)) + obf + struct.pack('<H', crc) + b'\xDC\xBA'

def read_frame(ser, timeout=1.0) -> tuple[int, bytes]:
    deadline = time.time() + timeout
    buf = bytearray()
    while time.time() < deadline:
        b = ser.read(1)
        if not b:
            continue
        buf += b
        # Find start marker
        i = buf.find(b'\xAB\xCD')
        if i < 0:
            continue
        if len(buf) < i + 4:
            continue
        size = struct.unpack('<H', buf[i+2:i+4])[0]
        total_len = i + 4 + size + 4  # header + payload + crc + footer
        if len(buf) < total_len:
            continue
        if buf[total_len-2:total_len] != b'\xDC\xBA':
            buf = buf[i+1:]
            continue
        obf_payload = buf[i+4:i+4+size]
        payload = obfuscate(bytes(obf_payload))
        cmd_id, body_size = struct.unpack('<HH', payload[:4])
        return cmd_id, payload[4:4+body_size]
    raise TimeoutError("no frame")

class K5Cat:
    def __init__(self, port: str, baud: int = 38400):
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.timestamp = 0

    def handshake(self):
        # CMD 0x0514: send a 4-byte timestamp (host's choice), get back version + challenge
        ts = int(time.time()) & 0xFFFFFFFF
        self.ser.write(frame(0x0514, struct.pack('<I', ts)))
        cmd, body = read_frame(self.ser)
        assert cmd == 0x0515, f"unexpected reply 0x{cmd:04X}"
        version = body[:16].rstrip(b'\x00').decode('ascii', errors='replace')
        # The firmware echoes back a usable timestamp for subsequent commands.
        # In stock K5 protocol, the host's own timestamp is what gets used.
        self.timestamp = ts
        return version

    def read_rssi(self):
        self.ser.write(frame(0x0527, b''))
        cmd, body = read_frame(self.ser)
        rssi, ex_noise, glitch = struct.unpack('<HBB', body)
        # BK4819 RSSI register: dBm = (rssi >> 1) - 160
        dbm = (rssi >> 1) - 160
        return dbm, rssi, ex_noise, glitch

    def read_bk_reg(self, reg: int) -> int:
        self.ser.write(frame(0x0601, struct.pack('<B', reg)))
        cmd, body = read_frame(self.ser)
        r, v = struct.unpack('<BH', body)
        return v

    def write_bk_reg(self, reg: int, value: int):
        self.ser.write(frame(0x0602, struct.pack('<BH', reg, value)))
        # CMD 0x0602 doesn't reply.

    def set_vfo_freq(self, vfo: int, freq_hz: int):
        freq_x10 = freq_hz // 10
        self.ser.write(frame(0x0603, struct.pack('<BI', vfo, freq_x10)))
        cmd, body = read_frame(self.ser)
        return body[0]  # 0 = ok

    def get_vfo_freq(self, vfo: int):
        self.ser.write(frame(0x0604, struct.pack('<B', vfo)))
        cmd, body = read_frame(self.ser)
        v, mod, bw, _, rx, tx = struct.unpack('<BBBBII', body)
        return {'vfo': v, 'modulation': mod, 'bw': bw, 'rx_hz': rx*10, 'tx_hz': tx*10}

    def ptt(self, key_down: bool):
        self.ser.write(frame(0x0605, struct.pack('<B', 1 if key_down else 0)))
        cmd, body = read_frame(self.ser)
        return body[0]

if __name__ == '__main__':
    port = sys.argv[1] if len(sys.argv) > 1 else '/dev/cu.usbmodem*'
    cat = K5Cat(port)
    print("Firmware:", cat.handshake())
    print("RSSI:", cat.read_rssi())
    print("VFO 0:", cat.get_vfo_freq(0))
    cat.set_vfo_freq(0, 146_520_000)  # call freq
    print("After set:", cat.get_vfo_freq(0))
