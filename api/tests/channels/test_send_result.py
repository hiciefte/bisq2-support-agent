from app.channels.models import SendResult


def test_send_result_bool_behavior() -> None:
    ok = SendResult(sent=True, external_message_id="evt-1", editable=True)
    failed = SendResult(sent=False, error="network")

    assert bool(ok) is True
    assert bool(failed) is False
