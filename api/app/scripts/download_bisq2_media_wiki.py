import argparse
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import mwclient

# Set up logging to stdout with debug level
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# Function to extract links from wiki content
def extract_links(content):
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
def classify_bisq_version(title, content):
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


def main(output_dir):
    """Main function to download and process wiki content."""
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

    # Use mwclient to iterate over all pages
    page_count = 0
    for page in site.allpages():
        if page.namespace != 0:  # Skip non-main pages
            continue

        page_count += 1
        logging.info(f"Processing page {page_count}: {page.name}")

        try:
            content = page.text()
            if not content or content.lower().startswith("#redirect"):
                logging.debug(f"Skipping empty or redirect page: {page.name}")
                continue

            # Classify content
            bisq_version = classify_bisq_version(page.name, content)

            # Create XML element for the page
            page_element = ET.SubElement(mediawiki_root, "page")
            ET.SubElement(page_element, "title").text = page.name
            ET.SubElement(page_element, "ns").text = str(page.namespace)
            ET.SubElement(page_element, "id").text = str(page.pageid)

            revision = page.revisions(prop="ids|timestamp|comment|user").__next__()
            revision_element = ET.SubElement(page_element, "revision")
            ET.SubElement(revision_element, "id").text = str(revision["revid"])
            ts = revision["timestamp"]
            formatted_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", ts)
            ET.SubElement(revision_element, "timestamp").text = formatted_ts

            contributor = ET.SubElement(revision_element, "contributor")
            ET.SubElement(contributor, "username").text = revision.get(
                "user", "downloader"
            )
            ET.SubElement(contributor, "id").text = str(revision.get("userid", "0"))

            ET.SubElement(revision_element, "comment").text = revision.get(
                "comment", "Downloaded by script"
            )
            ET.SubElement(revision_element, "model").text = "wikitext"
            ET.SubElement(revision_element, "format").text = "text/x-wiki"

            text_element = ET.SubElement(
                revision_element, "text", attrib={"xml:space": "preserve"}
            )

            # The text of the element must be set *after* the comment is appended.
            comment_text = f"<!-- BISQ VERSION: {bisq_version} -->"
            text_element.text = content + comment_text

        except Exception as e:
            logging.error(f"Error processing page {page.name}: {e}")

        # Small delay to avoid overwhelming the server
        time.sleep(0.1)

    logging.info(f"Finished processing {page_count} pages.")

    # Ensure the output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Save the XML file
    output_filename = os.path.join(output_dir, "bisq2_dump.xml")
    tree = ET.ElementTree(mediawiki_root)
    ET.indent(tree, space="  ")  # Pretty-print the XML
    tree.write(output_filename, encoding="utf-8", xml_declaration=True)

    logging.info(f"File saved as {output_filename}")

    # Verify the XML file is well-formed
    if validate_xml(output_filename):
        logging.info("XML validation successful.")
    else:
        logging.error("The generated XML file has formatting issues.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download and process Bisq MediaWiki content."
    )
    parser.add_argument(
        "--output-dir", default=".", help="The directory to save the output XML files."
    )
    args = parser.parse_args()
    main(args.output_dir)
