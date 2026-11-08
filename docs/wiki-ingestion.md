# Wiki ingestion and recovery checks

The wiki cache is a text source for retrieval, not a complete MediaWiki backup.
The downloader captures one revision of main-namespace pages, including
redirects, and template definitions (namespace 10). It does not capture upload
binaries, other namespaces, or full revision history. Content and revision
metadata are read in the same request. A failed page fetch, an export with no
articles, or invalid XML leaves the previous snapshot untouched.

The processor parses wikitext instead of deleting template syntax with a regular
expression. Warning and note prose is retained. Simple definitions present in
the export can expand, including parameter defaults and nested calls. Missing
or unsupported expansions remain explicit in the text and are recorded in each
article's optional `source_gaps` field. Parser functions, dynamic template
names, selective transclusion and other unsupported constructs are not guessed.
Literal code remains literal. Pure redirects and template definitions do not
become standalone retrieval articles. A redirect with substantive trailing prose retains that prose and its
`redirect_target` metadata. Full-history exports, including repeated WikiTeam
page chunks, are coalesced by page identity; the newest revision is selected by
UTC timestamp and numeric revision ID. Conflicting identities or revisions and
unavailable latest content fail rather than falling back silently.

A `presentation_wrapper_only` gap means a warning/note's prose was recovered,
but its original presentation-template definition was absent. Other gaps can
represent unavailable substantive content, such as a transcluded limit or
wallet explanation. Gap counts must not be described as counts of missing
articles. Captured values and recovered warnings remain historical evidence;
preservation does not establish that advice is current.

## Reprocess a saved export offline

From `api/`, use the existing application environment and an output directory
separate from runtime data:

```sh
python -m app.scripts.process_wiki_dump \
  --input-file /path/to/saved/bisq2_dump.xml \
  --output-file /path/to/audit/processed_wiki.jsonl
```

The output directory must already exist. Processing errors, conflicting page identities
or revisions, and an empty result do not replace an existing JSONL file. A successful
result is published by atomic replacement. Inspect title coverage and
`source_gaps`, and verify warning/note content against the raw source before
promoting a regenerated corpus. Retain the preceding snapshot and separately
record any older processed-only articles absent from the raw export; these do
not have the same provenance as original wikitext.

The runtime loader passes article content through to retrieval. Regenerating a
file in an audit directory does not change the running service or its Qdrant
index. Deploying these code changes alone also does not regenerate an existing
wiki cache or replace the bundled bootstrap seed. Runtime corpus promotion,
source-metadata verification, and the documented index rebuild remain separate
operator steps; do not reset the vector store as part of this audit.

## Verification

Focused regression tests cover warning and note content, nested/unknown
calls, unavailable definitions, literal code, template expansion limits,
atomic publication, redirects, and loading regenerated text through
`WikiService`. Run these with the normal API test environment:

```sh
pytest tests/scripts/test_download_wiki.py \
  tests/scripts/test_wiki_dump_preservation.py \
  tests/scripts/test_update_wiki.py \
  tests/services/test_wiki_protocol_metadata.py
```
