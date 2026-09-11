"""M1.4 EventBus tests."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from tonewatch.events import EventBus, ToneDetected


def test_filtered_subscribers_and_oldest_drop() -> None:
    async def run() -> None:
        bus = EventBus(max_queue_size=2)
        subscriber = bus.subscribe(ToneDetected)

        def event() -> ToneDetected:
            return ToneDetected(uuid4(), "page", datetime.now(UTC))

        bus.publish(event())
        bus.publish(event())
        bus.publish(event())
        await asyncio.sleep(0)
        assert subscriber.dropped == 1
        assert await subscriber.__anext__()
        assert await subscriber.__anext__()

    asyncio.run(run())
