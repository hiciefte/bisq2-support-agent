"""Offline parser regressions; no API services or persisted KB are loaded."""

import json
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from app.scripts.process_wiki_dump import WikiDumpProcessor, coalesce_pages
from app.scripts.wiki_text import WikiTextRenderer
from app.services.wiki_service import WikiService

pytestmark = pytest.mark.unit


def test_repeated_spaces_and_explicit_template_colons_resolve():
    """Verify repeated spaces and explicit template colons resolve."""
    renderer = WikiTextRenderer(
        {"Template:Trade limit": "0.01 BTC", "Template:Payment:Limit": "method limit"}
    )
    result = renderer.render("{{Trade__limit}} {{Template:Payment:Limit}}")
    assert result.text == "0.01 BTC method limit"
    assert not result.source_gaps
    assert (
        "non-template transclusion unsupported"
        in renderer.render("{{Payment:Limit}}").text
    )


def test_preflight_ignores_noinclude_and_literal_examples_but_not_active_code():
    """Verify preflight ignores noinclude and literal examples but not active code."""
    renderer = WikiTextRenderer(
        {
            "Limit": "<noinclude>{{#if:documentation|unrelated}}</noinclude>0.01 BTC",
            "Literal": "<code><noinclude>{{#if:example|exact}}</noinclude></code>",
            "Active": "{{#if:condition|unsupported}}0.01 BTC",
        }
    )
    assert renderer.render("{{Limit}}").text == "0.01 BTC"
    assert not renderer.render("{{Limit}}").source_gaps
    assert (
        "<noinclude>{{#if:example|exact}}</noinclude>"
        in renderer.render("{{Literal}}").text
    )
    assert "unsupported constructs" in renderer.render("{{Active}}").text


@pytest.mark.parametrize("prefix", ["", "<!-- leading -->", "<!-- a --><!-- b -->\n"])
def test_template_redirect_after_comments_is_explicitly_unresolved(prefix):
    """Verify template redirect after comments is explicitly unresolved."""
    result = WikiTextRenderer({"Limit": prefix + "#REDIRECT: [[Other]]"}).render(
        "Before {{Limit}} after"
    )
    assert (
        result.source_gaps[0]["reason"]
        == "redirect definition Template:Limit unsupported"
    )
    assert "{{Limit}}" in result.text and result.text.endswith(" after")


def test_includeonly_is_hidden_on_direct_article_but_visible_when_transcluded():
    """Verify includeonly is hidden on direct article but visible when transcluded."""
    body = "Shown<includeonly>transclusion only</includeonly><noinclude>direct only</noinclude>"
    renderer = WikiTextRenderer({"Example": body})
    assert renderer.render(body).text == "Showndirect only"
    assert renderer.render("{{Example}}").text == "Showntransclusion only"


def test_nested_missing_fallback_is_bounded_with_original_call_retained_once():
    """Verify nested missing fallback is bounded with original call retained once."""
    call = "{{Unknown|" * 80 + "Never reveal the seed" + "}}" * 80
    result = WikiTextRenderer().render(call + "\nAfter")
    assert call in result.text and result.text.endswith("After")
    assert "fallback traversal stopped" in result.text
    assert len(result.source_gaps) <= WikiTextRenderer.MAX_FALLBACK_DEPTH + 1
    assert sum("invocation" in gap for gap in result.source_gaps) == 1
    assert all("invocation_sha256" in gap for gap in result.source_gaps[1:])
    assert len(result.text) < len(call) + 5000


def test_substituted_argument_bytes_exceed_budget_after_definition_fits():
    """Verify substituted argument bytes exceed budget after definition fits."""
    renderer = WikiTextRenderer({"Repeat": "{{{1}}}" * 10})
    renderer.MAX_EXPANSION_BYTES = 200
    call = "{{Repeat|keep this warning}}"
    assert len(renderer.templates["Repeat"].encode()) + len(call.encode()) < 200
    result = renderer.render(call + "\nAfter")
    assert result.source_gaps[0]["reason"] == "template expansion budget exceeded"
    assert call in result.text and result.text.endswith("After")


@pytest.mark.parametrize(
    "budget", ["MAX_SOURCE_BYTES", "MAX_RENDER_BYTES", "MAX_RENDER_NODES"]
)
def test_total_render_limits_fail_closed_instead_of_publishing_partial(
    tmp_path, monkeypatch, budget
):
    """Verify total render limits fail closed instead of publishing partial."""
    source = write_dump(
        tmp_path, [("Safety", 0, "Before {{Missing|Keep original}} After")]
    )
    output = tmp_path / "processed.jsonl"
    output.write_text("existing complete corpus")
    monkeypatch.setattr(WikiTextRenderer, budget, 1)
    with pytest.raises(ValueError, match="budget"):
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert output.read_text() == "existing complete corpus"


def test_classification_uses_expanded_template_prose_and_reviewed_override(tmp_path):
    """Verify classification uses expanded template prose and reviewed override."""
    source = write_dump(
        tmp_path,
        [
            ("Checklist", 0, "{{Easy}}"),
            ("Funding your wallet", 0, "{{Easy}}"),
            ("Introduction", 0, "Classic Bisq 1 arbitration and {{Easy}}"),
            ("Template:Easy", 10, "Bisq Easy setup and Bisq 2 protocol"),
        ],
    )
    output = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(source), str(output)).process_dump()
    rows = {
        row["title"]: row for row in map(json.loads, output.read_text().splitlines())
    }
    assert rows["Checklist"]["category"] == "bisq2"
    assert rows["Funding your wallet"]["category"] == "bisq1"
    assert rows["Introduction"]["category"] == "general"


def test_identical_repeated_page_blocks_preserve_xml_only_redirect_marker(tmp_path):
    """Verify identical repeated page blocks preserve xml only redirect marker."""
    source = write_dump(tmp_path, [("Alias", 0, "Substantive body without directive")])
    tree = ET.parse(source)
    ns = {"mw": "http://www.mediawiki.org/xml/export-0.10/"}
    page = tree.getroot().find("mw:page", ns)
    ET.SubElement(page, "{" + ns["mw"] + "}id").text = "7"
    ET.SubElement(page, "{" + ns["mw"] + "}redirect", title="Target")
    revision = page.find("mw:revision", ns)
    ET.SubElement(revision, "{" + ns["mw"] + "}id").text = "1"
    ET.SubElement(revision, "{" + ns["mw"] + "}timestamp").text = "2026-01-01T00:00:00Z"
    pages = coalesce_pages([page, deepcopy(page)], ns)
    processor = WikiDumpProcessor(str(source), str(tmp_path / "out"))
    assert processor.process_page(pages[0])["redirect_target"] == "Target"
    changed = deepcopy(page)
    changed.find("mw:revision/mw:id", ns).text = "2"
    changed.find("mw:revision/mw:timestamp", ns).text = "2026-01-02T00:00:00Z"
    changed.find("mw:revision/mw:text", ns).text = "New nonredirect body"
    changed.remove(changed.find("mw:redirect", ns))
    for order in ([page, changed], [changed, page]):
        assert "redirect_target" not in processor.process_page(
            coalesce_pages(order, ns)[0]
        )


def test_conflicting_redirect_markers_for_same_revision_fail_closed(tmp_path):
    """Reject inconsistent redirect metadata rather than selecting by order."""
    source = write_dump(tmp_path, [("Alias", 0, "Body")])
    ns = {"mw": "http://www.mediawiki.org/xml/export-0.10/"}
    page = ET.parse(source).getroot().find("mw:page", ns)
    ET.SubElement(page, "{" + ns["mw"] + "}id").text = "7"
    ET.SubElement(page, "{" + ns["mw"] + "}redirect", title="Target A")
    other = deepcopy(page)
    other.find("mw:redirect", ns).set("title", "Target B")
    for order in ([page, other], [other, page]):
        with pytest.raises(ValueError, match="Conflicting redirect"):
            coalesce_pages(order, ns)


def test_real_warning_and_note_arguments_survive_missing_definitions():
    # Actual source calls from SEPA Instant and Downloading and installing.
    """Verify real warning and note arguments survive missing definitions."""
    source = (
        "{{Admonition_Warn|Please send payment only to the details provided by "
        "the BTC Seller in their Bisq account. Please leave the payment description blank.}}\n"
        "{{Admonition_Note|See [[#OS-specific_install_notes|install notes for various Linux distributions below]].}}"
    )
    result = WikiTextRenderer().render(source)
    assert "Please leave the payment description blank." in result.text
    assert "install notes for various Linux distributions below" in result.text
    assert [gap["template"] for gap in result.source_gaps] == [
        "Admonition_Warn",
        "Admonition_Note",
    ]
    assert all(gap["invocation"] in source for gap in result.source_gaps)
    assert "Warning: Please send payment only" in result.text
    assert (
        "Note: See install notes for various Linux distributions below." in result.text
    )
    assert all(gap["kind"] == "presentation_wrapper_only" for gap in result.source_gaps)


def test_warning_prose_remains_contiguous_but_external_urls_are_not_lost():
    """Verify warning prose remains contiguous but external urls are not lost."""
    result = WikiTextRenderer().render(
        "{{Admonition Warn|Do not [[Share|reveal]] your seed on [https://example.invalid/ any website].}}"
    )
    assert "Warning: Do not reveal your seed on any website." in result.text
    assert "any website: https://example.invalid/" in result.text


def test_unknown_arguments_have_readable_prose_as_well_as_exact_invocation():
    """Verify unknown arguments have readable prose as well as exact invocation."""
    source = "{{Unknown|Do not [[Share|reveal]] your seed}}"
    result = WikiTextRenderer().render(source)
    assert source in result.text
    assert "Do not reveal your seed" in result.text
    assert result.source_gaps[0]["invocation"] == source


def test_nested_unknown_and_bare_templates_are_never_silent():
    """Verify nested unknown and bare templates are never silent."""
    source = "Before {{Admonition_Warn|Do NOT restore {{Unknown|old=0.01 BTC}}.}} {{Wallet_derivation_paths}} after"
    result = WikiTextRenderer().render(source)
    assert "Do NOT restore" in result.text
    assert "old=0.01 BTC" in result.text
    assert "Wallet_derivation_paths" in result.text
    assert result.text.endswith(" after")
    assert {gap["template"] for gap in result.source_gaps} == {
        "Admonition_Warn",
        "Unknown",
        "Wallet_derivation_paths",
    }


def test_supplied_simple_definitions_expand_with_defaults_and_caller_scope():
    """Verify supplied simple definitions expand with defaults and caller scope."""
    renderer = WikiTextRenderer(
        {
            "Template:Admonition_Warn": "<noinclude>Documentation only</noinclude><includeonly>Warning: {{{1}}}</includeonly>",
            "Template:Outer": "{{Admonition_Warn|Keep {{{value|all backups}}}.}}",
            "Template:Wallet date explainer": "The date is {{{date|not supplied}}}.",
        }
    )
    result = renderer.render("{{Outer}} {{Wallet_date_explainer|date=2026-01-01}}")
    assert result.text == "Warning: Keep all backups. The date is 2026-01-01."
    assert not result.source_gaps
    assert "Documentation" not in result.text


@pytest.mark.parametrize(
    "body",
    [
        "{{#if:{{{1}}}|safe|unsafe}}",
        "{{{{{template}}}|value}}",
        "{{{ {{name}} }}}",
        "<onlyinclude>selective content</onlyinclude>other",
        "#REDIRECT [[Template:Other]]",
    ],
)
def test_unsupported_definition_is_explicit_without_guessed_branch(body):
    """Verify unsupported definition is explicit without guessed branch."""
    result = WikiTextRenderer({"Conditional": body}).render(
        "{{Conditional|Keep all backups}}"
    )
    assert "Unresolved template" in result.text
    assert "{{Conditional|Keep all backups}}" in result.text
    assert result.source_gaps


def test_recursive_definition_and_expansion_limits_keep_original_call():
    """Verify recursive definition and expansion limits keep original call."""
    result = WikiTextRenderer({"Cycle": "{{Cycle|never reveal seed}}"}).render(
        "{{Cycle}}"
    )
    assert "recursive template expansion" in result.text
    assert "never reveal seed" in result.text
    renderer = WikiTextRenderer({"Repeat": "{{{1}}}" * 50})
    renderer.MAX_EXPANSION_BYTES = 200
    result = renderer.render("{{Repeat|keep this warning}}")
    assert "template expansion budget exceeded" in result.text
    assert "{{Repeat|keep this warning}}" in result.text
    assert len(result.text) < 200


def test_unused_arguments_preserved_and_missing_argument_is_reported():
    """Verify unused arguments preserved and missing argument is reported."""
    result = WikiTextRenderer({"Box": "{{{required}}}"}).render(
        "{{Box|extra=Do not delete}}"
    )
    assert "argument has no supplied value" in result.text
    assert "extra: Do not delete" in result.text


def test_literal_parameter_example_cannot_consume_and_erase_real_argument():
    """Verify literal parameter example cannot consume and erase real argument."""
    result = WikiTextRenderer({"Example": "<code>{{{1}}}</code>"}).render(
        "{{Example|Do not share your seed}}"
    )
    assert "`{{{1}}}`" in result.text
    assert "1: Do not share your seed" in result.text


def test_duplicate_arguments_keep_both_values_in_unresolved_call():
    """Verify duplicate arguments keep both values in unresolved call."""
    result = WikiTextRenderer({"Warn": "{{{1}}}"}).render(
        "{{Warn|1=Do not delete|1=Keep backups}}"
    )
    assert "Do not delete" in result.text
    assert "Keep backups" in result.text
    assert "duplicate or dynamic parameter names unsupported" in result.text


def test_missing_nested_definition_cannot_erase_callers_warning():
    """Verify missing nested definition cannot erase callers warning."""
    result = WikiTextRenderer({"Warn": "{{Absent|{{{1}}}}}"}).render(
        "{{Warn|Never reveal your seed}}"
    )
    assert "Unresolved template: Absent" in result.text
    assert "Never reveal your seed" in result.text


def test_literal_blocks_are_exact_and_do_not_expand_templates_or_collapse_spaces():
    """Verify literal blocks are exact and do not expand templates or collapse spaces."""
    literal = '<pre lang="bash"># comment\n  SOURCE_DIR="a b"\n\n\n  echo "{{Wallet_date_explainer}}"\n</pre>'
    inline = "<code><nowiki>[[File:example.png]] {{Do not expand}}</nowiki></code>"
    result = WikiTextRenderer().render("Before\n" + literal + "\n" + inline + "\nAfter")
    assert literal.split(">", 1)[1].rsplit("</pre>", 1)[0] in result.text
    assert inline.removeprefix("<code>").removesuffix("</code>") in result.text
    assert "```\n# comment\n  SOURCE_DIR" in result.text
    assert not result.source_gaps


def test_literal_embedded_backticks_use_longer_fences_and_keep_whitespace():
    """Verify literal embedded backticks use longer fences and keep whitespace."""
    body = '  echo "```"\n\n    echo "{{Not_a_template}}"\n'
    result = WikiTextRenderer().render(f"<pre>{body}</pre> <code>a ` b</code>")
    assert f"````\n{body}\n````" in result.text
    assert "``a ` b``" in result.text
    assert not result.source_gaps
    assert (
        WikiTextRenderer()
        .render("  indented example\n  second line")
        .text.startswith("  indented")
    )


def test_expansion_count_limit_retains_call_without_truncating_article():
    """Verify expansion count limit retains call without truncating article."""
    renderer = WikiTextRenderer({"Value": "snapshot value"})
    renderer.MAX_EXPANSIONS = 1
    result = renderer.render("{{Value}}\n{{Value|retain this argument}}\nAfter")
    assert result.text.startswith("snapshot value")
    assert "{{Value|retain this argument}}" in result.text
    assert result.text.endswith("After")
    assert result.source_gaps[0]["reason"] == "template expansion budget exceeded"


def test_headings_lists_tables_and_html_boundaries_survive():
    """Verify headings lists tables and html boundaries survive."""
    source = "=== Recovery ===\n# Close Bisq\n## Keep backups\n* Never share seed\n<p>First</p><p>Second<br>Third</p>\n{| class=wikitable\n! Condition !! Action\n|-\n| No backup || Do not overwrite\n|}\n[[File:Backup.png|thumb|Keep the full directory]]"
    text = WikiTextRenderer().render(source).text
    assert text.startswith("### Recovery\n")
    assert "# Close Bisq\n## Keep backups\n* Never share seed" in text
    assert "First\n\nSecond\nThird" in text
    assert " |  Condition  |  Action" in text
    assert " |  No backup  |  Do not overwrite" in text
    assert "Keep the full directory" in text


def write_dump(tmp_path, pages, version="0.10"):
    """Write a minimal namespaced wiki export for processor tests."""
    root = ET.Element(
        "mediawiki", xmlns=f"http://www.mediawiki.org/xml/export-{version}/"
    )
    for title, namespace, text in pages:
        page = ET.SubElement(root, "page")
        ET.SubElement(page, "title").text = title
        ET.SubElement(page, "ns").text = str(namespace)
        revision = ET.SubElement(page, "revision")
        if text is not None:
            ET.SubElement(revision, "text").text = text
    path = tmp_path / "dump.xml"
    ET.ElementTree(root).write(path, encoding="utf-8")
    return path


def test_xml_loads_later_definitions_but_never_indexes_them_as_articles(tmp_path):
    """Verify xml loads later definitions but never indexes them as articles."""
    source = write_dump(
        tmp_path,
        [
            ("Recovery", 0, "{{Warn|Do not overwrite}} {{Absent}}"),
            ("Template:Warn", 10, "Warning: {{{1}}}"),
            ("File:Screenshot", 6, "file description"),
            ("Talk:Recovery", 1, "discussion"),
        ],
        version="0.11",
    )
    output = tmp_path / "processed.jsonl"
    processor = WikiDumpProcessor(str(source), str(output))
    processor.process_dump()
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["title"] == "Recovery"
    assert "Warning: Do not overwrite" in rows[0]["content"]
    assert rows[0]["category"] in {"bisq1", "bisq2", "general"}
    assert rows[0]["source_gaps"][0]["template"] == "Absent"
    processor.process_dump()
    assert len(output.read_text().splitlines()) == 1


def test_warning_and_missing_expansion_survive_service_loading(tmp_path):
    """Verify warning and missing expansion survive service loading."""
    source = write_dump(
        tmp_path,
        [
            (
                "Recovery",
                0,
                "{{Admonition_Warn|Never reveal your seed phrase to anyone.}}\n{{Wallet_derivation_paths}}",
            ),
            ("Template:Admonition_Warn", 10, "Warning: {{{1}}}"),
        ],
    )
    output = tmp_path / "processed_wiki.jsonl"
    WikiDumpProcessor(str(source), str(output)).process_dump()
    documents = WikiService().load_wiki_data(str(tmp_path))
    assert len(documents) == 1
    assert (
        "Warning: Never reveal your seed phrase to anyone." in documents[0].page_content
    )
    assert (
        "[Unresolved template: Wallet_derivation_paths; definition absent from XML dump]"
        in documents[0].page_content
    )
    assert "{{Wallet_derivation_paths}}" in documents[0].page_content
    assert documents[0].page_content == json.loads(output.read_text())["content"]


@pytest.mark.parametrize(
    "pages", [[], [("Template:Only", 10, "definition")], [("Broken", 0, None)]]
)
def test_empty_or_broken_dump_cannot_replace_existing_corpus(tmp_path, pages):
    """Verify empty or broken dump cannot replace existing corpus."""
    source = write_dump(tmp_path, pages)
    output = tmp_path / "processed.jsonl"
    output.write_text("original complete corpus\n")
    with pytest.raises(ValueError):
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert output.read_text() == "original complete corpus\n"


def test_atomic_write_failure_leaves_old_corpus_and_removes_temporary(
    tmp_path, monkeypatch
):
    """Verify atomic write failure leaves old corpus and removes temporary."""
    source = write_dump(tmp_path, [("Article", 0, "Useful text")])
    output = tmp_path / "processed.jsonl"
    output.write_text("old corpus\n")

    def fail_replace(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("app.scripts.process_wiki_dump.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated disk failure"):
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert output.read_text() == "old corpus\n"
    assert not list(tmp_path.glob(".wiki-*.jsonl.tmp"))


@pytest.mark.parametrize("existing_mode,expected_mode", [(0o640, 0o640), (None, 0o644)])
def test_atomic_output_retains_group_readers_or_uses_public_default(
    tmp_path, existing_mode, expected_mode
):
    """Verify atomic output retains group readers or uses public default."""
    source = write_dump(tmp_path, [("Article", 0, "Useful text")])
    output = tmp_path / "processed.jsonl"
    if existing_mode is not None:
        output.write_text("old corpus\n")
        output.chmod(existing_mode)
    WikiDumpProcessor(str(source), str(output)).process_dump()
    assert stat.S_IMODE(output.stat().st_mode) == expected_mode
    assert json.loads(output.read_text())["content"] == "Useful text"


def test_duplicate_article_title_fails_without_replacing_corpus(tmp_path):
    """Verify duplicate article title fails without replacing corpus."""
    source = write_dump(tmp_path, [("Article", 0, "first"), ("Article", 0, "second")])
    output = tmp_path / "processed.jsonl"
    output.write_text("old corpus\n")
    with pytest.raises(ValueError, match="Duplicate article title"):
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert output.read_text() == "old corpus\n"


def test_case_insensitive_redirect_without_xml_marker_is_not_an_article(tmp_path):
    """Verify case insensitive redirect without xml marker is not an article."""
    source = write_dump(
        tmp_path,
        [("Alias", 0, " \n#redirect [[Article]]"), ("Article", 0, "actual content")],
    )
    output = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(source), str(output)).process_dump()
    assert [json.loads(line)["title"] for line in output.read_text().splitlines()] == [
        "Article"
    ]


def test_cli_explicit_paths_preserve_defaults_without_touching_them(tmp_path):
    """Verify cli explicit paths preserve defaults without touching them."""
    source = write_dump(tmp_path, [("Article", 0, "{{Missing}}")])
    output = tmp_path / "processed.jsonl"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.scripts.process_wiki_dump",
            "--input-file",
            str(source),
            "--output-file",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text())["source_gaps"][0]["template"] == "Missing"


def write_history_dump(tmp_path, pages):
    """Write a namespaced wiki export containing explicit revision histories."""
    root = ET.Element("mediawiki", xmlns="http://www.mediawiki.org/xml/export-0.11/")
    for title, namespace, revisions in pages:
        page = ET.SubElement(root, "page")
        ET.SubElement(page, "title").text = title
        ET.SubElement(page, "ns").text = str(namespace)
        for fields in revisions:
            revision = ET.SubElement(page, "revision")
            for key in ("id", "timestamp", "text"):
                if key in fields:
                    ET.SubElement(revision, key).text = fields[key]
            if fields.get("deleted"):
                revision.find("text").set("deleted", "deleted")
    path = tmp_path / "history.xml"
    ET.ElementTree(root).write(path, encoding="utf-8")
    return path


@pytest.mark.parametrize("reverse", [False, True])
def test_history_uses_latest_article_and_template_regardless_of_xml_order(
    tmp_path, reverse
):
    """Verify history uses latest article and template regardless of xml order."""
    article = [
        {"id": "1", "timestamp": "2020-01-01T00:00:00Z", "text": "obsolete article"},
        {"id": "4", "timestamp": "2026-01-01T00:00:00Z", "text": "Current {{Value}}"},
    ]
    template = [
        {"id": "2", "timestamp": "2020-01-01T00:00:00Z", "text": "old definition"},
        {"id": "3", "timestamp": "2025-12-31T23:59:00Z", "text": "snapshot definition"},
    ]
    if reverse:
        article.reverse()
        template.reverse()
    source = write_history_dump(
        tmp_path, [("Article", 0, article), ("Template:Value", 10, template)]
    )
    output = tmp_path / "processed.jsonl"
    processor = WikiDumpProcessor(str(source), str(output))
    processor.process_dump()
    row = json.loads(output.read_text())
    assert row["content"] == "Current snapshot definition"
    assert row["source_revision"] == {"id": "4", "timestamp": "2026-01-01T00:00:00Z"}
    assert processor.template_revisions["Value"]["id"] == "3"


def test_history_ties_use_numeric_id_and_timestamps_use_actual_utc(tmp_path):
    """Verify history ties use numeric id and timestamps use actual utc."""
    revisions = [
        {"id": "9", "timestamp": "2026-01-01T01:00:00Z", "text": "smaller numeric ID"},
        {
            "id": "10",
            "timestamp": "2026-01-01T02:00:00+01:00",
            "text": "latest in actual UTC with greater ID",
        },
        {
            "id": "100",
            "timestamp": "2026-01-01T03:00:00+03:00",
            "text": "earlier in actual UTC despite bigger ID",
        },
    ]
    source = write_history_dump(tmp_path, [("Article", 0, revisions)])
    output = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(source), str(output)).process_dump()
    assert json.loads(output.read_text())["source_revision"]["id"] == "10"


@pytest.mark.parametrize(
    "bad_revision",
    [
        {"id": "2", "text": "missing date"},
        {"timestamp": "2026-01-01T00:00:00Z", "text": "missing ID"},
        {"id": "2", "timestamp": "invalid", "text": "bad date"},
        {"id": "2", "timestamp": "2026-01-01T00:00:00", "text": "no timezone"},
        {"id": "abc", "timestamp": "2026-01-01T00:00:00Z", "text": "bad ID"},
        {
            "id": "1",
            "timestamp": "2026-01-01T00:00:00Z",
            "text": "ambiguous repeated ID",
        },
    ],
)
def test_ambiguous_or_malformed_history_fails_without_replacing_corpus(
    tmp_path, bad_revision
):
    """Verify ambiguous or malformed history fails without replacing corpus."""
    old = {"id": "1", "timestamp": "2020-01-01T00:00:00Z", "text": "old"}
    source = write_history_dump(tmp_path, [("Article", 0, [old, bad_revision])])
    output = tmp_path / "processed.jsonl"
    output.write_text("old complete corpus\n")
    with pytest.raises(ValueError):
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert output.read_text() == "old complete corpus\n"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("template", [False, True])
def test_deleted_latest_revision_never_falls_back_for_articles_or_templates(
    tmp_path, reverse, template
):
    """Verify deleted latest revision never falls back for articles or templates."""
    revisions = [
        {"id": "1", "timestamp": "2020-01-01T00:00:00Z", "text": "obsolete text"},
        {"id": "2", "timestamp": "2026-01-01T00:00:00Z", "text": "", "deleted": True},
    ]
    if reverse:
        revisions.reverse()
    title, ns = ("Template:Value", 10) if template else ("Article", 0)
    source = write_history_dump(tmp_path, [(title, ns, revisions)])
    output = tmp_path / "processed.jsonl"
    output.write_text("old complete corpus\n")
    with pytest.raises(ValueError, match="latest revision content is deleted"):
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert output.read_text() == "old complete corpus\n"


def add_page_ids(path, ids):
    """Assign deterministic page IDs to fixture export records."""
    tree = ET.parse(path)
    namespace = "{http://www.mediawiki.org/xml/export-0.11/}"
    for page, page_id in zip(tree.getroot().findall(namespace + "page"), ids):
        if page_id is not None:
            ET.SubElement(page, namespace + "id").text = str(page_id)
    tree.write(path, encoding="utf-8")


@pytest.mark.parametrize("reverse", [False, True])
def test_incremental_history_chunks_merge_and_identical_revisions_deduplicate(
    tmp_path, reverse
):
    """Verify incremental history chunks merge and identical revisions deduplicate."""
    old = {"id": "1", "timestamp": "2020-01-01T00:00:00Z", "text": "obsolete"}
    new = {"id": "2", "timestamp": "2026-01-01T00:00:00Z", "text": "latest content"}
    chunks = [("Article", 0, [old]), ("Article", 0, [old, new])]
    if reverse:
        chunks.reverse()
    source = write_history_dump(tmp_path, chunks)
    add_page_ids(source, [123, 123])
    output = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(source), str(output)).process_dump()
    assert json.loads(output.read_text())["content"] == "latest content"
    assert json.loads(output.read_text())["source_revision"]["id"] == "2"


@pytest.mark.parametrize(
    "second_title,second_ns,second_id",
    [
        ("Different title", 0, 123),
        ("Article", 1, 123),
        ("Article", 0, 456),
    ],
)
def test_conflicting_incremental_page_identity_is_rejected(
    tmp_path, second_title, second_ns, second_id
):
    """Verify conflicting incremental page identity is rejected."""
    revision = {"id": "1", "timestamp": "2020-01-01T00:00:00Z", "text": "body"}
    source = write_history_dump(
        tmp_path, [("Article", 0, [revision]), (second_title, second_ns, [revision])]
    )
    add_page_ids(source, [123, second_id])
    with pytest.raises(ValueError, match="[Cc]onflicting"):
        WikiDumpProcessor(str(source), str(tmp_path / "processed.jsonl")).process_dump()


def test_duplicate_revision_id_with_different_content_is_rejected(tmp_path):
    """Verify duplicate revision id with different content is rejected."""
    old = {"id": "1", "timestamp": "2020-01-01T00:00:00Z", "text": "first content"}
    conflict = {**old, "text": "different content"}
    source = write_history_dump(
        tmp_path, [("Article", 0, [old]), ("Article", 0, [conflict])]
    )
    add_page_ids(source, [123, 123])
    with pytest.raises(ValueError, match="Conflicting contents for revision ID"):
        WikiDumpProcessor(str(source), str(tmp_path / "processed.jsonl")).process_dump()


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        ("", ""),
        (" \n<!--comment--> ", "\n<!-- unused --> \n"),
    ],
)
def test_pure_redirect_with_comments_is_not_an_article(tmp_path, prefix, suffix):
    """Verify pure redirect with comments is not an article."""
    source = write_dump(
        tmp_path,
        [("Alias", 0, prefix + "#REDIRECT [[Actual]]" + suffix), ("Actual", 0, "body")],
    )
    output = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(source), str(output)).process_dump()
    assert [json.loads(line)["title"] for line in output.read_text().splitlines()] == [
        "Actual"
    ]


@pytest.mark.parametrize("with_directive", [False, True])
def test_substantive_redirect_tail_survives_including_warnings_lists_and_images(
    tmp_path, with_directive
):
    """Verify substantive redirect tail survives including warnings lists and images."""
    body = "{{Admonition_Warn|Never reveal your seed.}}\n* Keep all backups\n[[File:Guide.png|thumb|Guide screenshot]]"
    source = write_dump(
        tmp_path,
        [("Alias", 0, ("#REDIRECT [[Actual]]\n" if with_directive else "") + body)],
    )
    tree = ET.parse(source)
    ns = "{http://www.mediawiki.org/xml/export-0.10/}"
    ET.SubElement(tree.getroot().find(ns + "page"), ns + "redirect", title="Actual")
    tree.write(source, encoding="utf-8")
    output = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(source), str(output)).process_dump()
    row = json.loads(output.read_text())
    assert row["redirect_target"] == "Actual"
    assert "Warning: Never reveal your seed." in row["content"]
    assert "* Keep all backups" in row["content"]
    assert "Guide screenshot" in row["content"]


def test_redirect_comment_prefix_is_scanned_without_backtracking():
    """Verify redirect comment prefix is scanned without backtracking."""
    from app.scripts.process_wiki_dump import redirect_directive

    prefix = " \n<!-- prefix -->" * 20000
    assert redirect_directive(prefix + "ordinary article") is None
    assert redirect_directive(prefix + "<!-- unterminated") is None
    content = prefix + "#redirect [[Target#Section]]\nKeep this warning."
    match = redirect_directive(content)
    assert match is not None
    assert match.group(1) == "Target#Section"
    assert content[match.end() :] == "\nKeep this warning."


@pytest.mark.parametrize("reverse", [False, True])
def test_newest_chunk_keeps_its_xml_only_redirect_without_stale_markers(
    tmp_path, reverse
):
    """Page redirect metadata follows the selected revision in either block order."""
    source = write_dump(tmp_path, [("Alias", 0, "Older body")])
    ns = {"mw": "http://www.mediawiki.org/xml/export-0.10/"}
    old = ET.parse(source).getroot().find("mw:page", ns)
    ET.SubElement(old, "{" + ns["mw"] + "}id").text = "7"
    revision = old.find("mw:revision", ns)
    ET.SubElement(revision, "{" + ns["mw"] + "}id").text = "1"
    ET.SubElement(revision, "{" + ns["mw"] + "}timestamp").text = "2026-01-01T00:00:00Z"
    newer = deepcopy(old)
    newer.find("mw:revision/mw:id", ns).text = "2"
    newer.find("mw:revision/mw:timestamp", ns).text = "2026-01-02T00:00:00Z"
    newer.find("mw:revision/mw:text", ns).text = "Preserved redirect tail"
    ET.SubElement(newer, "{" + ns["mw"] + "}redirect", title="New target")
    ordered = [newer, old] if reverse else [old, newer]
    merged = coalesce_pages(ordered, ns)[0]
    result = WikiDumpProcessor(str(source), str(tmp_path / "out")).process_page(merged)
    assert result["redirect_target"] == "New target"
    assert "Preserved redirect tail" in result["content"]
    assert result["source_revision"]["id"] == "2"


def test_template_generated_cues_are_not_double_counted(tmp_path):
    """Raw and rendered copies of the same cue should not defeat new cues."""
    source = write_dump(
        tmp_path,
        [
            ("Neutral", 0, "arbitration {{Easy}}"),
            ("Template:Easy", 10, "Bisq Easy trade protocols"),
        ],
    )
    output = tmp_path / "processed.jsonl"
    WikiDumpProcessor(str(source), str(output)).process_dump()
    assert json.loads(output.read_text())["category"] == "bisq2"
    processor = WikiDumpProcessor(str(source), str(output))
    assert (
        processor.categorize_content("Neutral", "arbitration multisig", "Bisq Easy")
        == "bisq1"
    )


def test_processing_rejects_input_changed_after_parse(tmp_path, monkeypatch):
    """An overlapping snapshot update cannot publish results from stale XML."""
    from app.scripts.wiki_atomic import WikiPublicationConflictError

    source = write_dump(tmp_path, [("Article", 0, "Useful content")])
    output = tmp_path / "processed.jsonl"
    output.write_text("previous corpus")
    processor = WikiDumpProcessor(str(source), str(output))
    clean = processor.clean_text

    def change_input(content):
        """Change the input after it has been parsed but before publication."""
        rendered = clean(content)
        source.write_text(source.read_text() + "<!-- newer source -->")
        return rendered

    monkeypatch.setattr(processor, "clean_text", change_input)
    with pytest.raises(WikiPublicationConflictError):
        processor.process_dump()
    assert output.read_text() == "previous corpus"


def test_processing_preserves_post_replace_durability_error(
    tmp_path, monkeypatch, caplog
):
    """Do not mask a post-rename failure with temporary-file cleanup."""
    from app.scripts import wiki_atomic

    source = write_dump(tmp_path, [("Article", 0, "Useful content")])
    output = tmp_path / "processed.jsonl"
    output.write_text("previous corpus")
    fsync = wiki_atomic.os.fsync
    caplog.set_level("INFO")

    def fail_directory_fsync(fd):
        """Fail the directory sync after rename, not the staged file sync."""
        if stat.S_ISDIR(wiki_atomic.os.fstat(fd).st_mode):
            raise OSError("injected directory fsync failure")
        return fsync(fd)

    monkeypatch.setattr(wiki_atomic.os, "fsync", fail_directory_fsync)
    with pytest.raises(wiki_atomic.WikiPublicationDurabilityError) as error:
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert error.value.published is True
    assert json.loads(output.read_text())["content"] == "Useful content"
    assert "Processed content saved" not in caplog.text
    assert "Successfully processed" not in caplog.text
