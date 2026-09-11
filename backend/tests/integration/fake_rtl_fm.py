"""Deterministic rtl_fm stand-in used by the subprocess integration test."""

import math
import os
import struct
import sys
from pathlib import Path


def main() -> None:
    """Write a 1 kHz signed PCM tone and record the received arguments."""
    argv_log = os.environ["TONEWATCH_FAKE_RTL_ARGV"]
    with Path(argv_log).open("a", encoding="utf-8") as log:
        log.write("\0".join(sys.argv[1:]) + "\n")
    count = int(os.environ.get("TONEWATCH_FAKE_RTL_SAMPLES", "3200"))
    rate = 16_000
    for start in range(0, count, 256):
        values = [
            struct.pack("<h", int(0.5 * 32767 * math.sin(2 * math.pi * 1000 * i / rate)))
            for i in range(start, min(start + 256, count))
        ]
        sys.stdout.buffer.write(b"".join(values))
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
