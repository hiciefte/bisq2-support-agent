"""Replay saved answer pairs through the contextual judge, without data mutations.

Run from api/ with provider credentials in the environment:
    python -m app.scripts.replay_comparison_review INPUT.json OUTPUT.json

INPUT is a candidate export with an `items` list, or a list of objects containing
question_text, staff_answer, and generated_answer. Existing edited question/staff
fields take precedence. Output contains sample indices and review judgments only;
it is private because judge evidence can quote input. This evaluates the judge,
not retrieval, ingestion, FAQ promotion, or end-to-end production quality.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.services.knowledge.comparison_engine import AnswerComparisonEngine


async def replay(input_path: Path, output_path: Path, model: str) -> None:
    import aisuite

    if output_path.exists():
        raise FileExistsError("Refusing to overwrite prior replay evidence")
    data = json.loads(input_path.read_text())
    items = data["items"] if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError("Expected a nonempty list of saved candidates")
    engine = AnswerComparisonEngine(
        ai_client=aisuite.Client(), embeddings_model=None, judge_model=model
    )
    results = []
    for index, item in enumerate(items, 1):
        question = item.get("edited_question_text") or item["question_text"]
        staff = item.get("edited_staff_answer") or item["staff_answer"]
        generated = item["generated_answer"]
        if not all(
            isinstance(value, str) and value.strip()
            for value in (question, staff, generated)
        ):
            raise ValueError(f"Sample {index} lacks a complete answer pair")
        result = await engine._llm_judge(question, staff, generated)
        requires_review, summary = engine._review_guard(result)
        results.append(
            {
                "sample_index": index,
                "requires_full_review": requires_review,
                "disposition": result.get("disposition"),
                "evaluation_status": result.get("evaluation_status", "success"),
                "context_review": summary,
                "reasoning": result.get("reasoning", ""),
            }
        )
    # Refuse to overwrite prior evidence; do not expose source IDs or raw inputs.
    fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(
            {
                "judge_model": model,
                "samples": results,
                "token_usage": engine.get_token_usage(),
            },
            output,
            indent=2,
        )
        output.write("\n")
    print(f"reviewed_samples={len(results)}; private_report_written=yes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--judge-model", default="openai:gpt-4o-mini")
    args = parser.parse_args()
    asyncio.run(replay(args.input, args.output, args.judge_model))


if __name__ == "__main__":
    main()
