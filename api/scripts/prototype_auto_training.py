#!/usr/bin/env python3
r"""
Prototype script to test auto-training pipeline with Matrix export.

Usage:
    python api/scripts/prototype_auto_training.py <matrix_export.json>

Example:
    python api/scripts/prototype_auto_training.py \
        ~/Downloads/matrix\ -\ Support\ -\ Chat\ Export.json
"""

import asyncio
import json
import sys
from pathlib import Path

# Add api to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import aisuite  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.services.simplified_rag_service import SimplifiedRAGService  # noqa: E402
from app.services.training.comparison_engine import AnswerComparisonEngine  # noqa: E402
from app.services.training.matrix_export_parser import MatrixExportParser  # noqa: E402
from app.services.training.substantive_filter import (
    SubstantiveAnswerFilter,
)  # noqa: E402
from app.services.wiki_service import WikiService  # noqa: E402
from langchain_openai import OpenAIEmbeddings  # noqa: E402


async def main(export_file: str, sample_size: int = 20):
    """Run prototype auto-training pipeline."""

    print(f"\n{'='*60}")
    print("AUTO-TRAINING PIPELINE PROTOTYPE v2.0")
    print(f"{'='*60}\n")

    settings = Settings()

    # Initialize components
    print("[1/5] Initializing components...")
    ai_client = aisuite.Client()
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    parser = MatrixExportParser()
    answer_filter = SubstantiveAnswerFilter(ai_client)
    comparison = AnswerComparisonEngine(ai_client, embeddings)

    # Initialize RAG service for generating our answers
    print("      Loading RAG service (this may take a moment)...")
    wiki_service = WikiService(settings)
    rag_service = SimplifiedRAGService(settings, wiki_service=wiki_service)
    await rag_service.setup()  # Must call setup() before query()

    # Step 1: Parse Matrix export
    print(f"\n[2/5] Parsing Matrix export: {export_file}")
    data = parser.parse_export(export_file)
    qa_pairs = parser.extract_qa_pairs(data, anonymize_pii=True)
    print(f"      Extracted {len(qa_pairs)} Q&A pairs")

    if not qa_pairs:
        print("\n❌ No Q&A pairs found. Check if the export contains staff replies.")
        return None

    # Step 2: Filter substantive answers
    print("\n[3/5] Filtering substantive answers...")
    substantive_pairs, filtered_pairs = await answer_filter.filter_answers(qa_pairs)
    print(f"      Substantive: {len(substantive_pairs)}")
    print(f"      Filtered: {len(filtered_pairs)}")

    if not substantive_pairs:
        print("\n❌ No substantive answers found after filtering.")
        return None

    # Step 3: Generate our answers and compare
    print(f"\n[4/5] Comparing answers (processing {sample_size} samples)...")
    print("      This may take a while due to LLM calls...")

    results = {
        "AUTO_APPROVE": [],
        "SPOT_CHECK": [],
        "FULL_REVIEW": [],
    }

    # Process first N pairs for prototype
    actual_sample_size = min(sample_size, len(substantive_pairs))

    for i, pair in enumerate(substantive_pairs[:actual_sample_size]):
        print(f"      Processing {i+1}/{actual_sample_size}...", end="\r")

        try:
            # Generate our answer (query is already async)
            rag_result = await rag_service.query(
                pair.question_text,
                chat_history=[],
            )
            our_answer = rag_result.get("response", "")

            # Compare with staff answer
            comparison_result = await comparison.compare(
                question_event_id=pair.question_event_id,
                question_text=pair.question_text,
                staff_answer=pair.answer_text,
                generated_answer=our_answer,
            )

            results[comparison_result.routing].append(
                {
                    "question_event_id": pair.question_event_id,
                    "question": pair.question_text[:200],
                    "staff_answer": pair.answer_text[:200],
                    "our_answer": our_answer[:200],
                    "score": comparison_result.final_score,
                    "embedding_sim": comparison_result.embedding_similarity,
                    "factual_alignment": comparison_result.factual_alignment,
                    "contradiction_score": comparison_result.contradiction_score,
                    "completeness": comparison_result.completeness,
                    "hallucination_risk": comparison_result.hallucination_risk,
                    "reasoning": comparison_result.llm_reasoning,
                    "is_calibration": comparison_result.is_calibration,
                }
            )
        except Exception as e:
            print(f"\n      Error processing pair {i+1}: {e}")
            continue

    # Step 4: Report results
    print("\n\n[5/5] Results Summary")
    print("=" * 60)

    total = (
        len(results["AUTO_APPROVE"])
        + len(results["SPOT_CHECK"])
        + len(results["FULL_REVIEW"])
    )

    if total == 0:
        print("\n❌ No results generated. Check for errors above.")
        return None

    for routing, items in results.items():
        pct = (len(items) / total * 100) if total > 0 else 0
        print(f"\n{routing}: {len(items)} ({pct:.1f}%)")
        for item in items[:3]:  # Show first 3 examples
            print(f"  - Score: {item['score']:.2f} | Q: {item['question'][:50]}...")

    # Show calibration status
    print(f"\n{'='*60}")
    print("CALIBRATION STATUS")
    print(f"{'='*60}")
    print(
        f"Calibration mode: {'ACTIVE' if comparison.is_calibration_mode else 'COMPLETE'}"
    )
    print(
        f"Samples processed: {comparison.calibration_count}/{comparison.calibration_samples_required}"
    )

    # Show token usage
    token_usage = comparison.get_token_usage()
    print(f"\n{'='*60}")
    print("TOKEN USAGE (LLM-as-Judge)")
    print(f"{'='*60}")
    print(f"Prompt tokens: {token_usage['prompt_tokens']}")
    print(f"Completion tokens: {token_usage['completion_tokens']}")
    print(f"Total tokens: {token_usage['total_tokens']}")

    # Save detailed results
    output_file = "prototype_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to: {output_file}")

    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python prototype_auto_training.py <matrix_export.json> [sample_size]"
        )
        print("\nExample:")
        print(
            "  python api/scripts/prototype_auto_training.py ~/Downloads/matrix\\ -\\ Support.json"
        )
        print("  python api/scripts/prototype_auto_training.py export.json 50")
        sys.exit(1)

    export_file = sys.argv[1]
    sample_size = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    asyncio.run(main(export_file, sample_size))
