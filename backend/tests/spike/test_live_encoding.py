"""Spike: prove the incremental live MP3 encoding contract."""

from io import BytesIO
from time import perf_counter

import av
import numpy as np


def test_incremental_float32_16khz_frames_round_trip_to_mp3() -> None:
    output = av.open("pipe:", mode="w", format="mp3")
    stream = output.add_stream("mp3", rate=44_100)
    stream.layout = "mono"
    stream.bit_rate = 48_000
    resampler = av.audio.resampler.AudioResampler(format="fltp", layout="mono", rate=44_100)
    packets: list[bytes] = []
    latencies: list[float] = []
    for _index in range(20):
        samples = np.sin(np.arange(1600, dtype=np.float32) * (2 * np.pi * 1000 / 16_000))
        frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = 16_000
        started = perf_counter()
        for resampled in resampler.resample(frame):
            packets.extend(bytes(packet) for packet in stream.encode(resampled))
        latencies.append(perf_counter() - started)
    for resampled in resampler.resample(None):
        packets.extend(bytes(packet) for packet in stream.encode(resampled))
    packets.extend(bytes(packet) for packet in stream.encode())
    output.close()
    encoded = b"".join(packets)
    assert encoded
    assert max(latencies) < 0.05
    decoder = av.open(BytesIO(encoded), mode="r", format="mp3")
    decoded = sum(frame.samples for frame in decoder.decode(audio=0))
    decoder.close()
    assert decoded >= 20 * 1600 * 44_100 // 16_000 - 4410
