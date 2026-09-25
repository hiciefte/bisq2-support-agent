"""Explicitly reviewed public sections of the same maintained internal wiki pages.

Publication stores metadata only in the existing knowledge database. It never
copies content into FAQs or rewrites a wiki page. Every read rechecks current
content, so an old approval cannot publish a subsequently edited projection.
"""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from app.channels.plugins.support_markdown import BISQ2_FAQ_ONION_BASE_URL
from app.services.rag.llm_wiki_loader import (
    INDEXABLE_STATUSES,
    _split_frontmatter,
    _validate_page,
)

PAGE_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}"
PUBLIC_SECTIONS = (
    ("canonical-support-answer", "Canonical Support Answer"),
    ("applies-when", "Applies When"),
)


def support_guide_url(page_id: str, *, internal: bool = False) -> str:
    if not re.fullmatch(PAGE_ID_PATTERN, page_id):
        raise ValueError("Invalid support guide ID")
    path = "admin/knowledge-updates/pages" if internal else "knowledge"
    return f"{BISQ2_FAQ_ONION_BASE_URL.rstrip('/')}/{path}/{page_id}"


class PublicKnowledgeService:
    def __init__(self, pages_dir: str | Path, db_path: str | Path):
        self.pages_dir = Path(pages_dir)
        self.db_path = str(db_path)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS knowledge_page_publications ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, page_id TEXT NOT NULL, "
                "action TEXT NOT NULL, revision TEXT NOT NULL, "
                "reviewer TEXT NOT NULL, created_at TEXT NOT NULL)"
            )

    def _page(self, page_id: str):
        if not re.fullmatch(PAGE_ID_PATTERN, page_id):
            raise ValueError("Invalid support guide ID")
        matches = []
        root = self.pages_dir.resolve()
        for path in sorted(self.pages_dir.rglob("*.md")):
            # Never follow a page or ancestor symlink out of the maintained tree.
            if path.is_symlink() or any(
                p.is_symlink() for p in path.parents if p != self.pages_dir.parent
            ):
                continue
            if not path.resolve().is_relative_to(root):
                continue
            try:
                frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"))
            except (ValueError, OSError, yaml.YAMLError):
                continue
            if frontmatter.get("id") == page_id:
                matches.append(
                    _validate_page(frontmatter=frontmatter, body=body, path=path)
                )
        if len(matches) != 1:
            raise ValueError("Support guide unavailable or ambiguous")
        return matches[0]

    def _projection(self, page) -> dict[str, Any]:
        sections: dict[str, str] = {}
        current = None
        lines: list[str] = []
        fenced = False
        for line in page.body.splitlines():
            if re.match(r"^\s{0,3}(`{3,}|~{3,})", line):
                fenced = not fenced
            heading = None if fenced else re.match(r"^## ([^#].*?)\s*#*\s*$", line)
            if heading:
                if current is not None:
                    if current in sections:
                        raise ValueError("Duplicate support guide section")
                    sections[current] = "\n".join(lines).strip()
                current, lines = heading.group(1), []
            else:
                lines.append(line)
        if current is not None:
            if current in sections:
                raise ValueError("Duplicate support guide section")
            sections[current] = "\n".join(lines).strip()
        selected = [
            {"id": anchor, "title": title, "content": sections.get(title, "")}
            for anchor, title in PUBLIC_SECTIONS
        ]
        if any(not section["content"] for section in selected):
            raise ValueError("Support guide requires answer and applicability sections")
        content = {
            "page_id": page.id,
            "title": page.title,
            "protocol": page.protocol,
            "sections": selected,
        }
        revision = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        url = support_guide_url(page.id)
        return {
            **content,
            "revision": revision,
            "url": url,
            "sections": [
                {**section, "url": f"{url}#{section['id']}"} for section in selected
            ],
        }

    def _events(self, page_id: str) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT action, revision, reviewer, created_at FROM knowledge_page_publications "
                    "WHERE page_id = ? ORDER BY id DESC",
                    (page_id,),
                )
            ]

    def get_internal_page(self, page_id: str) -> dict[str, Any]:
        page = self._page(page_id)
        events = self._events(page_id)
        try:
            projection = self._projection(page)
        except ValueError:
            projection = None
        public = bool(
            projection
            and page.status in INDEXABLE_STATUSES
            and events
            and events[0]["action"] == "publish"
            and events[0]["revision"] == projection["revision"]
        )
        return {
            "page_id": page.id,
            "title": page.title,
            "protocol": page.protocol,
            "status": page.status,
            "body": page.body,
            "projection": projection,
            "public": public,
            "can_publish": bool(projection and page.status in INDEXABLE_STATUSES),
            "publication_history": events,
        }

    def get_public_projection(self, page_id: str) -> dict[str, Any] | None:
        try:
            page = self.get_internal_page(page_id)
        except (ValueError, OSError):
            return None
        return page["projection"] if page["public"] else None

    def publish(self, page_id: str, revision: str, reviewer: str) -> dict[str, Any]:
        page = self._page(page_id)
        projection = self._projection(page)
        if page.status not in INDEXABLE_STATUSES or projection["revision"] != revision:
            raise ValueError("Support guide changed or is not reviewed; preview again")
        self._record(page_id, "publish", revision, reviewer)
        return self.get_internal_page(page_id)

    def revoke(self, page_id: str, reviewer: str) -> dict[str, Any]:
        # Revoke even when the current page is invalid or absent.
        if not re.fullmatch(PAGE_ID_PATTERN, page_id):
            raise ValueError("Invalid support guide ID")
        self._record(page_id, "revoke", "", reviewer)
        return {"page_id": page_id, "public": False}

    def _record(self, page_id: str, action: str, revision: str, reviewer: str) -> None:
        if not reviewer.strip() or len(reviewer) > 120:
            raise ValueError("Reviewer required")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO knowledge_page_publications (page_id, action, revision, reviewer, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    page_id,
                    action,
                    revision,
                    reviewer,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
