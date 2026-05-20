from __future__ import annotations

import asyncio

import pytest

from rig_relay.events.dispatcher import EventDispatcher

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.concurrency]


@pytest.fixture
def dispatcher() -> EventDispatcher:
    return EventDispatcher()


@pytest.mark.asyncio
async def test_subscribed_handler_receives_matching_event(dispatcher: EventDispatcher):
    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    dispatcher.subscribe("bridge.", handler)
    event = {
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "payload": {},
    }
    await dispatcher.publish(event)

    assert len(received) == 1
    assert received[0]["event_id"] == "evt_001"


@pytest.mark.asyncio
async def test_unrelated_handler_does_not_receive_non_matching_event(
    dispatcher: EventDispatcher,
):
    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    dispatcher.subscribe("bridge.", handler)
    event = {
        "event_id": "evt_001",
        "event_type": "tool.invocation.completed",
        "payload": {},
    }
    await dispatcher.publish(event)

    assert received == []


@pytest.mark.asyncio
async def test_consumer_failure_is_isolated(dispatcher: EventDispatcher):
    received: list[dict] = []

    async def failing_handler(event: dict) -> None:
        raise RuntimeError("handler crash")

    async def good_handler(event: dict) -> None:
        received.append(event)

    dispatcher.subscribe("bridge.", failing_handler)
    dispatcher.subscribe("bridge.", good_handler)
    event = {
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "payload": {},
    }
    await dispatcher.publish(event)

    assert len(received) == 1
    assert received[0]["event_id"] == "evt_001"


@pytest.mark.asyncio
async def test_recursive_publish_guard_same_event_id(dispatcher: EventDispatcher):
    received_count = 0

    async def handler(event: dict) -> None:
        nonlocal received_count
        received_count += 1
        await dispatcher.publish(event)

    dispatcher.subscribe("bridge.", handler)
    event = {
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "payload": {},
    }
    await dispatcher.publish(event)

    assert received_count == 1


@pytest.mark.asyncio
async def test_drain_cancels_pending_tasks(dispatcher: EventDispatcher):
    received: list[dict] = []

    async def slow_handler(event: dict) -> None:
        await asyncio.sleep(10)
        received.append(event)

    dispatcher.subscribe("bridge.", slow_handler)
    event = {
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "payload": {},
    }

    publish_task = asyncio.create_task(dispatcher.publish(event))
    await asyncio.sleep(0.1)
    await dispatcher.drain()
    try:
        await publish_task
    except asyncio.CancelledError:
        pass

    assert received == []


@pytest.mark.asyncio
async def test_publish_to_no_subscribers_does_not_error(dispatcher: EventDispatcher):
    event = {
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "payload": {},
    }
    await dispatcher.publish(event)


@pytest.mark.asyncio
async def test_unsubscribe_removes_handler(dispatcher: EventDispatcher):
    received: list[dict] = []

    async def handler(event: dict) -> None:
        received.append(event)

    dispatcher.subscribe("bridge.", handler)
    dispatcher.unsubscribe("bridge.", handler)

    event = {
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "payload": {},
    }
    await dispatcher.publish(event)

    assert received == []


@pytest.mark.asyncio
async def test_multiple_handlers_receive_same_event(dispatcher: EventDispatcher):
    received_handlers: list[str] = []

    async def handler_a(event: dict) -> None:
        received_handlers.append("a")

    async def handler_b(event: dict) -> None:
        received_handlers.append("b")

    dispatcher.subscribe("bridge.", handler_a)
    dispatcher.subscribe("bridge.", handler_b)
    event = {
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "payload": {},
    }
    await dispatcher.publish(event)

    assert "a" in received_handlers
    assert "b" in received_handlers
