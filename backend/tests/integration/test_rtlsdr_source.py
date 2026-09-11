"""Real asyncio subprocess integration test for the RTL-SDR source."""

import asyncio
import os
import sys
from pathlib import Path

import numpy as np

from tonewatch.config.models import RtlSdrSource as RtlConfig
from tonewatch.sources.rtlsdr import RtlSdrSource


def test_rtlsdr_fake_process_restarts_without_shell(tmp_path: Path) -> None:
    log = tmp_path / "argv.log"
    fake = Path(__file__).with_name("fake_rtl_fm.py")
    config = RtlConfig(id="rtl", name="rtl", freq_hz=154000000, gain=12, ppm=3, squelch=4)
    source = RtlSdrSource(
        config,
        executable=sys.executable,
        prefix_args=(str(fake),),
        chunk_size=1600,
        sleep=lambda _: asyncio.sleep(0),
    )

    async def run() -> list[np.ndarray]:
        old_log = os.environ.get("TONEWATCH_FAKE_RTL_ARGV")
        old_count = os.environ.get("TONEWATCH_FAKE_RTL_SAMPLES")
        os.environ["TONEWATCH_FAKE_RTL_ARGV"] = str(log)
        os.environ["TONEWATCH_FAKE_RTL_SAMPLES"] = "3200"
        try:
            await source.open()
            chunks: list[np.ndarray] = []
            async for frame in source:
                chunks.append(frame.samples)
                if log.is_file() and len(log.read_text(encoding="utf-8").splitlines()) >= 2:
                    await source.close()
                    break
            return chunks
        finally:
            if old_log is None:
                os.environ.pop("TONEWATCH_FAKE_RTL_ARGV", None)
            else:
                os.environ["TONEWATCH_FAKE_RTL_ARGV"] = old_log
            if old_count is None:
                os.environ.pop("TONEWATCH_FAKE_RTL_SAMPLES", None)
            else:
                os.environ["TONEWATCH_FAKE_RTL_SAMPLES"] = old_count

    chunks = asyncio.run(run())
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 2
    assert all(
        item in lines[0].split("\0") for item in ("-M", "fm", "-r", "16000", "-p", "3", "-l", "4")
    )
    assert source.last_process is not None and source.last_process.returncode is not None
    signal = np.concatenate(chunks)
    crossings = np.flatnonzero(np.diff(np.signbit(signal)))
    frequency = crossings.size * 16_000 / (2 * signal.size)
    assert abs(frequency - 1000) < 5
