import argparse
import logging
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

import mwclient  # type: ignore[import-untyped]
from app.scripts.wiki_atomic import capture_wiki_preimage, replace_wiki_file
from app.scripts.wiki_text import WikiTextRenderer, redirect_directive, template_key

# Set up logging to stdout with debug level
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# Function to extract links from wiki content
def extract_links(content: str) -> list[str]:
    """Extract wiki links from MediaWiki content.

    Args:
        content: Raw wiki content text

    Returns:
        List of unique page names referenced in the content
    """
    links = []

    # Extract wiki links [[Page Name]]
    wiki_links = re.findall(r"\[\[(.*?)(?:\|.*?)?\]\]", content)
    for link in wiki_links:
        # Remove any section identifiers
        link = link.split("#")[0]
        if link and link not in links:
            links.append(link)

    return links


# Function to determine if a page is related to Bisq 1, Bisq 2, or both
def classify_bisq_version(title: str, content: str) -> str:
    """Classify wiki page as relating to Bisq 1, Bisq 2, or general content.

    Args:
        title: Page title
        content: Page content text

    Returns:
        Classification string: 'bisq1', 'bisq2', or 'general'
    """
    # Direct Bisq 2 indicators in title
    bisq2_title_indicators = [
        "Bisq 2",
        "Bisq2",
        "Bisq_2",
        "Bisq Easy",
        "Bisq_Easy",
        "Trade_Protocols",
        "Identity",
    ]

    # Direct Bisq 1 indicators in title
    bisq1_title_indicators = [
        "Bisq 1",
        "Bisq1",
        "Bisq_1",
        "Bisq Desktop",
        "Bisq_Desktop",
        "Bisq DAO",
        "Bisq_DAO",
    ]

    # Check title for direct indicators
    is_bisq2_in_title = any(
        indicator.lower() in title.lower() for indicator in bisq2_title_indicators
    )
    is_bisq1_in_title = any(
        indicator.lower() in title.lower() for indicator in bisq1_title_indicators
    )

    # Check content for references
    bisq2_content_indicators = [
        "Bisq 2",
        "Bisq2",
        "Bisq Easy",
        "Trade Protocol",
        "Identity",
        "Bisq 2 Wallet",
        "Bisq 2 Roles",
    ]

    bisq1_content_indicators = [
        "Bisq 1",
        "Bisq1",
        "Bisq Desktop",
        "Bisq DAO",
        "Legacy Bisq",
    ]

    # Count references
    bisq2_count = 0
    bisq1_count = 0

    for indicator in bisq2_content_indicators:
        bisq2_count += len(
            re.findall(r"\b" + re.escape(indicator) + r"\b", content, re.IGNORECASE)
        )

    for indicator in bisq1_content_indicators:
        bisq1_count += len(
            re.findall(r"\b" + re.escape(indicator) + r"\b", content, re.IGNORECASE)
        )

    # Determine classification based on title and content
    if is_bisq1_in_title or (bisq1_count > 0 and bisq1_count > bisq2_count):
        return "bisq1"
    if is_bisq2_in_title or (bisq2_count > 0 and bisq2_count > bisq1_count):
        return "bisq2"
    return "general"


def validate_xml(file_path: str) -> bool:
    """Checks if an XML file is well-formed."""
    try:
        ET.parse(file_path)
        return True
    except ET.ParseError as e:
        logging.error(f"XML validation failed: {str(e)}")
        logging.error("The generated XML file has formatting issues.")
        return False


def main(output_dir: str) -> None:
    """Main function to download and process wiki content.

    Args:
        output_dir: Directory path where the XML dump will be saved
    """
    output_filename = os.path.abspath(os.path.join(output_dir, "bisq2_dump.xml"))
    preimage = capture_wiki_preimage(output_filename)
    logging.info("Connecting to Bisq Wiki via mwclient...")
    site = mwclient.Site("bisq.wiki", path="/")

    # Create the root element for the XML dump.
    mediawiki_root = ET.Element(
        "mediawiki",
        attrib={
            "xmlns": "http://www.mediawiki.org/xml/export-0.10/",
            "version": "0.10",
            "xml:lang": "en",
        },
    )

    # Add siteinfo section to make it compatible with mwxml parser
    siteinfo = ET.SubElement(mediawiki_root, "siteinfo")
    ET.SubElement(siteinfo, "sitename").text = "Bisq Wiki"
    ET.SubElement(siteinfo, "dbname").text = "bisq_wiki"
    ET.SubElement(siteinfo, "base").text = "https://bisq.wiki/"
    ET.SubElement(siteinfo, "generator").text = "MediaWiki 1.35.0"
    ET.SubElement(siteinfo, "case").text = "first-letter"

    namespaces = ET.SubElement(siteinfo, "namespaces")
    namespace_data = [
        ("-2", "Media"),
        ("-1", "Special"),
        ("0", ""),
        ("1", "Talk"),
        ("2", "User"),
        ("3", "User talk"),
        ("4", "Project"),
        ("5", "Project talk"),
        ("6", "File"),
        ("7", "File talk"),
        ("8", "MediaWiki"),
        ("9", "MediaWiki talk"),
        ("10", "Template"),
        ("11", "Template talk"),
        ("12", "Help"),
        ("13", "Help talk"),
        ("14", "Category"),
        ("15", "Category talk"),
    ]
    for key, name in namespace_data:
        ns = ET.SubElement(
            namespaces, "namespace", attrib={"key": key, "case": "first-letter"}
        )
        ns.text = name

    # Keep redirect aliases and template definitions alongside article sources.
    # Read content and revision metadata together so they describe the same edit.
    page_count = 0
    article_bodies = []
    templates = {}
    normalized_templates = {}
    for namespace in (0, 10):
        for page in site.allpages(namespace=namespace):
            if page.namespace != namespace:
                raise ValueError(f"Unexpected namespace for {page.name}")
            try:
                revision = next(
                    page.revisions(
                        prop="ids|timestamp|comment|user|userid|content",
                        slots="main",
                        api_chunk_size=1,
                    )
                )
                content = (
                    revision["slots"]["main"]["*"]
                    if "slots" in revision
                    else revision["*"]
                )
                if not isinstance(content, str):
                    raise ValueError("Missing readable revision content")
                redirect = redirect_directive(content)
                page_element = ET.SubElement(mediawiki_root, "page")
                ET.SubElement(page_element, "title").text = page.name
                ET.SubElement(page_element, "ns").text = str(page.namespace)
                ET.SubElement(page_element, "id").text = str(page.pageid)
                if redirect:
                    ET.SubElement(
                        page_element,
                        "redirect",
                        attrib={"title": redirect.group(1).split("|", 1)[0].strip()},
                    )
                revision_element = ET.SubElement(page_element, "revision")
                ET.SubElement(revision_element, "id").text = str(revision["revid"])
                ET.SubElement(revision_element, "timestamp").text = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", revision["timestamp"]
                )
                contributor = ET.SubElement(revision_element, "contributor")
                ET.SubElement(contributor, "username").text = revision.get("user", "")
                ET.SubElement(contributor, "id").text = str(revision.get("userid", "0"))
                ET.SubElement(revision_element, "comment").text = revision.get(
                    "comment", ""
                )
                ET.SubElement(revision_element, "model").text = "wikitext"
                ET.SubElement(revision_element, "format").text = "text/x-wiki"
                ET.SubElement(
                    revision_element, "text", attrib={"xml:space": "preserve"}
                ).text = content
                page_count += 1
                if namespace == 0:
                    article_body = content[redirect.end() :] if redirect else content
                    article_bodies.append(article_body)
                else:
                    key = template_key(page.name)
                    if (
                        key in normalized_templates
                        and normalized_templates[key] != content
                    ):
                        raise ValueError(f"Conflicting definitions for Template:{key}")
                    normalized_templates[key] = content
                    templates[page.name] = content
            except Exception:
                # A well-formed but partial export must not replace a good snapshot.
                logging.exception(
                    "Failed to capture page %s; snapshot unchanged", page.name
                )
                raise
            time.sleep(0.1)

    article_count = sum(
        bool(WikiTextRenderer(templates).render(body).text.strip())
        for body in article_bodies
    )
    if not article_count:
        raise ValueError("Wiki export contains no non-redirect articles")
    logging.info("Captured %s pages, including %s articles", page_count, article_count)
    os.makedirs(output_dir, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_dir, prefix=".wiki-", suffix=".xml", delete=False
        ) as handle:
            temporary = handle.name
            tree = ET.ElementTree(mediawiki_root)
            ET.indent(tree, space="  ")
            tree.write(handle, encoding="utf-8", xml_declaration=True)
            handle.flush()
            os.fsync(handle.fileno())
        if not validate_xml(temporary):
            raise ValueError("Generated wiki XML failed validation")
        replace_wiki_file(temporary, output_filename, expected_preimage=preimage)
        temporary = None
        logging.info("Validated snapshot saved as %s", output_filename)
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                # A completed rename followed by an fsync error consumes the
                # staged path and must retain its durability-uncertain error.
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download and process Bisq MediaWiki content."
    )
    parser.add_argument(
        "--output-dir", default=".", help="The directory to save the output XML files."
    )
    args = parser.parse_args()
    main(args.output_dir)
