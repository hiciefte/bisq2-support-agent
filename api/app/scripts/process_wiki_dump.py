#!/usr/bin/env python3
"""
Process and clean the Bisq Wiki dump XML file.
This script:
1. Parses the XML dump
2. Cleans HTML entities and formatting
3. Maintains proper context for Bisq 1 vs Bisq 2 content
4. Creates clean JSONL output for embedding
"""

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Dict, Optional

from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# MediaWiki namespace
NS = {"mw": "http://www.mediawiki.org/xml/export-0.10/"}


class WikiDumpProcessor:
    def __init__(self, input_file: str, output_file: str):
        self.input_file = input_file
        self.output_file = output_file
        self.context = {"bisq1": [], "bisq2": [], "general": []}

    def clean_text(self, text: str) -> str:
        """
        Clean MediaWiki text by converting it to a more readable format,
        preserving structure like headings and bold text, while removing
        unnecessary markup.
        """
        if not text:
            return ""

        # --- Stage 1: Regex-based MediaWiki syntax conversion ---

        # Keep content of <pre> blocks, protect them from further processing
        pre_blocks = {}

        def pre_tag_replacer(match):
            key = f"__PRE_BLOCK_{len(pre_blocks)}__"
            # Extract content and remove the tags
            content = match.group(1).strip()
            pre_blocks[key] = f"\n```\n{content}\n```\n"
            return key

        text = re.sub(r"<pre>(.*?)</pre>", pre_tag_replacer, text, flags=re.DOTALL)

        # Convert headings: == Heading == -> ## Heading
        text = re.sub(r"==\s*(.*?)\s*==", r"\n## \1\n", text)

        # Convert bold: '''bold''' -> **bold**
        text = re.sub(r"'''(.*?)'''", r"**\1**", text)

        # Convert internal links: [[Page Title|display text]] -> display text
        text = re.sub(r"\[\[(?:[^|\]]+\|)?([^\]]+)\]\]", r"\1", text)

        # Remove file links and thumbnails: [[File:...]]
        text = re.sub(r"\[\[File:.*?\]\]", "", text, flags=re.IGNORECASE)

        # Remove templates: {{template...}}
        text = re.sub(r"{{.*?}}", "", text, flags=re.DOTALL)

        # --- Stage 2: HTML tag stripping with BeautifulSoup ---
        soup = BeautifulSoup(text, "html.parser")
        text = soup.get_text()

        # --- Stage 3: Final cleanup ---

        # Restore <pre> blocks
        for key, value in pre_blocks.items():
            text = text.replace(key, value)

        # Consolidate multiple newlines into a maximum of two
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove multiple spaces
        text = re.sub(r" +", " ", text)
        # Remove leading/trailing whitespace from each line
        text = "\n".join(line.strip() for line in text.split("\n"))

        return text.strip()

    def categorize_content(self, title: str, content: str) -> str:
        """Categorize content as bisq1, bisq2, or general based on title and content analysis."""
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
            title_elem = page.find("mw:title", NS)
            if title_elem is None or title_elem.text is None:
                logger.warning("Page missing title")
                return None
            title = title_elem.text

            # Skip pages that are just file descriptions as they provide no value
            if title.startswith("File:"):
                return None

            revision = page.find("mw:revision", NS)
            if revision is None:
                logger.warning(f"Page '{title}' missing revision")
                return None

            text_elem = revision.find("mw:text", NS)
            if text_elem is None or text_elem.text is None:
                logger.warning(f"Page '{title}' missing text content")
                return None

            content = text_elem.text

            # Use enhanced categorization logic
            category = self.categorize_content(title, content)

            # Clean the text
            clean_content = self.clean_text(content)

            # Skip redirects and empty pages
            if clean_content.startswith("#REDIRECT") or not clean_content.strip():
                logger.debug(f"Skipping redirect/empty page: {title}")
                return None

            # Create page entry
            entry = {"title": title, "content": clean_content, "category": category}

            logger.info(f"Processed page: {title} (category: {entry['category']})")
            return entry

        except Exception as e:
            logger.error(f"Error processing page: {str(e)}")
            return None

    def process_dump(self):
        """Process the entire wiki dump."""
        logger.info(f"Processing wiki dump from {self.input_file}")

        try:
            # Parse XML
            tree = ET.parse(self.input_file)
            root = tree.getroot()

            # Get all pages
            pages = root.findall(".//mw:page", NS)
            logger.info(f"Found {len(pages)} pages in the dump")

            # Process each page
            processed_count = 0
            for page in pages:
                entry = self.process_page(page)
                if entry:
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
            logger.error(f"Error processing dump: {str(e)}")
            raise

    def save_processed_content(self):
        """Save processed content to JSONL file."""
        total_entries = sum(len(entries) for entries in self.context.values())
        if total_entries == 0:
            logger.warning("No entries to save!")
            return

        with open(self.output_file, "w", encoding="utf-8") as f:
            # Write Bisq 2 content first (most relevant)
            for entry in self.context["bisq2"]:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # Write Bisq 1 content
            for entry in self.context["bisq1"]:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            # Write general content
            for entry in self.context["general"]:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    # Define file paths
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    input_file = os.path.join(project_root, "data", "wiki", "bisq2_dump.xml")
    output_file = os.path.join(project_root, "data", "wiki", "processed_wiki.jsonl")

    # Check if input file exists
    if not os.path.exists(input_file):
        logger.error(f"Input file not found: {input_file}")
        return

    # Process the dump
    processor = WikiDumpProcessor(str(input_file), str(output_file))
    processor.process_dump()


if __name__ == "__main__":
    main()
