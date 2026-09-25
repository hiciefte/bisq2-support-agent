"""Validated official release snapshots; no network or model calls at runtime."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.rag.code_evidence import (
    _STOP_WORDS,
    _TOKEN_RE,
    code_repo_for_context,
    explicit_product,
    release_version,
)


@dataclass(frozen=True)
class ReleaseNote:
    repo: str
    tag: str
    commit: str
    published_at: str
    url: str
    body: str
    body_sha256: str

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> ReleaseNote:
        fields = {key: row.get(key) for key in cls.__dataclass_fields__}
        if not all(isinstance(value, str) and value for value in fields.values()):
            raise ValueError("Release snapshot requires all string fields")
        note = cls(**fields)
        version = release_version(note.tag)
        if note.repo not in {"bisq", "bisq2"} or not re.fullmatch(
            r"[0-9a-f]{40}", note.commit
        ):
            raise ValueError("Invalid release repository or immutable commit")
        if (
            note.url
            != f"https://github.com/bisq-network/{note.repo}/releases/tag/{note.tag}"
        ):
            raise ValueError("Release notes must use the exact official tag URL")
        if (
            not version.startswith("1." if note.repo == "bisq" else "2.")
            or "-" in version
        ):
            raise ValueError("Release version does not match the stable product")
        if (
            datetime.fromisoformat(note.published_at.replace("Z", "+00:00")).utcoffset()
            is None
        ):
            raise ValueError("Release publication date must include timezone")
        if (
            len(note.body.encode()) > 65536
            or hashlib.sha256(note.body.encode()).hexdigest() != note.body_sha256
        ):
            raise ValueError("Release body size or digest mismatch")
        return note

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class ReleaseNotesLoader:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[ReleaseNote]:
        if not self.path.exists():
            return []
        if self.path.stat().st_size > 2_000_000:
            raise ValueError("Release snapshot corpus is too large")
        records = [
            ReleaseNote.from_dict(json.loads(line))
            for line in self.path.read_text().splitlines()
            if line.strip()
        ]
        identities: set[tuple[str, str]] = set()
        for record in records:
            key = (record.repo, record.tag)
            if key in identities:
                raise ValueError("Ambiguous duplicate release snapshot")
            identities.add(key)
        return records

    def retrieve(
        self,
        query: str,
        *,
        product: str | None = None,
        protocol: str | None = None,
        user_version: str | None = None,
    ) -> list[dict[str, Any]]:
        repo = code_repo_for_context(product or explicit_product(query), protocol)
        if repo is None:
            return []
        notes = [
            note
            for note in self.load()
            if note.repo == repo
            and (
                user_version is None
                or release_version(note.tag) == user_version.removeprefix("v")
            )
        ]
        # One release per question; no cross-version blend when installed version
        # is unknown. Latest is source scope, never an inferred user version.
        notes.sort(
            key=lambda note: tuple(map(int, release_version(note.tag).split("."))),
            reverse=True,
        )
        if not notes:
            return []
        note = notes[0]
        terms = set(_TOKEN_RE.findall(query.casefold())) - _STOP_WORDS
        paragraphs = re.split(r"\n\s*\n", note.body)
        ranked = sorted(
            enumerate(paragraphs),
            key=lambda pair: (
                -len(terms & set(_TOKEN_RE.findall(pair[1].casefold()))),
                pair[0],
            ),
        )
        relevant = [
            text
            for _, text in ranked
            if terms & set(_TOKEN_RE.findall(text.casefold()))
        ][:3]
        if not relevant and not re.search(
            r"\b(?:release|update|upgrade|changed|new)\b", query, re.I
        ):
            return []
        excerpt = "\n\n".join(relevant or paragraphs[:2])[:6000]
        return [
            {
                **note.to_dict(),
                "body": excerpt,
                "excerpt": True,
                "source_version": release_version(note.tag),
                "user_version": user_version,
                "limitation": "Official release notes describe this source release, not the user's installed version or a diagnosis. An omitted change is not proof of its absence.",
            }
        ]
