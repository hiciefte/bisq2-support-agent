#!/usr/bin/env python3
"""
Process and clean the Bisq Wiki dump XML file.
This script:
1. Parses the XML dump
2. Cleans HTML entities and formatting
3. Maintains proper context for Bisq 1 vs Bisq 2 content
4. Creates clean JSONL output for embedding
"""

import argparse
import json
import logging
import os
import re
import stat
import tempfile
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.scripts.wiki_text import WikiTextRenderer, template_key
from app.services.wiki_metadata import reviewed_wiki_category

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# MediaWiki namespace
NS = {"mw": "http://www.mediawiki.org/xml/export-0.10/"}


def coalesce_pages(
    pages: List[ET.Element], namespace: Dict[str, str]
) -> List[ET.Element]:
    """Join incremental WikiTeam blocks without accepting identity conflicts."""
    by_id = {}
    by_title = {}
    merged = []

    def signature(element):
        # XML indentation and tail whitespace are not revision content. Leaf
        # text (especially <text xml:space="preserve">) stays byte-exact.
        return (
            element.tag,
            tuple(sorted(element.attrib.items())),
            element.text if len(element) == 0 else (element.text or "").strip(),
            tuple(signature(child) for child in element),
        )

    for page in pages:
        title = page.findtext("mw:title", namespaces=namespace)
        ns = page.findtext("mw:ns", default="0", namespaces=namespace)
        raw_id = page.findtext("mw:id", namespaces=namespace)
        if not title:
            raise ValueError("Page missing title")
        if raw_id is not None and not re.fullmatch(r"[0-9]+", raw_id):
            raise ValueError(f"Page {title!r} has malformed page ID")
        page_id = int(raw_id) if raw_id is not None else None
        identity = (page_id, title, ns)
        if title in by_title and (page_id is None or by_title[title] != identity):
            raise ValueError(
                f"Duplicate article title or conflicting page identity: {title!r}"
            )
        by_title[title] = identity
        if page_id is not None and page_id in by_id:
            existing_identity, target = by_id[page_id]
            if identity != existing_identity:
                raise ValueError(f"Conflicting title/namespace for page ID {page_id}")
            # Page-level redirect metadata can describe a different chunk's
            # current state. The selected revision's actual directive wins.
            redirect = target.find("mw:redirect", namespace)
            if redirect is not None:
                target.remove(redirect)
            for revision in page.findall("mw:revision", namespace):
                target.append(deepcopy(revision))
        else:
            target = deepcopy(page)
            merged.append(target)
            if page_id is not None:
                by_id[page_id] = (identity, target)

    for page in merged:
        seen = {}
        for revision in list(page.findall("mw:revision", namespace)):
            raw_id = revision.findtext("mw:id", namespaces=namespace)
            if raw_id is None or not re.fullmatch(r"[0-9]+", raw_id):
                continue  # latest_revision gives the metadata error for history
            revision_id = int(raw_id)
            value = signature(revision)
            if revision_id in seen:
                if seen[revision_id] != value:
                    raise ValueError(
                        f"Conflicting contents for revision ID {revision_id}"
                    )
                page.remove(revision)
            else:
                seen[revision_id] = value
    return merged


def latest_revision(page: ET.Element, namespace: Dict[str, str]) -> ET.Element:
    """Select a history revision by UTC time, then numeric ID, never XML order.

    Legacy one-revision exports may omit metadata. Multiple revisions require
    complete, unambiguous metadata. A deleted latest revision is an unavailable
    source, not permission to silently publish an older revision instead.
    """
    title = page.findtext("mw:title", default="<untitled>", namespaces=namespace)
    revisions = page.findall("mw:revision", namespace)
    if not revisions:
        raise ValueError(f"Page {title!r} missing revision")
    ranked = []
    seen_ids = set()
    for revision in revisions:
        timestamp = revision.findtext("mw:timestamp", namespaces=namespace)
        revision_id = revision.findtext("mw:id", namespaces=namespace)
        if len(revisions) > 1 and (not timestamp or not revision_id):
            raise ValueError(f"Page {title!r} history revision missing timestamp or ID")
        instant = datetime.min.replace(tzinfo=timezone.utc)
        if timestamp is not None:
            try:
                if not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                    timestamp,
                ):
                    raise ValueError("expected timestamp with explicit timezone")
                instant = datetime.fromisoformat(
                    timestamp.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError as exc:
                raise ValueError(
                    f"Page {title!r} has malformed revision timestamp: {timestamp!r}"
                ) from exc
        numeric_id = -1
        if revision_id is not None:
            if not re.fullmatch(r"[0-9]+", revision_id):
                raise ValueError(
                    f"Page {title!r} has malformed revision ID: {revision_id!r}"
                )
            numeric_id = int(revision_id)
            if numeric_id in seen_ids:
                raise ValueError(
                    f"Page {title!r} has ambiguous duplicate revision ID: {revision_id}"
                )
            seen_ids.add(numeric_id)
        ranked.append((instant, numeric_id, revision))
    selected = max(ranked, key=lambda item: (item[0], item[1]))[2]
    text = selected.find("mw:text", namespace)
    if selected.get("deleted") is not None or (
        text is not None and text.get("deleted") is not None
    ):
        raise ValueError(f"Page {title!r} latest revision content is deleted")
    return selected


def revision_metadata(
    revision: ET.Element, namespace: Dict[str, str]
) -> Dict[str, str]:
    """Original revision identifiers, when present, for source provenance."""
    return {
        field: value
        for field in ("id", "timestamp")
        if (value := revision.findtext(f"mw:{field}", namespaces=namespace)) is not None
    }


class WikiDumpProcessor:
    def __init__(self, input_file: str, output_file: str):
        self.input_file = input_file
        self.output_file = output_file
        self.templates: Dict[str, str] = {}
        self.template_revisions: Dict[str, Dict[str, str]] = {}
        self.source_gaps: List[Dict[str, str]] = []
        self.namespace = NS
        self.context: Dict[str, List[Dict[str, Any]]] = {
            "bisq1": [],
            "bisq2": [],
            "general": [],
        }

    def clean_text(self, text: str) -> str:
        """Render without silently discarding warnings or missing expansions."""
        result = WikiTextRenderer(self.templates).render(text or "")
        self.source_gaps = result.source_gaps
        return result.text

    def categorize_content(self, title: str, content: str) -> str:
        """Categorize content as bisq1, bisq2, or general based on title and content analysis."""
        reviewed_category = reviewed_wiki_category(title)
        if reviewed_category is not None:
            return reviewed_category
        title_lower = title.lower()
        content_lower = content.lower()

        # Define Bisq 2 specific page titles and patterns
        bisq2_titles = [
            "bisq 2",
            "bisq easy",
            "bsq swaps",
            "bisq 2 roles",
            "automatic backup script",
        ]

        # Define Bisq 1 specific page titles and patterns
        bisq1_titles = [
            "arbitration",
            "arbitrator",
            "bsq",
            "mediator",
            "security deposits",
            "mediation",
            "dispute resolution",
            "refund agent",
            "burningman",
            "burning man",
            "dao",
            "bisq 1",
        ]

        # Check for exact title matches first
        for bisq2_title in bisq2_titles:
            if bisq2_title in title_lower:
                return "bisq2"

        for bisq1_title in bisq1_titles:
            if bisq1_title in title_lower:
                return "bisq1"

        # Content-based pattern analysis
        bisq2_score = 0
        bisq1_score = 0

        # Bisq 2 indicators
        bisq2_patterns = [
            "bisq easy",
            "reputation-based",
            "no security deposit",
            "trade protocols",
            "multiple identities",
            "multiple trade protocols",
            "bisq 2",
            "bisq2",
            "600 usd",
            "$600",
            "novice bitcoin",
            "reputation system",
            "bonded roles",
        ]

        # Bisq 1 indicators
        bisq1_patterns = [
            "multisig",
            "2-of-2 multisig",
            "arbitration",
            "security deposits",
            "time-locked",
            "delayed payout",
            "v1.2",
            "version 1.",
            "mediation",
            "dispute resolution",
            "dao voting",
            "bsq burning",
            "refund agent",
        ]

        for pattern in bisq2_patterns:
            if pattern in content_lower:
                bisq2_score += content_lower.count(pattern)

        for pattern in bisq1_patterns:
            if pattern in content_lower:
                bisq1_score += content_lower.count(pattern)

        # Determine category based on scores
        if bisq2_score > bisq1_score and bisq2_score > 0:
            return "bisq2"
        elif bisq1_score > bisq2_score and bisq1_score > 0:
            return "bisq1"
        else:
            # Additional context clues for general content
            if "bisq 2" in content_lower or "bisq2" in content_lower:
                return "bisq2"
            elif "bisq 1" in content_lower or any(
                v in content_lower for v in ["v1.2", "version 1"]
            ):
                return "bisq1"
            else:
                return "general"

    def process_page(self, page: ET.Element) -> Optional[Dict]:
        """Process a single wiki page."""
        try:
            title_elem = page.find("mw:title", self.namespace)
            if title_elem is None or title_elem.text is None:
                raise ValueError("Page missing title")
            title = title_elem.text

            # Template definitions and other namespaces are not support articles.
            namespace = page.findtext("mw:ns", default="0", namespaces=self.namespace)
            if namespace != "0" or title.lower().startswith(("file:", "template:")):
                return None
            revision = latest_revision(page, self.namespace)

            text_elem = revision.find("mw:text", self.namespace)
            if text_elem is None or text_elem.get("deleted") is not None:
                raise ValueError(f"Page {title!r} missing text content")

            content = text_elem.text or ""
            redirect = page.find("mw:redirect", self.namespace)
            redirect_target = redirect.get("title") if redirect is not None else None
            directive = re.match(
                r"^(?:\s|<!--.*?-->)*#redirect\s*:?\s*\[\[([^\]]+)\]\]",
                content,
                re.IGNORECASE | re.DOTALL,
            )
            if directive:
                redirect_target = directive.group(1).split("|", 1)[0].strip()
                content = content[directive.end() :]

            # Use enhanced categorization logic
            category = self.categorize_content(title, content)

            # Clean the text
            clean_content = self.clean_text(content)

            # Pure redirects have no article body, but trailing prose, warnings
            # and lists in a redirect source are still useful content.
            if not clean_content.strip():
                logger.debug(f"Skipping redirect/empty page: {title}")
                return None

            # Create page entry
            entry = {"title": title, "content": clean_content, "category": category}
            if redirect_target:
                entry["redirect_target"] = redirect_target
            provenance = revision_metadata(revision, self.namespace)
            if provenance:
                entry["source_revision"] = provenance
            if self.source_gaps:
                entry["source_gaps"] = self.source_gaps.copy()
                logger.warning(
                    "Page %r has %d unresolved source gaps",
                    title,
                    len(self.source_gaps),
                )

            logger.info(f"Processed page: {title} (category: {entry['category']})")
            return entry

        except Exception as e:
            logger.error(f"Error processing page: {str(e)}", exc_info=True)
            raise

    def process_dump(self):
        """Process the entire wiki dump."""
        logger.info(f"Processing wiki dump from {self.input_file}")

        try:
            # Parse XML
            tree = ET.parse(self.input_file)
            root = tree.getroot()

            namespace_uri = root.tag.partition("}")[0].lstrip("{")
            if not namespace_uri.startswith("http://www.mediawiki.org/xml/export-"):
                raise ValueError("Input is not a namespaced MediaWiki export")
            self.namespace = {"mw": namespace_uri}
            pages = coalesce_pages(
                root.findall("mw:page", self.namespace), self.namespace
            )
            self.context = {"bisq1": [], "bisq2": [], "general": []}
            self.templates = {}
            self.template_revisions = {}
            # Definitions can appear after the articles which invoke them.
            for page in pages:
                title = page.findtext("mw:title", default="", namespaces=self.namespace)
                ns = page.findtext("mw:ns", default="0", namespaces=self.namespace)
                if ns == "10" or title.lower().startswith("template:"):
                    selected = latest_revision(page, self.namespace)
                    definition = selected.find("mw:text", self.namespace)
                    if (
                        not title
                        or definition is None
                        or definition.get("deleted") is not None
                    ):
                        raise ValueError(
                            f"Template {title!r} has no available definition"
                        )
                    key = template_key(title)
                    value = definition.text or ""
                    if key in self.templates and self.templates[key] != value:
                        raise ValueError(f"Conflicting definitions for Template:{key}")
                    self.templates[key] = value
                    self.template_revisions[key] = revision_metadata(
                        selected, self.namespace
                    )
            logger.info(f"Found {len(pages)} pages in the dump")

            # Process each page
            processed_count = 0
            article_titles = set()
            for page in pages:
                entry = self.process_page(page)
                if entry:
                    if entry["title"] in article_titles:
                        raise ValueError(f"Duplicate article title: {entry['title']!r}")
                    article_titles.add(entry["title"])
                    self.context[entry["category"]].append(entry)
                    processed_count += 1

            logger.info(f"Successfully processed {processed_count} pages")
            logger.info("Categories breakdown:")
            for category, entries in self.context.items():
                logger.info(f"- {category}: {len(entries)} entries")

            # Save processed content
            self.save_processed_content()
            logger.info(f"Processed content saved to {self.output_file}")

        except Exception as e:
            logger.error(f"Error processing dump: {str(e)}", exc_info=True)
            raise

    def save_processed_content(self):
        """Save processed content to JSONL file."""
        total_entries = sum(len(entries) for entries in self.context.values())
        if total_entries == 0:
            raise ValueError("No articles to save; existing corpus left unchanged")

        destination = os.path.abspath(self.output_file)
        try:
            output_mode = stat.S_IMODE(os.stat(destination).st_mode) & 0o777
        except FileNotFoundError:
            output_mode = 0o644  # New wiki output is public source material.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=os.path.dirname(destination),
                prefix=".wiki-",
                suffix=".jsonl.tmp",
                delete=False,
            ) as output:
                temporary = output.name
                os.fchmod(output.fileno(), output_mode)
                for category in ("bisq2", "bisq1", "general"):
                    for entry in self.context[category]:
                        output.write(json.dumps(entry, ensure_ascii=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            temporary = None
        finally:
            if temporary is not None:
                os.unlink(temporary)


def main():
    # Define file paths
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    input_file = os.path.join(project_root, "data", "wiki", "bisq2_dump.xml")
    output_file = os.path.join(project_root, "data", "wiki", "processed_wiki.jsonl")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-file", default=input_file, help="MediaWiki XML input")
    parser.add_argument(
        "--output-file", default=output_file, help="Processed JSONL destination"
    )
    args = parser.parse_args()
    input_file, output_file = args.input_file, args.output_file

    # Check if input file exists
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    # Process the dump
    processor = WikiDumpProcessor(str(input_file), str(output_file))
    processor.process_dump()


if __name__ == "__main__":
    main()
