"""Route support reports by the affected app, not a working comparator."""

from unittest.mock import Mock

import pytest
from app.services.rag.document_retriever import (
    DocumentRetriever,
    _classify_query_protocol,
    is_bisq_version_comparison_query,
)
from app.services.rag.protocol_detector import ProtocolDetector

WINDOWS_INSTALLER_REPORT = (
    "On Windows, after an update and automatic restart while Bisq was open, "
    "Bisq closed after I entered the password and bisq.exe disappeared. "
    "Repair was not possible because the .exe was missing. Reinstalling now "
    "makes Windows Installer ask for main.msi. I have no other antivirus "
    "installed, Windows Security will not open, and other apps including "
    "Bisq 2 still run. Where should main.msi be?"
)


@pytest.mark.parametrize(
    "question,version,classification",
    [
        (WINDOWS_INSTALLER_REPORT, "Unknown", (False, False, False)),
        (
            "Bisq fails after the update, but Bisq 2 still runs.",
            "Unknown",
            (False, False, False),
        ),
        (
            "Bisq 1 crashes after the update, but Bisq 2 still runs.",
            "Bisq 1",
            (True, False, False),
        ),
        ("Bisq1 fails but Bisq2 works", "Bisq 1", (True, False, False)),
        ("Bisq2 fails but Bisq1 works", "Bisq 2", (False, True, False)),
        (
            "Bisq 1 works fine while Bisq 2 fails to open.",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "Bisq 2 fails to open. Bisq 1 connects just fine.",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "Bisq fails to open, but Bisq Easy still runs.",
            "Unknown",
            (False, False, False),
        ),
        (
            "Bisq Easy fails to open, but Bisq 1 works.",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "Bisq 2 does not work fine after the update.",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "Bisq 1 crashes and Bisq 2 does not work fine either.",
            "Unknown",
            (True, True, True),
        ),
        (
            "Bisq 1 fails but Bisq 2 works only sometimes.",
            "Unknown",
            (True, True, True),
        ),
        (
            "Bisq 1 fails but Bisq 2 still works only sometimes.",
            "Unknown",
            (True, True, True),
        ),
        (
            "Bisq 1 fails but Bisq 2 does not work.",
            "Unknown",
            (True, True, True),
        ),
        (
            "Bisq2 starts, then crashes. How can I fix this?",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "Bisq 2 works fine, but its installer failed.",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "Bisq 2 works fine. Its installer failed. What should I check?",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "I am not using Bisq 2. Bisq crashes after the update.",
            "Unknown",
            (False, False, False),
        ),
        (
            "I am not using Bisq 1. My Bisq 2 update failed.",
            "Bisq 2",
            (False, True, False),
        ),
        ("How do I update Bisq 2?", "Bisq 2", (False, True, False)),
        ("How do I back up Bisq 1?", "Bisq 1", (True, False, False)),
        (
            "Bisq 2 runs fine. How do I update it?",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "My installer failed. Why does Bisq 2 still run?",
            "Bisq 2",
            (False, True, False),
        ),
        (
            "Compare Bisq 1 which fails to open and Bisq 2 which works fine.",
            "Unknown",
            (True, True, True),
        ),
    ],
)
@pytest.mark.asyncio
async def test_detector_and_retrieval_agree_on_product_evidence(
    question, version, classification
):
    detector = ProtocolDetector()
    assert detector.detect_version_from_text(question)[0] == version
    assert (await detector.detect_version(question, []))[0] == version
    assert _classify_query_protocol(question) == classification
    assert is_bisq_version_comparison_query(question) is classification[2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "affected,working", [("Bisq 1", "Bisq 2"), ("Bisq 2", "Bisq 1")]
)
@pytest.mark.parametrize("working_first", [False, True])
@pytest.mark.parametrize("symptom", ["hangs at startup", "shows 0 peers", "times out"])
async def test_startup_symptoms_keep_affected_product(
    affected, working, working_first, symptom
):
    clauses = [f"{affected} {symptom}", f"{working} works fine"]
    if working_first:
        clauses.reverse()
    question = ", but ".join(clauses) + "."
    detector = ProtocolDetector()
    assert detector.detect_version_from_text(question)[0] == affected
    assert (await detector.detect_version(question, []))[0] == affected
    assert _classify_query_protocol(question) == (
        affected == "Bisq 1",
        affected == "Bisq 2",
        False,
    )
    assert not is_bisq_version_comparison_query(question)


@pytest.mark.parametrize(
    "excluded,detected_version",
    [
        ("Bisq 1", "Bisq 1"),
        ("Bisq 1", "multisig_v1"),
        ("Bisq 2", "Bisq 2"),
        ("Bisq 2", "bisq_easy"),
    ],
)
def test_retrieval_fallback_does_not_restore_explicitly_excluded_product(
    excluded, detected_version
):
    assert _classify_query_protocol(
        f"I am not using {excluded}. I cannot connect.", detected_version
    ) == (False, False, False)


@pytest.mark.parametrize("with_scores", [False, True])
def test_frozen_installer_report_retrieves_all_product_scopes(with_scores):
    backend = Mock()
    backend.retrieve.return_value = []
    backend.retrieve_with_scores.return_value = []
    backend.retrieve_semantic_with_scores.return_value = []
    retriever = DocumentRetriever(backend)
    if with_scores:
        retriever.retrieve_with_scores(WINDOWS_INSTALLER_REPORT, "Unknown")
        calls = backend.retrieve_with_scores.call_args_list
    else:
        retriever.retrieve_with_version_priority(WINDOWS_INSTALLER_REPORT, "Unknown")
        calls = backend.retrieve.call_args_list
    assert {
        call.kwargs["filter_dict"]["protocol"]
        for call in calls
        if call.kwargs.get("filter_dict")
    } == {"all", "multisig_v1", "bisq_easy"}


@pytest.mark.asyncio
async def test_working_comparator_in_history_does_not_establish_affected_app():
    detector = ProtocolDetector()
    version, _, _ = await detector.detect_version(
        "Where should main.msi be?",
        [{"role": "user", "content": WINDOWS_INSTALLER_REPORT}],
    )
    assert version == "Unknown"


@pytest.mark.asyncio
async def test_explicit_affected_app_in_history_survives_working_comparator():
    detector = ProtocolDetector()
    version, _, _ = await detector.detect_version(
        WINDOWS_INSTALLER_REPORT,
        [{"role": "user", "content": "My Bisq 1 install failed."}],
    )
    assert version == "Bisq 1"
    assert _classify_query_protocol(WINDOWS_INSTALLER_REPORT, version) == (
        True,
        False,
        False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("negation_in_history", [False, True])
async def test_newer_exclusion_does_not_revive_older_product(negation_in_history):
    history = [{"role": "user", "content": "I use Bisq 2."}]
    question = "I am not using Bisq 2. Where is the installer?"
    if negation_in_history:
        history.append({"role": "user", "content": question})
        question = "Where is the installer?"
    version, _, _ = await ProtocolDetector().detect_version(question, history)
    assert version == "Unknown"


@pytest.mark.asyncio
async def test_exclusion_preserves_explicit_other_product_in_history():
    history = [
        {"role": "user", "content": "My Bisq 1 install failed."},
        {"role": "user", "content": "I am not using Bisq 2."},
    ]
    version, _, _ = await ProtocolDetector().detect_version(
        "Where is the installer?", history
    )
    assert version == "Bisq 1"
