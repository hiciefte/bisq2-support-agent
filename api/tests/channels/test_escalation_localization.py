from app.channels.escalation_localization import render_escalation_notice


def test_render_escalation_notice_web_german_capitalization():
    notice = render_escalation_notice(
        channel_id="web",
        escalation_id=1,
        support_handle="support",
        language_code="de",
    )

    assert notice.startswith("Ich markiere das")
    assert "Teammitglied" in notice
    assert "Details" in notice
    assert "Kürze" in notice


def test_render_escalation_notice_matrix_german_capitalization():
    notice = render_escalation_notice(
        channel_id="matrix",
        escalation_id=1,
        support_handle="support",
        language_code="de",
    )

    assert notice.startswith("Das braucht die Aufmerksamkeit")
    assert "Teammitglieds" in notice
    assert "Raum" in notice
