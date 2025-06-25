import argparse
import html
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import mwclient
import requests

# Set up logging to stdout with debug level
logging.basicConfig(
    level=logging.DEBUG,
    stream=sys.stdout,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


# Function to sanitize XML content
def sanitize_xml_content(content):
    if not content:
        return ""

    # Escape XML special characters
    content = html.escape(content)

    # Fix any other potential XML issues
    # Remove control characters except for whitespace
    content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)

    return content


# Function to extract links from wiki content
def extract_links(content):
    links = []

    # Extract wiki links [[Page Name]]
    wiki_links = re.findall(r'\[\[(.*?)(?:\|.*?)?\]\]', content)
    for link in wiki_links:
        # Remove any section identifiers
        link = link.split('#')[0]
        if link and link not in links:
            links.append(link)

    return links


# Function to determine if a page is related to Bisq 1, Bisq 2, or both
def classify_bisq_version(title, content):
    # Direct Bisq 2 indicators in title
    bisq2_title_indicators = [
        "Bisq 2", "Bisq2", "Bisq_2",
        "Bisq Easy", "Bisq_Easy",
        "Trade_Protocols", "Identity"
    ]

    # Direct Bisq 1 indicators in title
    bisq1_title_indicators = [
        "Bisq 1", "Bisq1", "Bisq_1",
        "Bisq Desktop", "Bisq_Desktop",
        "Bisq DAO", "Bisq_DAO"
    ]

    # Check title for direct indicators
    is_bisq2_in_title = any(
        indicator.lower() in title.lower() for indicator in bisq2_title_indicators)
    is_bisq1_in_title = any(
        indicator.lower() in title.lower() for indicator in bisq1_title_indicators)

    # Check content for references
    bisq2_content_indicators = [
        "Bisq 2", "Bisq2", "Bisq Easy",
        "Trade Protocol", "Identity",
        "Bisq 2 Wallet", "Bisq 2 Roles"
    ]

    bisq1_content_indicators = [
        "Bisq 1", "Bisq1", "Bisq Desktop",
        "Bisq DAO", "Legacy Bisq"
    ]

    # Count references
    bisq2_count = 0
    bisq1_count = 0

    for indicator in bisq2_content_indicators:
        bisq2_count += len(
            re.findall(r'\b' + re.escape(indicator) + r'\b', content, re.IGNORECASE))

    for indicator in bisq1_content_indicators:
        bisq1_count += len(
            re.findall(r'\b' + re.escape(indicator) + r'\b', content, re.IGNORECASE))

    # Determine classification based on title and content
    if is_bisq2_in_title or (bisq2_count > 0 and bisq2_count > bisq1_count):
        return "Bisq 2"
    elif is_bisq1_in_title or (bisq1_count > 0 and bisq1_count > bisq2_count):
        return "Bisq 1"
    elif bisq1_count > 0 and bisq2_count > 0:
        return "Both"
    else:
        # For general pages with no clear indicators, default to "General"
        return "General"


def validate_xml(file_path):
    """Checks if an XML file is well-formed."""
    try:
        ET.parse(file_path)
        return True
    except ET.ParseError as e:
        logging.error(f"XML validation failed: {str(e)}")
        logging.error("The generated XML file has formatting issues.")
        return False


def fetch_page_content(page_title: str) -> dict | None:
    """Fetches the content of a single wiki page via the MediaWiki API."""
    api_url = "https://bisq.wiki/api.php"
    params = {
        'action': 'query',
        'prop': 'revisions',
        'rvprop': 'content|ids|timestamp',
        'titles': page_title,
        'format': 'json'
    }
    try:
        response = requests.get(api_url, params=params)
        logging.debug(f"HTTP status for page '{page_title}': {response.status_code}")
        if response.status_code != 200:
            logging.error(f"Failed to fetch {page_title}: HTTP {response.status_code}")
            return None
        return response.json()
    except Exception as e:
        logging.error(f"Error fetching {page_title}: {e}")
        return None


def process_page_data(page_title: str, data: dict) -> dict | None:
    """Processes the JSON data from the API for a single page."""
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        logging.warning(f"No page data returned for {page_title}")
        return None

    for pageid, pageinfo in pages.items():
        if "missing" in pageinfo:
            logging.warning(f"Page '{page_title}' is missing (might be a redirect or non-existent).")
            continue

        revisions = pageinfo.get("revisions", [])
        if not revisions:
            logging.warning(f"No revisions found for page '{page_title}'")
            continue

        content = revisions[0].get("*", "")
        if not content:
            logging.warning(f"Empty content for page '{page_title}'")
            continue

        title = pageinfo.get("title", "")
        bisq_version = classify_bisq_version(title, content)
        metadata_header = f"""
<!-- BISQ VERSION: {bisq_version} -->
<!-- This page is classified as {bisq_version} content -->

"""
        enhanced_content = metadata_header + content

        return {
            "pageid": pageid,
            "title": title,
            "content": enhanced_content,
            "revision": revisions[0],
            "bisq_version": bisq_version,
            "links": extract_links(content)
        }
    return None


def create_page_element(root: ET.Element, page_info: dict):
    """Creates and appends a <page> XML element to the root."""
    page_element = ET.SubElement(root, 'page')
    ET.SubElement(page_element, 'title').text = page_info["title"]
    ET.SubElement(page_element, 'ns').text = "0"
    ET.SubElement(page_element, 'id').text = str(page_info["pageid"])

    revision_element = ET.SubElement(page_element, 'revision')
    rev_info = page_info["revision"]
    ET.SubElement(revision_element, 'id').text = str(rev_info.get("revid", ""))
    ET.SubElement(revision_element, 'timestamp').text = rev_info.get("timestamp", "")

    # Add contributor section (can be simplified if not needed)
    contributor = ET.SubElement(revision_element, 'contributor')
    ET.SubElement(contributor, 'username').text = "downloader"
    ET.SubElement(contributor, 'id').text = "0"

    ET.SubElement(revision_element, 'comment').text = "Downloaded by script"
    ET.SubElement(revision_element, 'model').text = "wikitext"
    ET.SubElement(revision_element, 'format').text = "text/x-wiki"

    text_element = ET.SubElement(revision_element, 'text', attrib={"xml:space": "preserve"})
    text_element.text = sanitize_xml_content(page_info["content"])


def main(output_dir):
    logging.info("Connecting to Bisq Wiki via mwclient...")
    site = mwclient.Site('bisq.wiki', path='/')

    # Start with the Bisq 2 page
    start_page = "Bisq 2"
    pages_to_process = [start_page]
    processed_pages = set()
    all_pages = {}

    # Create the root element for the XML dump.
    mediawiki_root = ET.Element('mediawiki', attrib={
        'xmlns': "http://www.mediawiki.org/xml/export-0.10/",
        'version': "0.10",
        'xml:lang': "en"
    })

    # Add siteinfo section to make it compatible with mwxml parser
    siteinfo = ET.SubElement(mediawiki_root, 'siteinfo')
    ET.SubElement(siteinfo, 'sitename').text = "Bisq Wiki"
    ET.SubElement(siteinfo, 'dbname').text = "bisq_wiki"
    ET.SubElement(siteinfo, 'base').text = "https://bisq.wiki/"
    ET.SubElement(siteinfo, 'generator').text = "MediaWiki 1.35.0"
    ET.SubElement(siteinfo, 'case').text = "first-letter"

    # Add namespaces
    namespaces = ET.SubElement(siteinfo, 'namespaces')
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
        ("15", "Category talk")
    ]

    for key, name in namespace_data:
        ns = ET.SubElement(namespaces, 'namespace',
                           attrib={"key": key, "case": "first-letter"})
        ns.text = name

    # Process pages in a breadth-first manner
    while pages_to_process:
        current_page = pages_to_process.pop(0)

        if current_page in processed_pages:
            continue

        logging.info(f"Processing page: {current_page}")
        processed_pages.add(current_page)

        data = fetch_page_content(current_page)
        if not data:
            continue

        page_info = process_page_data(current_page, data)
        if not page_info:
            continue

        all_pages[current_page] = page_info

        # Add new links to the processing queue
        for link in page_info["links"]:
            if link not in processed_pages and link not in pages_to_process:
                pages_to_process.append(link)

        # Allow for a small delay to avoid being blocked
        time.sleep(1)

    logging.info(f"Finished processing {len(all_pages)} unique pages.")

    # Sort pages by title for consistent output
    sorted_titles = sorted(all_pages.keys())

    # Add all processed pages to the XML tree
    for title in sorted_titles:
        page_info = all_pages[title]
        create_page_element(mediawiki_root, page_info)

    # Save the XML file
    output_filename = os.path.join(output_dir, "bisq2_dump.xml")
    tree = ET.ElementTree(mediawiki_root)
    tree.write(output_filename, encoding='utf-8', xml_declaration=True)

    logging.info(f"File saved as {output_filename}")

    # Verify the XML file is well-formed
    if validate_xml(output_filename):
        logging.info(
            "XML validation successful: The generated XML file is well-formed.")
    else:
        logging.error("The generated XML file has formatting issues.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download and process Bisq MediaWiki content.")
    parser.add_argument("--output-dir", default=".",
                        help="The directory to save the output XML files.")
    args = parser.parse_args()
    main(args.output_dir)
