#!/usr/bin/env python3
"""Preview at most ten public-context cases; never send to a room.

Input is {"cases": [{"id": "...", "request": <PublicContextRequest>}]}.
Without --execute this validates inputs without initializing a provider.
Execution writes an exclusive private JSONL evidence file, one attempt per case.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.channels.staff_assist.public_context import (  # noqa: E402
    PublicContextRequest,
    PublicContextService,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator  # noqa: E402


class PreviewCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    request: PublicContextRequest


class PreviewBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cases: list[PreviewCase] = Field(min_length=1, max_length=10)

    @field_validator("cases")
    @classmethod
    def unique_cases(cls, value: list[PreviewCase]) -> list[PreviewCase]:
        if len({case.id for case in value}) != len(value):
            raise ValueError("Case IDs must be unique")
        return value


def _observed_cost() -> float:
    from app.utils.instrumentation import RAG_COST

    for metric in RAG_COST.collect():
        for sample in metric.samples:
            if sample.name == "rag_cost_per_request_usd_sum":
                value = float(sample.value)
                if math.isfinite(value) and value >= 0:
                    return value
    raise RuntimeError("Generation cost metric unavailable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-observed-spend-usd", type=float, default=0.75)
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.max_observed_spend_usd)
        or not 0.25 <= args.max_observed_spend_usd <= 1
    ):
        parser.error("spend stop must be between 0.25 and 1 USD")
    if args.input.stat().st_size > 1_000_000:
        parser.error("input exceeds one MB")
    raw = args.input.read_bytes()
    batch = PreviewBatch.model_validate_json(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if not args.execute:
        print(
            json.dumps(
                {
                    "valid": True,
                    "cases": len(batch.cases),
                    "input_sha256": digest,
                    "provider_called": False,
                }
            )
        )
        return 0
    if args.output is None:
        parser.error("--execute requires --output")

    # Reserve the output before provider setup: an existing result is never
    # overwritten/replayed accidentally by rerunning the same command.
    with os.fdopen(
        os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        from app.core.config import get_settings
        from app.services.rag.llm_provider import LLMProvider

        settings = get_settings()
        llm = LLMProvider(settings).initialize_llm()
        service = PublicContextService(llm)
        initial_cost = _observed_cost()
        completed = 0
        for case in batch.cases:
            # Leave a next-call reserve. This is an observed-cost stop, not a
            # provider-enforced invoice ceiling; a call can exceed its reserve.
            if _observed_cost() - initial_cost >= args.max_observed_spend_usd - 0.20:
                print(json.dumps({"stopped": "spend_reserve", "completed": completed}))
                return 2
            before = _observed_cost()
            result = service.preview(case.request)
            row = {
                "id": case.id,
                "input_sha256": digest,
                "answer_model": settings.OPENAI_MODEL,
                "reasoning_effort": settings.OPENAI_REASONING_EFFORT,
                "preview": result.model_dump(),
                "observed_generation_cost_usd": _observed_cost() - before,
            }
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            completed += 1
            if result.decision.reason in {
                "generation_unavailable",
                "invalid_model_output",
            }:
                print(
                    json.dumps(
                        {"stopped": result.decision.reason, "completed": completed}
                    )
                )
                return 3
        print(
            json.dumps(
                {
                    "completed": completed,
                    "input_sha256": digest,
                    "observed_generation_cost_usd": _observed_cost() - initial_cost,
                    "messages_sent": 0,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
