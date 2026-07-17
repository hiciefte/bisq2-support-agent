from types import SimpleNamespace

from app.channels.runtime import ChannelRuntime
from app.channels.staff import (
    StaffResolver,
    collect_staff_display_names,
    collect_trusted_staff_ids,
    resolve_channel_staff_resolver,
    staff_resolver_service_key,
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
        "staff-profile-1",
        "staff-profile-2",
    ]


def test_bisq_staff_ids_preserve_case_and_resolve_exactly() -> None:
    settings = SimpleNamespace(
        BISQ2_STAFF_PROFILE_IDS=["Profile-X"],
    )

    configured = collect_trusted_staff_ids(settings, channel_id="bisq2")
    resolver = StaffResolver(configured, case_sensitive=True)

    assert configured == ["Profile-X"]
    assert resolver.is_staff("Profile-X") is True
    assert resolver.is_staff("profile-x") is False
    assert resolver.is_staff(" Profile-X ") is False


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


def test_channel_staff_resolvers_are_namespaced_and_isolated() -> None:
    runtime = ChannelRuntime(settings=SimpleNamespace())
    bisq_resolver = StaffResolver(["bisq-profile-1"])
    matrix_resolver = StaffResolver(["@staff:matrix.org"])
    runtime.register(staff_resolver_service_key("bisq2"), bisq_resolver)
    runtime.register(staff_resolver_service_key("matrix"), matrix_resolver)

    resolved_bisq = resolve_channel_staff_resolver(runtime, "bisq2")
    resolved_matrix = resolve_channel_staff_resolver(runtime, "matrix")

    assert resolved_bisq is bisq_resolver
    assert resolved_matrix is matrix_resolver
    assert resolved_bisq.is_staff("bisq-profile-1")
    assert not resolved_bisq.is_staff("@staff:matrix.org")
    assert resolved_matrix.is_staff("@staff:matrix.org")
    assert not resolved_matrix.is_staff("bisq-profile-1")
