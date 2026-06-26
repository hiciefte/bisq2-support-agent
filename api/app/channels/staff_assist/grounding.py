"""Staff-only grounding brief construction."""

from __future__ import annotations

import logging
from typing import Any

from app.services.rag.code_evidence import CODE_EVIDENCE_TYPE, STAFF_ONLY_AUDIENCE
from app.services.rag.interfaces import RetrievedDocument

logger = logging.getLogger(__name__)

_SUPPORTED_PROTOCOLS = {"bisq_easy", "multisig_v1", "musig", "all"}


class GroundingBriefService:
    """Build compact internal evidence for human support staff."""

    def __init__(self, *, code_retriever: Any, max_evidence: int = 3) -> None:
        self.code_retriever = code_retriever
        self.max_evidence = max(1, int(max_evidence))

    def build(
        self,
        *,
        question: str,
        knowledge_sources: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        query = str(question or "").strip()
        if not query:
            return None

        protocol = self._infer_protocol(knowledge_sources)
        try:
            docs = self.code_retriever.retrieve(
                query,
                protocol=protocol,
                k=self.max_evidence,
            )
        except Exception:
            logger.exception("Failed to retrieve staff-only code evidence")
            return None

        evidence = [
            self._format_code_fact(doc) for doc in docs if self._is_staff_code_fact(doc)
        ]
        if not evidence:
            return None

        return {
            "summary": "Staff-only grounding for this support request.",
            "likely_protocol": protocol or self._infer_protocol_from_evidence(evidence),
            "evidence": evidence,
            "safe_customer_guidance": [
                "Use this as investigation context, not as wording to paste to the user.",
                "Ask for the user's Bisq version and exact error text before making version-specific claims.",
            ],
            "uncertainties": self._uncertainties(evidence),
            "do_not_say": [
                "Do not expose raw file paths, class names, line numbers, or stack traces to the user.",
                "Do not treat main-branch code evidence as release-specific user guidance unless the user's version is known.",
            ],
        }

    def _infer_protocol(self, sources: list[dict[str, Any]]) -> str | None:
        for source in sources:
            protocol = str(source.get("protocol") or "").strip()
            if protocol in _SUPPORTED_PROTOCOLS and protocol != "all":
                return protocol
        return None

    def _is_staff_code_fact(self, doc: RetrievedDocument) -> bool:
        metadata = doc.metadata or {}
        return (
            metadata.get("type") == CODE_EVIDENCE_TYPE
            and metadata.get("audience") == STAFF_ONLY_AUDIENCE
        )

    def _format_code_fact(self, doc: RetrievedDocument) -> dict[str, Any]:
        metadata = doc.metadata or {}
        source_refs = list(metadata.get("source_refs") or [])
        return {
            "kind": CODE_EVIDENCE_TYPE,
            "claim": str(metadata.get("claim") or doc.content or "").strip(),
            "support_use": str(metadata.get("support_use") or "").strip(),
            "source_ref": source_refs[0] if source_refs else None,
            "source_refs": source_refs,
            "audience": STAFF_ONLY_AUDIENCE,
            "repo": metadata.get("repo"),
            "commit": metadata.get("commit"),
            "protocol": metadata.get("protocol"),
            "freshness_class": metadata.get("freshness_class"),
            "risk_level": metadata.get("risk_level"),
            "score": round(float(doc.score or 0.0), 4),
        }

    def _infer_protocol_from_evidence(
        self, evidence: list[dict[str, Any]]
    ) -> str | None:
        for item in evidence:
            protocol = str(item.get("protocol") or "").strip()
            if protocol in _SUPPORTED_PROTOCOLS and protocol != "all":
                return protocol
        return None

    def _uncertainties(self, evidence: list[dict[str, Any]]) -> list[str]:
        output: list[str] = []
        if any(item.get("freshness_class") == "main_branch" for item in evidence):
            output.append(
                "Main-branch code may not match the user's installed release."
            )
        output.append(
            "The evidence is staff-only until promoted into reviewed support knowledge."
        )
        return output
