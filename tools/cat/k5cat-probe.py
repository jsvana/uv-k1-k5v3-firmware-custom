#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyserial>=3.5",
# ]
# ///
"""Raw probe: send 0x0514 handshake, dump whatever bytes (if any) come back."""
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

if __name__ == '__main__':
    port = sys.argv[1]
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 38400
    ser = serial.Serial(port, baud, timeout=0.1)
    pkt = frame(0x0514, struct.pack('<I', int(time.time()) & 0xFFFFFFFF))
    print(f"TX ({len(pkt)} bytes @ {baud} baud): {pkt.hex(' ')}")
    ser.reset_input_buffer()
    ser.write(pkt)
    ser.flush()
    time.sleep(0.5)
    rx = ser.read(256)
    print(f"RX ({len(rx)} bytes): {rx.hex(' ') if rx else '(nothing)'}")
