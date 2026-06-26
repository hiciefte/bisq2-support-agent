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
        draft_answer: str | None = None,
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
            self._format_code_fact(doc)
            for doc in docs
            if self._is_staff_code_fact(doc, expected_protocol=protocol)
        ]
        if not evidence:
            return None

        safe_customer_guidance = [
            "Use this as investigation context, not as wording to paste to the user.",
            "Ask for the user's Bisq version and exact error text before making version-specific claims.",
        ]
        uncertainties = self._uncertainties(evidence)
        do_not_say = [
            "Do not expose raw file paths, class names, line numbers, or stack traces to the user.",
            "Do not treat main-branch code evidence as release-specific user guidance unless the user's version is known.",
        ]

        return {
            "summary": "Staff-only grounding for this support request.",
            "likely_protocol": protocol or self._infer_protocol_from_evidence(evidence),
            "evidence": evidence,
            "safe_customer_guidance": safe_customer_guidance,
            "uncertainties": uncertainties,
            "do_not_say": do_not_say,
            "staff_enriched_answer": self._build_staff_enriched_answer(
                draft_answer=draft_answer,
                evidence=evidence,
                safe_customer_guidance=safe_customer_guidance,
                uncertainties=uncertainties,
            ),
        }

    def _infer_protocol(self, sources: list[dict[str, Any]]) -> str | None:
        for source in sources:
            protocol = str(source.get("protocol") or "").strip()
            if protocol in _SUPPORTED_PROTOCOLS and protocol != "all":
                return protocol
        return None

    def _is_staff_code_fact(
        self, doc: RetrievedDocument, *, expected_protocol: str | None
    ) -> bool:
        metadata = doc.metadata or {}
        doc_protocol = str(metadata.get("protocol") or "").strip()
        return (
            metadata.get("type") == CODE_EVIDENCE_TYPE
            and metadata.get("audience") == STAFF_ONLY_AUDIENCE
            and (
                expected_protocol is None or doc_protocol in {expected_protocol, "all"}
            )
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

    def _build_staff_enriched_answer(
        self,
        *,
        draft_answer: str | None,
        evidence: list[dict[str, Any]],
        safe_customer_guidance: list[str],
        uncertainties: list[str],
    ) -> str:
        """Create an internal staff-room answer draft using code evidence.

        This text is intentionally not customer-copy-safe. It helps staff decide
        whether and how to edit the normal RAG draft before sending a reply.
        """
        draft = str(draft_answer or "").strip()
        parts: list[str] = []
        if draft:
            parts.append(draft)
        else:
            parts.append("No public-safe draft answer was generated.")

        code_lines = []
        for item in evidence[: self.max_evidence]:
            claim = str(item.get("claim") or "").strip()
            support_use = str(item.get("support_use") or "").strip()
            if not claim:
                continue
            if support_use:
                code_lines.append(f"- {claim} Staff use: {support_use}")
            else:
                code_lines.append(f"- {claim}")

        if code_lines:
            parts.append("Staff-only codebase context:\n" + "\n".join(code_lines))

        if safe_customer_guidance:
            parts.append(
                "Safe customer guidance:\n"
                + "\n".join(f"- {item}" for item in safe_customer_guidance)
            )

        if uncertainties:
            parts.append(
                "Uncertainties to verify:\n"
                + "\n".join(f"- {item}" for item in uncertainties)
            )

        return "\n\n".join(parts).strip()
