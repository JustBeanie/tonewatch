"""Global test safeguards against accidentally opening host audio hardware."""

from collections.abc import Iterator

import pytest

from tonewatch.integrations.zeroconf import ZeroconfAdvertiser
from tonewatch.sources import soundcard


@pytest.fixture(autouse=True)
def no_real_audio_devices(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Make hardware access opt-in through an explicit pytest marker."""
    if request.node.get_closest_marker("allow_real_audio") is not None:
        yield
        return

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr(soundcard.sd, "InputStream", refuse)
    monkeypatch.setattr(soundcard.sd, "RawInputStream", refuse)
    yield


class ZeroconfTestSafetyError(AssertionError):
    """Raised when a test starts zeroconf without opting in."""

    def __init__(self) -> None:
        super().__init__("real zeroconf requires the real_zeroconf marker")


@pytest.fixture(autouse=True)
def forbid_unmarked_zeroconf(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent tests from opening a host mDNS socket accidentally."""
    if request.node.get_closest_marker("real_zeroconf") is not None:
        return

    original_start = ZeroconfAdvertiser.start

    async def fail_if_enabled(advertiser: ZeroconfAdvertiser) -> None:
        if advertiser.enabled:
            raise ZeroconfTestSafetyError
        await original_start(advertiser)

    monkeypatch.setattr(ZeroconfAdvertiser, "start", fail_if_enabled)
