import mwclient
import requests
import xml.etree.ElementTree as ET
import time
import sys
import logging
import os
import html
import re
from bs4 import BeautifulSoup
from urllib.parse import unquote

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
    is_bisq2_in_title = any(indicator.lower() in title.lower() for indicator in bisq2_title_indicators)
    is_bisq1_in_title = any(indicator.lower() in title.lower() for indicator in bisq1_title_indicators)
    
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
        bisq2_count += len(re.findall(r'\b' + re.escape(indicator) + r'\b', content, re.IGNORECASE))
    
    for indicator in bisq1_content_indicators:
        bisq1_count += len(re.findall(r'\b' + re.escape(indicator) + r'\b', content, re.IGNORECASE))
    
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
    ns = ET.SubElement(namespaces, 'namespace', attrib={"key": key, "case": "first-letter"})
    ns.text = name

api_url = "https://bisq.wiki/api.php"

# Process pages in a breadth-first manner
while pages_to_process:
    current_page = pages_to_process.pop(0)
    
    # Skip if already processed
    if current_page in processed_pages:
        continue
    
    logging.info(f"Processing page: {current_page}")
    processed_pages.add(current_page)
    
    # Fetch page content
    params = {
        'action': 'query',
        'prop': 'revisions',
        'rvprop': 'content|ids|timestamp',
        'titles': current_page,
        'format': 'json'
    }
    
    try:
        response = requests.get(api_url, params=params)
        logging.debug(f"HTTP status for page '{current_page}': {response.status_code}")
        if response.status_code != 200:
            logging.error(f"Failed to fetch {current_page}: HTTP {response.status_code}")
            continue
        data = response.json()
    except Exception as e:
        logging.error(f"Error fetching {current_page}: {e}")
        continue
    
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        logging.warning(f"No page data returned for {current_page}")
        continue
    
    for pageid, pageinfo in pages.items():
        if "missing" in pageinfo:
            logging.warning(f"Page '{current_page}' is missing (might be a redirect or non-existent).")
            continue
        
        # Get content
        revisions = pageinfo.get("revisions", [])
        if not revisions:
            logging.warning(f"No revisions found for page '{current_page}'")
            continue
        
        content = revisions[0].get("*", "")
        if not content:
            logging.warning(f"Empty content for page '{current_page}'")
            continue
        
        # Classify the page
        title = pageinfo.get("title", "")
        bisq_version = classify_bisq_version(title, content)
        
        # Add a clear metadata header to the content
        metadata_header = f"""
<!-- BISQ VERSION: {bisq_version} -->
<!-- This page is classified as {bisq_version} content -->

"""
        enhanced_content = metadata_header + content
        
        # Store page info
        all_pages[current_page] = {
            "pageid": pageid,
            "title": title,
            "content": enhanced_content,
            "revision": revisions[0],
            "bisq_version": bisq_version
        }
        
        logging.info(f"Classified '{title}' as '{bisq_version}' content")
        
        # Extract links from content and add to processing queue
        links = extract_links(content)
        logging.info(f"Found {len(links)} links in page '{current_page}'")
        
        for link in links:
            if link not in processed_pages and link not in pages_to_process:
                pages_to_process.append(link)
    
    # Short pause to avoid overwhelming the server
    time.sleep(0.5)

# Now create XML elements for all processed pages
logging.info(f"Creating XML elements for {len(all_pages)} pages...")
bisq2_count = 0
bisq1_count = 0
both_count = 0
general_count = 0

for title, page_data in all_pages.items():
    page_el = ET.Element('page')
    ET.SubElement(page_el, 'title').text = page_data["title"]
    
    # Set the correct namespace based on the title prefix
    title = page_data["title"]
    if title.startswith("File:"):
        ET.SubElement(page_el, 'ns').text = "6"  # File namespace
    elif title.startswith("Category:"):
        ET.SubElement(page_el, 'ns').text = "14"  # Category namespace
    else:
        ET.SubElement(page_el, 'ns').text = "0"  # Main namespace
    
    ET.SubElement(page_el, 'id').text = page_data["pageid"]
    
    # Add custom element for Bisq version
    bisq_version_el = ET.SubElement(page_el, 'bisq_version')
    bisq_version_el.text = page_data["bisq_version"]
    
    # Update counters
    if page_data["bisq_version"] == "Bisq 2":
        bisq2_count += 1
    elif page_data["bisq_version"] == "Bisq 1":
        bisq1_count += 1
    elif page_data["bisq_version"] == "Both":
        both_count += 1
    else:
        general_count += 1
    
    rev = page_data["revision"]
    rev_el = ET.SubElement(page_el, 'revision')
    ET.SubElement(rev_el, 'id').text = str(rev.get("revid", ""))
    ET.SubElement(rev_el, 'timestamp').text = rev.get("timestamp", "")
    
    # Sanitize content
    sanitized_content = sanitize_xml_content(page_data["content"])
    
    text_el = ET.SubElement(rev_el, 'text', attrib={"xml:space": "preserve"})
    text_el.text = sanitized_content
    
    mediawiki_root.append(page_el)

# Write out the combined XML dump.
output_dir = os.path.join("api", "data", "wiki")
os.makedirs(output_dir, exist_ok=True)
output_file = os.path.join(output_dir, "bisq_dump_with_metadata.xml")

# Use a custom function to write the XML to ensure proper formatting
def write_xml_with_declaration(tree, file_path):
    # First convert to string with proper indentation
    xml_string = ET.tostring(tree.getroot(), encoding='utf-8', method='xml')
    
    # Add XML declaration
    xml_declaration = '<?xml version="1.0" encoding="utf-8"?>\n'
    
    # Write to file
    with open(file_path, 'wb') as f:
        f.write(xml_declaration.encode('utf-8'))
        f.write(xml_string)

tree = ET.ElementTree(mediawiki_root)
write_xml_with_declaration(tree, output_file)

logging.info(f"Dump complete. Found {len(all_pages)} total pages:")
logging.info(f"- Bisq 2 related: {bisq2_count}")
logging.info(f"- Bisq 1 related: {bisq1_count}")
logging.info(f"- Both versions: {both_count}")
logging.info(f"- General content: {general_count}")
logging.info(f"File saved as {output_file}")

# Verify the XML file is well-formed
try:
    ET.parse(output_file)
    logging.info("XML validation successful: The generated XML file is well-formed.")
except ET.ParseError as e:
    logging.error(f"XML validation failed: {str(e)}")
    logging.error("The generated XML file has formatting issues. Please check and fix manually.")

# Also create a Bisq 2 only version
bisq2_root = ET.Element('mediawiki', attrib={
    'xmlns': "http://www.mediawiki.org/xml/export-0.10/",
    'version': "0.10",
    'xml:lang': "en"
})

# Copy the siteinfo section
bisq2_root.append(siteinfo)

# Add only Bisq 2 and relevant general pages
bisq2_only_count = 0
for title, page_data in all_pages.items():
    if page_data["bisq_version"] in ["Bisq 2", "Both", "General"]:
        # For pages that cover both, add a note that this is filtered for Bisq 2
        if page_data["bisq_version"] == "Both":
            enhanced_content = page_data["content"].replace(
                "<!-- BISQ VERSION: Both -->", 
                "<!-- BISQ VERSION: Bisq 2 (filtered from content covering both versions) -->"
            )
            page_data["content"] = enhanced_content
        
        # Copy the page element
        for page_el in mediawiki_root.findall(".//page"):
            if page_el.find("title").text == page_data["title"]:
                bisq2_root.append(page_el)
                bisq2_only_count += 1
                break

# Write out the Bisq 2 only XML dump
bisq2_output_file = os.path.join(output_dir, "bisq2_dump.xml")
bisq2_tree = ET.ElementTree(bisq2_root)
write_xml_with_declaration(bisq2_tree, bisq2_output_file)

logging.info(f"Bisq 2 only dump complete. Included {bisq2_only_count} pages.")
logging.info(f"File saved as {bisq2_output_file}")

# Verify the Bisq 2 XML file is well-formed
try:
    ET.parse(bisq2_output_file)
    logging.info("Bisq 2 XML validation successful: The generated XML file is well-formed.")
except ET.ParseError as e:
    logging.error(f"Bisq 2 XML validation failed: {str(e)}")
    logging.error("The generated XML file has formatting issues. Please check and fix manually.") 