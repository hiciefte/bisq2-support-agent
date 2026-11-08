"""Offline parser regressions; no API services or persisted KB are loaded."""

import json
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from app.scripts.process_wiki_dump import WikiDumpProcessor
from app.scripts.wiki_text import WikiTextRenderer
from app.services.wiki_service import WikiService

pytestmark = pytest.mark.unit


def test_real_warning_and_note_arguments_survive_missing_definitions():
    # Actual source calls from SEPA Instant and Downloading and installing.
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
    result = WikiTextRenderer().render(
        "{{Admonition Warn|Do not [[Share|reveal]] your seed on [https://example.invalid/ any website].}}"
    )
    assert "Warning: Do not reveal your seed on any website." in result.text
    assert "any website: https://example.invalid/" in result.text


def test_unknown_arguments_have_readable_prose_as_well_as_exact_invocation():
    source = "{{Unknown|Do not [[Share|reveal]] your seed}}"
    result = WikiTextRenderer().render(source)
    assert source in result.text
    assert "Do not reveal your seed" in result.text
    assert result.source_gaps[0]["invocation"] == source


def test_nested_unknown_and_bare_templates_are_never_silent():
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
    result = WikiTextRenderer({"Conditional": body}).render(
        "{{Conditional|Keep all backups}}"
    )
    assert "Unresolved template" in result.text
    assert "{{Conditional|Keep all backups}}" in result.text
    assert result.source_gaps


def test_recursive_definition_and_expansion_limits_keep_original_call():
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
    result = WikiTextRenderer({"Box": "{{{required}}}"}).render(
        "{{Box|extra=Do not delete}}"
    )
    assert "argument has no supplied value" in result.text
    assert "extra: Do not delete" in result.text


def test_literal_parameter_example_cannot_consume_and_erase_real_argument():
    result = WikiTextRenderer({"Example": "<code>{{{1}}}</code>"}).render(
        "{{Example|Do not share your seed}}"
    )
    assert "`{{{1}}}`" in result.text
    assert "1: Do not share your seed" in result.text


def test_duplicate_arguments_keep_both_values_in_unresolved_call():
    result = WikiTextRenderer({"Warn": "{{{1}}}"}).render(
        "{{Warn|1=Do not delete|1=Keep backups}}"
    )
    assert "Do not delete" in result.text
    assert "Keep backups" in result.text
    assert "duplicate or dynamic parameter names unsupported" in result.text


def test_missing_nested_definition_cannot_erase_callers_warning():
    result = WikiTextRenderer({"Warn": "{{Absent|{{{1}}}}}"}).render(
        "{{Warn|Never reveal your seed}}"
    )
    assert "Unresolved template: Absent" in result.text
    assert "Never reveal your seed" in result.text


def test_literal_blocks_are_exact_and_do_not_expand_templates_or_collapse_spaces():
    literal = '<pre lang="bash"># comment\n  SOURCE_DIR="a b"\n\n\n  echo "{{Wallet_date_explainer}}"\n</pre>'
    inline = "<code><nowiki>[[File:example.png]] {{Do not expand}}</nowiki></code>"
    result = WikiTextRenderer().render("Before\n" + literal + "\n" + inline + "\nAfter")
    assert literal.split(">", 1)[1].rsplit("</pre>", 1)[0] in result.text
    assert inline.removeprefix("<code>").removesuffix("</code>") in result.text
    assert "```\n# comment\n  SOURCE_DIR" in result.text
    assert not result.source_gaps


def test_literal_embedded_backticks_use_longer_fences_and_keep_whitespace():
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
    renderer = WikiTextRenderer({"Value": "snapshot value"})
    renderer.MAX_EXPANSIONS = 1
    result = renderer.render("{{Value}}\n{{Value|retain this argument}}\nAfter")
    assert result.text.startswith("snapshot value")
    assert "{{Value|retain this argument}}" in result.text
    assert result.text.endswith("After")
    assert result.source_gaps[0]["reason"] == "template expansion budget exceeded"


def test_headings_lists_tables_and_html_boundaries_survive():
    source = "=== Recovery ===\n# Close Bisq\n## Keep backups\n* Never share seed\n<p>First</p><p>Second<br>Third</p>\n{| class=wikitable\n! Condition !! Action\n|-\n| No backup || Do not overwrite\n|}\n[[File:Backup.png|thumb|Keep the full directory]]"
    text = WikiTextRenderer().render(source).text
    assert text.startswith("### Recovery\n")
    assert "# Close Bisq\n## Keep backups\n* Never share seed" in text
    assert "First\n\nSecond\nThird" in text
    assert " |  Condition  |  Action" in text
    assert " |  No backup  |  Do not overwrite" in text
    assert "Keep the full directory" in text


def write_dump(tmp_path, pages, version="0.10"):
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
    source = write_dump(tmp_path, pages)
    output = tmp_path / "processed.jsonl"
    output.write_text("original complete corpus\n")
    with pytest.raises(ValueError):
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert output.read_text() == "original complete corpus\n"


def test_atomic_write_failure_leaves_old_corpus_and_removes_temporary(
    tmp_path, monkeypatch
):
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
    source = write_dump(tmp_path, [("Article", 0, "Useful text")])
    output = tmp_path / "processed.jsonl"
    if existing_mode is not None:
        output.write_text("old corpus\n")
        output.chmod(existing_mode)
    WikiDumpProcessor(str(source), str(output)).process_dump()
    assert stat.S_IMODE(output.stat().st_mode) == expected_mode
    assert json.loads(output.read_text())["content"] == "Useful text"


def test_duplicate_article_title_fails_without_replacing_corpus(tmp_path):
    source = write_dump(tmp_path, [("Article", 0, "first"), ("Article", 0, "second")])
    output = tmp_path / "processed.jsonl"
    output.write_text("old corpus\n")
    with pytest.raises(ValueError, match="Duplicate article title"):
        WikiDumpProcessor(str(source), str(output)).process_dump()
    assert output.read_text() == "old corpus\n"


def test_case_insensitive_redirect_without_xml_marker_is_not_an_article(tmp_path):
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
    revision = {"id": "1", "timestamp": "2020-01-01T00:00:00Z", "text": "body"}
    source = write_history_dump(
        tmp_path, [("Article", 0, [revision]), (second_title, second_ns, [revision])]
    )
    add_page_ids(source, [123, second_id])
    with pytest.raises(ValueError, match="[Cc]onflicting"):
        WikiDumpProcessor(str(source), str(tmp_path / "processed.jsonl")).process_dump()


def test_duplicate_revision_id_with_different_content_is_rejected(tmp_path):
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
