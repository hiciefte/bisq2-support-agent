"""
Test suite for data-driven classifier improvements.

Based on analysis of 2001 real Matrix questions.
Tests patterns discovered from production data that current classifier misses.

TDD Approach: Write failing tests first, then implement patterns.
"""

import pytest
from app.services.shadow_mode.classifiers import (
    MultiLayerClassifier,
    SpeakerRoleClassifier,
)

# Official Bisq support agents
OFFICIAL_SUPPORT_STAFF = [
    "darawhelan",
    "luis3672",
    "mwithm",
    "pazza83",
    "strayorigin",
    "suddenwhipvapor",
]


class TestUserHelpSeekingPatterns:
    """
    Test USER help-seeking patterns from real data.

    Analysis showed these patterns appear frequently but are missed:
    - "how can i/do i/to" → 133 instances (26.6% of user questions!)
    - "my [X] shows/says" → 49 instances (10%)
    - "what should i/we" → 30 instances (6%)
    - "anyone else/having" → 21 instances (4%)
    """

    def test_how_can_i_pattern(self):
        """Should detect 'how can i' help-seeking (133 real instances)."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "how can i check my bisq client version without launching it?",
            "how can i check if the DAO is synchronized?",
            "how can i restore my wallet from seed?",
            "how can you explain the buyer not having any btc",  # Edge case
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence > 0.6

    def test_how_do_i_pattern(self):
        """Should detect 'how do i' help-seeking (part of 133 instances)."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "how do i check my version?",
            "how do i restore from backup?",
            "how do i sync the DAO?",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence > 0.6

    def test_how_to_pattern(self):
        """Should detect 'how to' help-seeking (part of 133 instances)."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "how to message the seller first?",
            "how to check if DAO is synced?",
            "how to restore wallet?",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence > 0.6

    def test_my_shows_says_tells_pattern(self):
        """Should detect 'my [X] shows/says/tells' (49 real instances)."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "my zelle can only go up to 2,500 per day",
            "my bisq btc wallet balance vanishing",
            "my DAO shows unconfirmed",
            "my wallet says insufficient funds",
            "my client tells me to restart",
            "my offers display an error",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence > 0.6

    def test_what_should_i_we_pattern(self):
        """Should detect 'what should i/we' help-seeking (30 real instances)."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "what should I do if the father never approves the transaction?",
            "what should i do??",
            "what should we do?",
            "what should the buyer do in this case?",
            "what should the seller do?",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence > 0.6

    def test_anyone_variations_pattern(self):
        """Should detect 'anyone else/having/know' (21 real instances)."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "anyone having issues with DAO today?",
            "does anyone have any clue?",
            "anyone else experiencing this?",
            "anyone know how to fix this?",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence > 0.6


class TestUserActionWithAdversativeContext:
    """
    Test 'i [action]ed... but/and/however' pattern (50 real instances).

    Users report actions that FAILED - strong indicator of genuine problem.
    """

    def test_i_performed_but_pattern(self):
        """Should detect 'i performed... but' problem reports."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "I performed a BSQ Swap using Bisq 1, but I can't see any BSQ",
            "I performed the sync but it's still not working",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence >= 0.7  # Strong indicator

    def test_i_opened_made_sent_but_pattern(self):
        """Should detect 'i [action]ed... but' variations."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "I opened a trade to buy BTC and I made a mistake",
            "I sent the fund 3+ hours ago but the only activity...",
            "I made the payment, but seller hasn't confirmed",
            "I tried restarting but nothing changed",
            "I placed an order however it's stuck",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence >= 0.7


class TestGreetingBasedQuestions:
    """
    Test greeting-based questions (216 real instances - 43% of user questions!).

    Current pattern too restrictive - requires "?" OR specific keywords.
    Real data shows many greetings followed by problem statements.
    """

    def test_greeting_with_first_person_action(self):
        """Should detect greeting + 'i [action]' pattern."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        messages = [
            "Hello, I have a trade closing in a few minutes...",
            "Hi support, I have a trade closing...",
            "Hi, I am trying to withdraw two transactions",
            "Hello, I placed a Buy BTC order...",
            "Hey, I opened a trade and made a mistake",
            "Hi, I moved my bisq to another computer",
        ]

        for msg in messages:
            result = classifier.classify_message(msg, "@user:matrix.org")
            assert result["is_question"] is True, f"Should accept: {msg}"

    def test_greeting_with_problem_statement(self):
        """Should detect greeting + problem statement (no question mark)."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        messages = [
            "Hello! I read in docs you can sell bitcoins...",
            "Hi - is it common practice for sellers to take their time?",
            "Hi, my zelle can only go up to 2,500 per day",
        ]

        for msg in messages:
            result = classifier.classify_message(msg, "@user:matrix.org")
            assert result["is_question"] is True, f"Should accept: {msg}"


class TestRoleIdentificationPattern:
    """Test 'i am [the buyer/seller]' pattern (12 real instances)."""

    def test_i_am_the_buyer_seller(self):
        """Should detect users identifying their role in trade."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "I am the buyer, but I am late with the payment",
            "I am the seller and haven't received payment",
            "I am trying to withdraw two transactions",
            "I am getting an error message",
            "I am in need of a mediator",
            "I am stuck with this trade",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect user for: {msg}"
            assert confidence > 0.6


class TestStaffPatternFixes:
    """
    Test fixes for staff patterns that are too broad.

    These patterns catch USER questions when they should only catch STAFF:
    - "what" pattern → 7 staff instances (1.4%) but catches many users
    - "seed nodes" → catches users REPORTING errors
    - "you can/should" → 15.7% staff, 4% users (weak signal)
    """

    def test_what_pattern_should_not_catch_user_questions(self):
        """'what' pattern should NOT catch user help-seeking questions."""
        classifier = SpeakerRoleClassifier()

        # These are USER questions that current pattern wrongly catches
        user_questions = [
            "What is the name of the mediator for the trade?",
            "What's causing this error with my offers?",
            "what should I do if the father never approves?",
            "What can I do to fix this?",
        ]

        for msg in user_questions:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "user", f"Should detect USER (not staff) for: {msg}"

    def test_what_pattern_should_catch_staff_diagnostic(self):
        """'what' pattern SHOULD catch staff diagnostic questions."""
        classifier = SpeakerRoleClassifier()

        # These are STAFF diagnostic questions (should be caught)
        staff_questions = [
            "What version are you running?",
            "What error are you seeing?",
            "What market was the offer on?",
            "What problem did you encounter?",
        ]

        for msg in staff_questions:
            role, confidence = classifier.classify_speaker_role(
                msg, "@helper:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "staff", f"Should detect STAFF for: {msg}"

    def test_seed_nodes_in_error_report_is_user(self):
        """Users REPORTING errors with 'seed nodes' should be USER, not STAFF."""
        classifier = SpeakerRoleClassifier()

        # User reporting error message (contains "seed nodes")
        messages = [
            "I woke up to a message about seed nodes: 'We did not receive a filter object from seed nodes'",
            "I got this error: 'seed nodes are not responding'",
            "My client says something about seed nodes failing",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            # Should NOT be classified as staff
            assert (
                role != "staff" or confidence < 0.6
            ), f"Should not strongly classify as staff for: {msg}"

    def test_seed_nodes_in_explanation_is_staff(self):
        """Staff EXPLAINING seed nodes should be STAFF."""
        classifier = SpeakerRoleClassifier()

        messages = [
            "This means the seed nodes are having issues",
            "The seed nodes provide the initial connection",
            "Our seed nodes should be back online soon",
            "You can use alternative seed nodes with --seedNodes",
        ]

        for msg in messages:
            role, confidence = classifier.classify_speaker_role(
                msg, "@helper:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            assert role == "staff", f"Should detect staff for: {msg}"

    def test_you_can_should_lower_weight(self):
        """'you can/should' should have lower weight (appears in 4% of user questions)."""
        classifier = SpeakerRoleClassifier()

        # Users sometimes quote staff advice or suggest solutions
        user_with_advisory = [
            "you can actually change the payment amount?",  # Questioning
            "you should check with the seller first",  # User suggestion
        ]

        for msg in user_with_advisory:
            role, confidence = classifier.classify_speaker_role(
                msg, "@user:matrix.org", OFFICIAL_SUPPORT_STAFF
            )
            # Should not have HIGH confidence for staff detection
            if role == "staff":
                assert confidence < 0.8, f"Confidence too high for ambiguous: {msg}"


class TestRealWorldFailures:
    """
    Test the 15 manually selected questions that system missed.

    These are the ACTUAL failures from production data analysis.
    """

    def test_q1_version_check_without_launching(self):
        """Q1: 'how do i check my bisq client version without launching it?'"""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "how do i check my bisq client version without launching it?",
            "@mochicake:matrix.org",
        )

        assert result["is_question"] is True
        assert result["reason"] == "support_question"

    def test_q2_tor_connection_issue(self):
        """Q2: 'i keep having tor connection issue...'"""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "i keep having tor connection issue when i start up the bisq app on linux, is this problem happening to anyone else recently?",
            "@mochicake:matrix.org",
        )

        assert result["is_question"] is True

    def test_q3_mediator_name(self):
        """Q3: 'What is the name of the mediator for the trade?'"""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "What is the name of the mediator for the trade?",
            "@pantaneiro12:matrix.org",
        )

        assert result["is_question"] is True
        # Should NOT be classified as staff diagnostic

    def test_q4_need_mediator(self):
        """Q4: 'Hi – I am in need of a mediator for trade ID...'"""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "Hi – I am in need of a mediator for trade ID #98590482",
            "@papillion-12:matrix.org",
        )

        assert result["is_question"] is True
        # No question mark, but clear help-seeking

    def test_q7_offer_error(self):
        """Q7: 'I'm getting this error with my offers... What's causing this?'"""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "I'm getting this error with my offers when someone tries to accept them. What's causing this?: \"Attention\\nAn error occurred at task: ProcessOfferAvailabilityResponse\\nCannot take offer because taker's price is outside tolerance\".",
            "@yazh2.0:matrix.org",
        )

        assert result["is_question"] is True

    def test_q9_bisq_daemon_check(self):
        """Q9: 'Hello, if I only use the Bisq daemon...'"""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "Hello, if I only use the Bisq daemon (without the graphical interface), how can I check if the DAO is synchronized?",
            "@yazh2.0:matrix.org",
        )

        assert result["is_question"] is True

    def test_q10_dao_issues(self):
        """Q10: 'hello. anyone having issues with DAO today?'"""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "hello. anyone having issues with DAO today?", "@tobmath:matrix.org"
        )

        assert result["is_question"] is True

    def test_q11_seed_nodes_error_report(self):
        """Q11: User REPORTING seed nodes error (not explaining)."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "GM everyone! I woke up to a message about seed nodes: `We did not receive a filter object from the seed nodes.  This is a not expected situation.  Please inform the Bisq developers.`",
            "@user:matrix.org",
        )

        assert result["is_question"] is True
        # Should NOT be filtered as staff response

    def test_q15_what_should_i_do(self):
        """Q15: 'Hello, what should I do if...'"""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "Hello, what should I do if the father never approves the transaction?\\nEven though I made it.\\nIt appears on my bank statement and my banking app.\\nIt's been 22 hours.\\nShould I wait until the deadline to file a dispute?",
            "@sali:matrix.org",
        )

        assert result["is_question"] is True


class TestFalsePositiveReduction:
    """
    Test that improvements don't create NEW false positives.

    These messages should still be REJECTED.
    """

    def test_follow_up_with_yes_username(self):
        """Should still reject 'Yes [username]' follow-ups."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "Yes suddenwhipvapor For some weird reason...", "@user:matrix.org"
        )

        assert result["is_question"] is False

    def test_ok_username_follow_up(self):
        """Should still reject 'OK [username]' follow-ups."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "OK mwithm so I did what the link you sent me suggests...",
            "@user:matrix.org",
        )

        assert result["is_question"] is False

    def test_staff_command_suggestion(self):
        """Should still reject staff providing command suggestions."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "I have not tested its usefulness in real life, but there is a getdaostatus command in bisq-cli",
            "@helper:matrix.org",
        )

        assert result["is_question"] is False

    def test_same_here_follow_up(self):
        """Should still reject 'Same here' follow-ups."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        result = classifier.classify_message(
            "Same here, and some (more than usual) of the orders can't be taken.",
            "@user:matrix.org",
        )

        assert result["is_question"] is False


class TestPerformanceTargets:
    """
    Test overall performance targets after improvements.

    Target metrics based on data-driven analysis:
    - Recall: 60-70% (up from 26.7%)
    - Precision: 75-85% (up from 36.4%)
    """

    def test_user_question_recall_target(self):
        """Should achieve 60%+ recall on user questions from manual selection."""
        classifier = MultiLayerClassifier(OFFICIAL_SUPPORT_STAFF)

        # The 15 manually selected questions (shortened for readability)
        manual_questions = [
            "how do i check my bisq client version without launching it?",
            "i keep having tor connection issue when i start up the bisq app on linux",
            "What is the name of the mediator for the trade?",
            "Hi – I am in need of a mediator for trade ID #98590482",
            "Hey folks, I performed a BSQ Swap using Bisq 1, but I can't see any BSQ",
            "I have for the first time encountered a zelle limit payment",
            "I'm getting this error with my offers when someone tries to accept them",
            "Hi, I moved my bisq to another computer",
            "Hello, if I only use the Bisq daemon, how can I check if the DAO is synchronized?",
            "hello. anyone having issues with DAO today?",
            "GM everyone! I woke up to a message about seed nodes",
            "Hello, I placed a Buy BTC order, the seller's deposit transaction still shows unconfirmed",
            "Hello, I am trying to withdraw two transactions",
            'who is "N/A" on support agent list?',
            "Hello, what should I do if the father never approves the transaction?",
        ]

        correctly_identified = 0
        for msg in manual_questions:
            result = classifier.classify_message(msg, "@user:matrix.org")
            if result["is_question"]:
                correctly_identified += 1

        recall = correctly_identified / len(manual_questions)

        # Target: 60% recall (9/15 questions)
        assert recall >= 0.60, f"Recall {recall:.1%} below target of 60%"

        print(
            f"\nRecall: {correctly_identified}/{len(manual_questions)} = {recall:.1%}"
        )
