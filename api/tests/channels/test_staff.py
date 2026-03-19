from types import SimpleNamespace

from app.channels.staff import (
    StaffResolver,
    collect_staff_display_names,
    collect_trusted_staff_ids,
)


def test_collect_trusted_staff_ids_ignores_support_nicknames() -> None:
    settings = SimpleNamespace(
        SUPPORT_AGENT_NICKNAMES=["alice", "bob"],
        TRUSTED_STAFF_IDS=["@alice:matrix.org", "@bob:matrix.org"],
        BISQ2_STAFF_PROFILE_IDS=["staff-profile-1"],
    )

    assert collect_trusted_staff_ids(settings, channel_id="matrix") == [
        "@alice:matrix.org",
        "@bob:matrix.org",
    ]


def test_collect_trusted_staff_ids_prefers_bisq2_profile_ids_for_bisq_channel() -> None:
    settings = SimpleNamespace(
        TRUSTED_STAFF_IDS=["@alice:matrix.org"],
        BISQ2_STAFF_PROFILE_IDS=["staff-profile-1", "staff-profile-2"],
    )

    assert collect_trusted_staff_ids(settings, channel_id="bisq2") == [
        "@alice:matrix.org",
        "staff-profile-1",
        "staff-profile-2",
    ]


def test_collect_staff_display_names_only_uses_nicknames() -> None:
    settings = SimpleNamespace(SUPPORT_AGENT_NICKNAMES=" alice, bob , ")
    assert collect_staff_display_names(settings) == ["alice", "bob"]


def test_staff_resolver_exposes_trusted_ids_and_display_names() -> None:
    resolver = StaffResolver(
        trusted_staff_ids=["@Alice:matrix.org", "staff-profile-1"],
        display_names=["Alice", "Support Team"],
    )

    assert resolver.is_staff("@alice:matrix.org")
    assert resolver.is_staff("STAFF-PROFILE-1")
    assert not resolver.is_staff("Support Team")
    assert resolver.get_display_names() == {"Alice", "Support Team"}
