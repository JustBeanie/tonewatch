"""Global test safeguards against accidentally opening host audio hardware."""

from collections.abc import Iterator

import pytest

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
