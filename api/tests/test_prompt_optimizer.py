from app.services.feedback.prompt_optimizer import PromptOptimizer


class _Analyzer:
    def analyze_feedback_issues(self, _feedback):
        return {
            "too_verbose": 6,
            "wrong_version": 4,
            "bad_tone": 4,
            "bad_formatting": 4,
            "partially_inaccurate": 4,
        }


def test_prompt_optimizer_emits_structured_guidance_for_common_quality_issues():
    optimizer = PromptOptimizer()
    updated = optimizer.update_prompt_guidance(
        feedback_data=[{"rating": 0}] * 20,
        analyzer=_Analyzer(),
    )

    assert updated is True
    guidance = optimizer.get_prompt_guidance()
    assert any("answer first" in item.lower() for item in guidance)
    assert any("do not mix bisq 1 and bisq 2" in item.lower() for item in guidance)
    assert any("human support teammate" in item.lower() for item in guidance)
    assert any("no markdown headings" in item.lower() for item in guidance)
    assert any(
        "uncertain" in item.lower() or "guessing" in item.lower() for item in guidance
    )
