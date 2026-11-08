"""Offline export tests: capture dependencies without losing a good snapshot."""

import json
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.scripts import download_bisq2_media_wiki as downloader
from app.scripts.process_wiki_dump import WikiDumpProcessor

pytestmark = pytest.mark.unit
NS = {"m": "http://www.mediawiki.org/xml/export-0.10/"}


def page(title, text, namespace=0, *, legacy=False, page_id=1):
    revision = {
        "revid": 41 + page_id,
        "timestamp": time.gmtime(0),
        "user": "Example",
        "userid": 7,
        "comment": "edit",
    }
    revision.update({"*": text} if legacy else {"slots": {"main": {"*": text}}})
    return SimpleNamespace(
        name=title,
        namespace=namespace,
        pageid=page_id,
        revisions=Mock(side_effect=lambda **_: iter([revision])),
    )


def install_site(monkeypatch, pages):
    site = SimpleNamespace(
        allpages=Mock(side_effect=lambda namespace: pages[namespace])
    )
    monkeypatch.setattr(downloader.mwclient, "Site", lambda *_, **__: site)
    monkeypatch.setattr(downloader.time, "sleep", lambda _: None)
    return site


def test_export_preserves_templates_redirects_and_exact_revision_text(
    tmp_path, monkeypatch
):
    text = "Before {{Admonition_Warn|Keep this warning.}} after.\n"
    article = page("Trading", text)
    alias = page("Old title", " #REDIRECT [[Trading#Safety]]", legacy=True, page_id=2)
    template = page("Template:Limit", "0.01<noinclude>docs</noinclude>", 10, page_id=3)
    site = install_site(monkeypatch, {0: [article, alias], 10: [template]})

    downloader.main(str(tmp_path))

    root = ET.parse(tmp_path / "bisq2_dump.xml").getroot()
    entries = root.findall("m:page", NS)
    assert [p.findtext("m:title", namespaces=NS) for p in entries] == [
        "Trading",
        "Old title",
        "Template:Limit",
    ]
    assert entries[0].findtext("m:revision/m:text", namespaces=NS) == text
    assert entries[0].findtext("m:revision/m:id", namespaces=NS) == "42"
    assert entries[1].find("m:redirect", NS).get("title") == "Trading#Safety"
    assert (
        entries[2].findtext("m:revision/m:text", namespaces=NS)
        == "0.01<noinclude>docs</noinclude>"
    )
    assert [call.kwargs for call in site.allpages.call_args_list] == [
        {"namespace": 0},
        {"namespace": 10},
    ]
    article.revisions.assert_called_once_with(
        prop="ids|timestamp|comment|user|userid|content", slots="main", api_chunk_size=1
    )

    processed = tmp_path / "processed_wiki.jsonl"
    WikiDumpProcessor(str(tmp_path / "bisq2_dump.xml"), str(processed)).process_dump()
    rows = list(map(json.loads, processed.read_text().splitlines()))
    assert [row["title"] for row in rows] == ["Trading"]
    assert "Keep this warning." in rows[0]["content"]


@pytest.mark.parametrize("failure", ["page", "empty", "validation", "template-list"])
def test_incomplete_or_invalid_export_leaves_previous_snapshot(
    tmp_path, monkeypatch, failure
):
    target = tmp_path / "bisq2_dump.xml"
    target.write_bytes(b"previous good snapshot")
    good = page("Trading", "Article content")
    broken = page("Unavailable", "")
    broken.revisions.side_effect = RuntimeError("unavailable revision")
    pages = {0: [good, broken] if failure == "page" else [good], 10: []}
    if failure == "empty":
        pages[0] = [page("Alias", "#REDIRECT [[Missing]]")]
    site = install_site(monkeypatch, pages)
    if failure == "validation":
        monkeypatch.setattr(downloader, "validate_xml", lambda _: False)
    if failure == "template-list":
        site.allpages.side_effect = lambda namespace: (
            [good]
            if namespace == 0
            else (_ for _ in ()).throw(RuntimeError("template listing failed"))
        )

    with pytest.raises((RuntimeError, ValueError)):
        downloader.main(str(tmp_path))

    assert target.read_bytes() == b"previous good snapshot"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bisq2_dump.xml"]


def test_replacement_preserves_existing_reader_permissions(tmp_path, monkeypatch):
    target = tmp_path / "bisq2_dump.xml"
    target.write_bytes(b"previous snapshot")
    target.chmod(0o640)
    install_site(monkeypatch, {0: [page("Trading", "Article")], 10: []})
    downloader.main(str(tmp_path))
    assert target.stat().st_mode & 0o777 == 0o640
