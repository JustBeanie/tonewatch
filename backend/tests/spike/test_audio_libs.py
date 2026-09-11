"""M0.6 codec and sounddevice compatibility spike."""

import io
import logging
import sys
from importlib import import_module
from typing import Any, cast

import av
import numpy as np


def _round_trip(codec: str) -> None:
    samples = (0.2 * np.sin(2 * np.pi * 440 * np.arange(16_000) / 16_000)).astype(np.float32)
    output = io.BytesIO()
    container = av.open(output, mode="w", format="mp3" if codec == "mp3" else "ogg")
    stream = cast("Any", container.add_stream(codec, rate=16_000))
    frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="flt", layout="mono")
    frame.sample_rate = 16_000
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    decoded = cast("Any", av.open(io.BytesIO(output.getvalue())))
    assert (
        sum(cast("Any", frame).samples for packet in decoded.demux() for frame in packet.decode())
        > 0
    )


def test_pyav_mp3_and_opus_and_sounddevice() -> None:
    """Both planned codecs round-trip and PortAudio imports."""
    assert import_module("sounddevice") is not None
    message = f"PyAV version={av.__version__}; FFmpeg libraries={av.library_versions}\n"
    LOGGER.info(message.rstrip())
    sys.stderr.write(message)
    _round_trip("mp3")
    _round_trip("opus")


LOGGER = logging.getLogger(__name__)
