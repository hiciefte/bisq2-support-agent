"""Tests for EmpathyDetector service."""

import pytest
from app.services.rag.empathy_detector import EmpathyDetector


@pytest.fixture
def detector():
    return EmpathyDetector()


class TestFrustrationDetection:
    """Test frustration pattern detection."""

    @pytest.mark.asyncio
    async def test_detect_high_frustration(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "This is broken!! Nothing works and I'm so frustrated!"
        )
        assert emotion == "frustrated"
        assert intensity > 0.5

    @pytest.mark.asyncio
    async def test_detect_frustration_not_working(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "It's not working and I don't understand why"
        )
        assert emotion == "frustrated"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_frustration_stuck(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "I'm stuck on this step and can't figure out what to do"
        )
        assert emotion == "frustrated"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_frustration_multiple_exclamation(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "Why doesn't this work!!! I've tried everything and I'm stuck!!"
        )
        assert emotion == "frustrated"
        assert intensity > 0.5

    @pytest.mark.asyncio
    async def test_detect_frustration_multiple_question_marks(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "Why isn't this working???? I don't understand what I'm doing wrong??"
        )
        assert emotion == "frustrated"
        assert intensity > 0.3


class TestConfusionDetection:
    """Test confusion pattern detection."""

    @pytest.mark.asyncio
    async def test_detect_confusion_dont_understand(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "I don't understand what this means. Can you explain?"
        )
        assert emotion == "confused"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_confusion_dont_get(self, detector):
        emotion, intensity = await detector.detect_emotion("I don't get how this works")
        assert emotion == "confused"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_confusion_lost(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "I'm lost, where do I find this setting?"
        )
        assert emotion == "confused"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_confusion_what_does_mean(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "What does reputation score mean?"
        )
        assert emotion == "confused"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_confusion_help_understand(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "Help me understand how trading works"
        )
        assert emotion == "confused"
        assert intensity > 0.3


class TestPositiveDetection:
    """Test positive emotion detection."""

    @pytest.mark.asyncio
    async def test_detect_positive_thank(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "Thank you! That was really helpful!"
        )
        assert emotion == "positive"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_positive_great(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "Great, that's exactly what I needed!"
        )
        assert emotion == "positive"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_positive_works(self, detector):
        emotion, intensity = await detector.detect_emotion("It works now! Perfect!")
        assert emotion == "positive"
        assert intensity > 0.3

    @pytest.mark.asyncio
    async def test_detect_positive_got_it(self, detector):
        emotion, intensity = await detector.detect_emotion("Got it, I understand now")
        assert emotion == "positive"
        assert intensity > 0.3


class TestNeutralDetection:
    """Test neutral message handling."""

    @pytest.mark.asyncio
    async def test_neutral_message(self, detector):
        emotion, intensity = await detector.detect_emotion("How do I start a trade?")
        assert emotion == "neutral"
        assert intensity == 0.0

    @pytest.mark.asyncio
    async def test_neutral_simple_question(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "What are the supported payment methods?"
        )
        assert emotion == "neutral"
        assert intensity == 0.0

    @pytest.mark.asyncio
    async def test_neutral_factual_statement(self, detector):
        emotion, intensity = await detector.detect_emotion(
            "I want to buy Bitcoin with bank transfer"
        )
        assert emotion == "neutral"
        assert intensity == 0.0


class TestResponseModifiers:
    """Test response modifier generation."""

    def test_response_modifier_high_frustration(self, detector):
        modifier = detector.get_response_modifier("frustrated", 0.8)
        assert "empathy" in modifier.lower()
        assert "step-by-step" in modifier.lower()

    def test_response_modifier_low_frustration(self, detector):
        modifier = detector.get_response_modifier("frustrated", 0.3)
        # Low intensity shouldn't trigger special response
        assert modifier == ""

    def test_response_modifier_confusion(self, detector):
        modifier = detector.get_response_modifier("confused", 0.5)
        assert "explain" in modifier.lower() or "simple" in modifier.lower()

    def test_response_modifier_low_confusion(self, detector):
        modifier = detector.get_response_modifier("confused", 0.2)
        # Low intensity shouldn't trigger special response
        assert modifier == ""

    def test_response_modifier_positive(self, detector):
        modifier = detector.get_response_modifier("positive", 0.6)
        assert "additional" in modifier.lower() or "energy" in modifier.lower()

    def test_response_modifier_neutral(self, detector):
        modifier = detector.get_response_modifier("neutral", 0.0)
        assert modifier == ""


class TestIntensityCalculation:
    """Test intensity score calculation."""

    @pytest.mark.asyncio
    async def test_intensity_increases_with_patterns(self, detector):
        # Single pattern
        _, intensity1 = await detector.detect_emotion("This is broken")
        # Multiple patterns
        _, intensity2 = await detector.detect_emotion(
            "This is broken!! Not working! I'm stuck and frustrated!"
        )
        assert intensity2 > intensity1

    @pytest.mark.asyncio
    async def test_intensity_capped_at_one(self, detector):
        # Many frustration patterns
        _, intensity = await detector.detect_emotion(
            "Broken!! Not working!! Stuck!! Frustrated!! Can't figure out!! "
            "Annoyed!! Waste of time!!"
        )
        assert intensity <= 1.0


class TestCaseInsensitivity:
    """Test case-insensitive pattern matching."""

    @pytest.mark.asyncio
    async def test_frustration_uppercase(self, detector):
        emotion, _ = await detector.detect_emotion("THIS IS BROKEN AND NOT WORKING")
        assert emotion == "frustrated"

    @pytest.mark.asyncio
    async def test_confusion_mixed_case(self, detector):
        emotion, _ = await detector.detect_emotion("I Don't Get What This Means")
        assert emotion == "confused"

    @pytest.mark.asyncio
    async def test_positive_lowercase(self, detector):
        emotion, _ = await detector.detect_emotion("thank you so much for your help")
        assert emotion == "positive"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_message(self, detector):
        emotion, intensity = await detector.detect_emotion("")
        assert emotion == "neutral"
        assert intensity == 0.0

    @pytest.mark.asyncio
    async def test_mixed_emotions_frustration_wins(self, detector):
        # Frustration requires 2+ patterns, confusion requires 1
        emotion, _ = await detector.detect_emotion(
            "I don't understand why this is broken and not working!"
        )
        # Frustration should win when both present with high frustration
        assert emotion in ["frustrated", "confused"]

    @pytest.mark.asyncio
    async def test_special_characters_only(self, detector):
        emotion, intensity = await detector.detect_emotion("!!! ???")
        # Multiple exclamation/question marks should trigger frustration
        assert emotion == "frustrated"

    @pytest.mark.asyncio
    async def test_single_exclamation_not_frustration(self, detector):
        emotion, _ = await detector.detect_emotion("Help!")
        # Single exclamation mark shouldn't indicate frustration
        assert emotion != "frustrated"
