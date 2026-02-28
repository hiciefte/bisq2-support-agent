from types import SimpleNamespace

import pytest
from app.channels.delivery_planner import DeliveryMode, DeliveryPlanner


@pytest.mark.unit
def test_planner_uses_single_delivery_for_non_stream_responses():
    channel = SimpleNamespace(send_message=lambda target, message: True)
    response = SimpleNamespace(answer="final", stream=None)

    plan = DeliveryPlanner().plan(channel=channel, response=response)

    assert plan.mode == DeliveryMode.SINGLE


@pytest.mark.unit
def test_planner_prefers_native_streaming_transport_when_available():
    channel = SimpleNamespace(
        send_message=lambda target, message: True,
        send_streaming_message=lambda target, response: True,
    )
    response = SimpleNamespace(answer="", stream=iter(["a", "b"]))

    plan = DeliveryPlanner().plan(channel=channel, response=response)

    assert plan.mode == DeliveryMode.STREAM_NATIVE


@pytest.mark.unit
def test_planner_uses_buffered_streaming_without_native_transport():
    channel = SimpleNamespace(send_message=lambda target, message: True)
    response = SimpleNamespace(answer="", stream=iter(["a", "b"]))

    plan = DeliveryPlanner().plan(channel=channel, response=response)

    assert plan.mode == DeliveryMode.STREAM_BUFFERED
