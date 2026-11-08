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
    """Build a deterministic wiki page and revision fixture."""
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
    """Install an offline wiki client fixture with selected namespaces."""
    site = SimpleNamespace(
        allpages=Mock(side_effect=lambda namespace: pages[namespace])
    )
    monkeypatch.setattr(downloader.mwclient, "Site", lambda *_, **__: site)
    monkeypatch.setattr(downloader.time, "sleep", lambda _: None)
    return site


def test_export_preserves_templates_redirects_and_exact_revision_text(
    tmp_path, monkeypatch
):
    """Verify export preserves templates redirects and exact revision text."""
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
    """Verify incomplete or invalid export leaves previous snapshot."""
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
    """Verify replacement preserves existing reader permissions."""
    target = tmp_path / "bisq2_dump.xml"
    target.write_bytes(b"previous snapshot")
    target.chmod(0o640)
    install_site(monkeypatch, {0: [page("Trading", "Article")], 10: []})
    downloader.main(str(tmp_path))
    assert target.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize(
    "content",
    [
        "<!-- leading --> #REDIRECT [[Target]]",
        "#REDIRECT: [[Target]]",
        "<!-- a --><!-- b --> #redirect: [[Target]] <!-- tail -->",
    ],
)
def test_export_rejects_comment_or_colon_only_redirect_corpus(
    tmp_path, monkeypatch, content
):
    """Verify export rejects comment or colon only redirect corpus."""
    target = tmp_path / "bisq2_dump.xml"
    target.write_bytes(b"previous snapshot")
    install_site(monkeypatch, {0: [page("Alias", content)], 10: []})
    with pytest.raises(ValueError, match="no non-redirect articles"):
        downloader.main(str(tmp_path))
    assert target.read_bytes() == b"previous snapshot"


def test_export_retains_substantive_redirect_tail_as_article(tmp_path, monkeypatch):
    """Verify export retains substantive redirect tail as article."""
    text = "<!-- before --> #REDIRECT: [[Target]]\n{{Admonition_Warn|Do not overwrite}}\n* Keep backups"
    install_site(monkeypatch, {0: [page("Alias", text)], 10: []})
    downloader.main(str(tmp_path))
    out = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(tmp_path / "bisq2_dump.xml"), str(out)).process_dump()
    row = json.loads(out.read_text())
    assert row["redirect_target"] == "Target"
    assert "Do not overwrite" in row["content"] and "* Keep backups" in row["content"]


@pytest.mark.parametrize(
    "definition",
    ["<!-- only a comment -->", "<noinclude>Documentation only</noinclude>"],
)
def test_export_rejects_article_empty_after_snapshot_template_expansion(
    tmp_path, monkeypatch, definition
):
    """An export must not replace usable XML if its articles render empty."""
    target = tmp_path / "bisq2_dump.xml"
    target.write_bytes(b"previous good snapshot")
    install_site(
        monkeypatch,
        {
            0: [page("Article", "{{Empty}}")],
            10: [page("Template:Empty", definition, 10)],
        },
    )
    with pytest.raises(ValueError, match="no non-redirect articles"):
        downloader.main(str(tmp_path))
    assert target.read_bytes() == b"previous good snapshot"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["bisq2_dump.xml"]


def test_export_accepts_article_populated_only_by_snapshot_template(
    tmp_path, monkeypatch
):
    """A real template expansion is an article even when the raw body is a call."""
    install_site(
        monkeypatch,
        {
            0: [page("Article", "{{Body}}")],
            10: [page("Template:Body", "Useful content", 10, page_id=2)],
        },
    )
    downloader.main(str(tmp_path))
    output = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(tmp_path / "bisq2_dump.xml"), str(output)).process_dump()
    assert json.loads(output.read_text())["content"] == "Useful content"


def test_export_rejects_conflicting_normalized_template_definitions(
    tmp_path, monkeypatch
):
    """Do not publish a snapshot the processor would reject as ambiguous."""
    target = tmp_path / "bisq2_dump.xml"
    target.write_bytes(b"previous snapshot")
    install_site(
        monkeypatch,
        {
            0: [page("Article", "{{Value}}")],
            10: [
                page("Template:Value", "first", 10, page_id=2),
                page("Template:value", "second", 10, page_id=3),
            ],
        },
    )
    with pytest.raises(ValueError, match="Conflicting definitions"):
        downloader.main(str(tmp_path))
    assert target.read_bytes() == b"previous snapshot"


def test_export_does_not_replace_snapshot_updated_during_fetch(tmp_path, monkeypatch):
    """Capture the destination before acquisition so overlapping writers conflict."""
    from app.scripts.wiki_atomic import WikiPublicationConflictError

    target = tmp_path / "bisq2_dump.xml"
    target.write_bytes(b"previous snapshot")
    site = install_site(monkeypatch, {0: [page("Article", "Useful")], 10: []})

    def changed_during_fetch(namespace):
        """Simulate a second completed publisher before our staging begins."""
        if namespace == 0:
            target.write_bytes(b"newer complete snapshot")
            return [page("Article", "Useful")]
        return []

    site.allpages.side_effect = changed_during_fetch
    with pytest.raises(WikiPublicationConflictError):
        downloader.main(str(tmp_path))
    assert target.read_bytes() == b"newer complete snapshot"


def test_export_preserves_post_replace_durability_error(tmp_path, monkeypatch, caplog):
    """A visible replacement with uncertain fsync is not reported as an old file."""
    import stat

    from app.scripts import wiki_atomic

    target = tmp_path / "bisq2_dump.xml"
    target.write_bytes(b"previous snapshot")
    install_site(monkeypatch, {0: [page("Article", "Useful")], 10: []})
    fsync = wiki_atomic.os.fsync
    caplog.set_level("INFO")

    def fail_directory_fsync(fd):
        """Fail the directory sync after rename, not the staged file sync."""
        if stat.S_ISDIR(wiki_atomic.os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        return fsync(fd)

    monkeypatch.setattr(wiki_atomic.os, "fsync", fail_directory_fsync)
    with pytest.raises(wiki_atomic.WikiPublicationDurabilityError) as error:
        downloader.main(str(tmp_path))
    assert error.value.published is True
    assert b"Useful" in target.read_bytes()
    assert "Validated snapshot saved" not in caplog.text
