"""Conservative, offline MediaWiki-to-text rendering for retrieval.

This is not a MediaWiki execution engine. Data-bearing templates expand only
from definitions present in the dump. The two known Admonition presentation
wrappers retain their supplied Warning/Note prose without requiring CSS/layout
definitions. Parser functions, dynamic names and other unsupported constructs
remain explicitly unresolved. Literal code is never reparsed or whitespace
normalized. Gaps retain the exact invocation for a machine-readable audit.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import mwparserfromhell
from mwparserfromhell import nodes


class _ExpansionLimit(Exception):
    """Abort an expansion without publishing its partial result."""


class _Parameters(dict):
    """Track arguments actually consumed, excluding literal examples/defaults."""

    def __init__(self):
        """Initialize a caller-argument map and its consumption ledger."""
        super().__init__()
        self.used = set()

    def __getitem__(self, key):
        """Record a substitution when its value is actually read."""
        self.used.add(key)
        return super().__getitem__(key)


def redirect_directive(content: str) -> Optional[re.Match[str]]:
    """Find a leading redirect after whitespace/comments in one forward scan."""
    offset = 0
    while offset < len(content):
        if content[offset].isspace():
            offset += 1
        elif content.startswith("<!--", offset):
            end = content.find("-->", offset + 4)
            if end < 0:
                return None
            offset = end + 3
        else:
            break
    return re.compile(r"#redirect\s*:?\s*\[\[([^\]]+)\]\]", re.IGNORECASE).match(
        content, offset
    )


def template_key(name: str) -> str:
    """MediaWiki's space/underscore and first-letter title normalization."""
    name = " ".join(name.replace("_", " ").split())
    if name.lower().startswith("template:"):
        name = name.split(":", 1)[1].strip()
    return name[:1].upper() + name[1:]


@dataclass
class RenderResult:
    """Rendered retrieval text plus explicit unresolved source dependencies."""

    text: str
    source_gaps: List[Dict[str, str]] = field(default_factory=list)


class WikiTextRenderer:
    """Render syntax structurally without inventing missing transclusions.

    Expansion budgets apply per article. Exhaustion leaves the original call
    visible rather than truncating the article. The source XML is the sole
    authority for definitions, including their potentially historical values.
    """

    MAX_DEPTH = 16
    MAX_EXPANSIONS = 128
    MAX_EXPANSION_BYTES = 1_000_000
    MAX_SOURCE_BYTES = 2_000_000
    MAX_RENDER_BYTES = 8_000_000
    MAX_RENDER_NODES = 100_000
    MAX_TRAVERSAL_DEPTH = 64
    MAX_FALLBACK_DEPTH = 16

    def __init__(self, templates: Optional[Dict[str, str]] = None):
        """Normalize definitions supplied by the XML snapshot only."""
        self.templates = {template_key(k): v for k, v in (templates or {}).items()}
        self.gaps: List[Dict[str, str]] = []
        self.expansions = 0
        self.expansion_bytes = 0
        self.external_links = []

    def render(self, text: str) -> RenderResult:
        """Render a bounded article, failing closed if total work is excessive."""
        if len(text.encode("utf-8")) > self.MAX_SOURCE_BYTES:
            raise ValueError("Wiki article exceeds source byte budget")
        self.gaps = []
        self.expansions = 0
        self.expansion_bytes = 0
        self.external_links = []
        self.render_bytes = 0
        self.render_nodes = 0
        self.traversal_depth = 0
        self.fallback_depth = 0
        self.fallback_stopped = False
        self.gap_bytes = 0
        result = self._code(mwparserfromhell.parse(text), {}, ())
        if self.fallback_stopped:
            # The parser can itself stop recognizing very deep syntax. Keep a
            # single exact source copy instead of trying to reconstruct it from
            # partially recognized nodes after our readability traversal stops.
            result += "\n[Fallback traversal stopped; exact original article]\n" + text
        if self.external_links:
            result += "\n\n[External links from article]\n" + "\n".join(
                f"{label}: {url}" for label, url in dict.fromkeys(self.external_links)
            )
        if len(result.encode("utf-8")) + self.gap_bytes > self.MAX_RENDER_BYTES:
            raise ValueError("Wiki rendered article and gaps exceed output byte budget")
        return RenderResult(result.strip("\n"), self.gaps.copy())

    def _gap(self, node, reason: str, kind: str = "template") -> str:
        """Record an unresolved invocation or a digest into its retained parent."""
        name = str(getattr(node, "name", "")).strip()
        invocation = str(node)
        gap = {
            "kind": kind,
            "template": name,
            "reason": reason,
        }
        if self.fallback_depth:
            # The outer raw invocation already contains every nested call.
            # Keep a verifiable reference, not quadratic copies of the subtree.
            gap["invocation_sha256"] = hashlib.sha256(invocation.encode()).hexdigest()
            gap["invocation_location"] = "contained in outer unresolved invocation"
        else:
            gap["invocation"] = invocation
        self.gap_bytes += sum(len(value.encode()) for value in gap.values())
        if self.gap_bytes > self.MAX_RENDER_BYTES:
            raise ValueError("Wiki source-gap output exceeds byte budget")
        definition = self.templates.get(template_key(name))
        if definition is not None:
            gap["definition_sha256"] = hashlib.sha256(
                definition.encode("utf-8")
            ).hexdigest()
        self.gaps.append(gap)
        # Keep the original call intact: every argument, negation, number and
        # nested call survives, even when execution is deliberately unsupported.
        marker = f"\n[Unresolved {kind}: {name}; {reason}]\n"
        return marker if self.fallback_depth else marker + invocation + "\n"

    def _code(self, code, params: Dict[str, str], stack: Tuple[str, ...]) -> str:
        """Visit syntax nodes under independent traversal and output budgets."""
        self.traversal_depth += 1
        try:
            if self.traversal_depth > self.MAX_TRAVERSAL_DEPTH:
                raise ValueError("Wiki rendering exceeds traversal depth budget")
            parts = []
            for node in code.nodes:
                self.render_nodes += 1
                if self.render_nodes > self.MAX_RENDER_NODES:
                    raise ValueError("Wiki rendering exceeds node budget")
                part = self._node(node, params, stack)
                self.render_bytes += len(part.encode("utf-8"))
                if self.render_bytes > self.MAX_RENDER_BYTES:
                    raise ValueError("Wiki rendering exceeds output/work byte budget")
                parts.append(part)
            return "".join(parts)
        finally:
            self.traversal_depth -= 1

    def _template(self, node, params: Dict[str, str], stack: Tuple[str, ...]) -> str:
        """Expand supported definitions or retain raw calls plus readable args."""

        def arguments():
            """Render parameter prose in the caller's scope."""
            return [
                (str(p.name).strip(), self._code(p.value, params, stack))
                for p in node.params
            ]

        def unresolved(reason: str) -> str:
            """Bound fallback work without losing the outer source invocation."""
            text = self._gap(node, reason)
            # Raw syntax remains available for audit; readable supplied prose is
            # separate from an expansion, so conditional arguments are not
            # presented as an evaluated result.
            if node.params and reason != "template expansion budget exceeded":
                if self.fallback_depth >= self.MAX_FALLBACK_DEPTH:
                    self.fallback_stopped = True
                    return (
                        text
                        + "[Nested arguments retained in outer invocation; fallback traversal stopped]\n"
                    )
                text += "[Supplied arguments; template not expanded]\n"
                self.fallback_depth += 1
                try:
                    text += (
                        "\n".join(f"{name}: {value}" for name, value in arguments())
                        + "\n"
                    )
                finally:
                    self.fallback_depth -= 1
            elif params and reason == "template expansion budget exceeded":
                text += "[Caller-supplied arguments; expansion stopped]\n"
                text += (
                    "\n".join(f"{name}: {value}" for name, value in params.items())
                    + "\n"
                )
            return text

        raw_name = str(node.name).strip()
        key = template_key(raw_name)
        if node.name.filter_templates() or node.name.filter_arguments():
            return unresolved("dynamic template name is unsupported")
        explicit_template = raw_name.lower().startswith("template:")
        if raw_name.startswith("#") or (":" in key and not explicit_template):
            return unresolved(
                "parser function or non-template transclusion unsupported"
            )
        if key in stack:
            return unresolved("recursive template expansion")
        if len(stack) >= self.MAX_DEPTH or self.expansions >= self.MAX_EXPANSIONS:
            return unresolved("template expansion budget exceeded")
        definition = self.templates.get(key)
        if definition is None:
            wrapper = {"Admonition Warn": "Warning", "Admonition Note": "Note"}.get(key)
            if wrapper and node.params:
                self._gap(
                    node,
                    "definition absent from XML dump; supplied prose preserved, presentation only",
                    "presentation_wrapper_only",
                )
                return (
                    "\n"
                    + wrapper
                    + ": "
                    + "\n".join(value for _, value in arguments())
                    + "\n"
                )
            return unresolved("definition absent from XML dump")
        if redirect_directive(definition):
            return unresolved(f"redirect definition Template:{key} unsupported")

        self.expansions += 1
        self.expansion_bytes += len(definition.encode("utf-8")) + len(
            str(node).encode("utf-8")
        )
        if self.expansion_bytes > self.MAX_EXPANSION_BYTES:
            return unresolved("template expansion budget exceeded")
        body = mwparserfromhell.parse(definition)
        # Noinclude documentation (and literal examples) is not active template
        # syntax. Remove excluded nodes before inspecting executable constructs.
        self._exclude_tags(body, {"noinclude"})
        preflight = mwparserfromhell.parse(str(body))
        self._exclude_tags(
            preflight, {"pre", "nowiki", "code", "syntaxhighlight", "source"}
        )
        # Do not guess conditional branch evaluation, Lua, magic words, dynamic
        # parameter names or selective transclusion semantics. Preserve the call
        # and identify which definition prevented a complete expansion.
        if any(
            str(t.name).strip().startswith("#")
            or t.name.filter_templates()
            or t.name.filter_arguments()
            for t in preflight.filter_templates()
        ) or any(str(t.tag).lower() == "onlyinclude" for t in preflight.filter_tags()):
            return unresolved(f"unsupported constructs in Template:{key}")
        if any(
            a.name.filter_templates() or a.name.filter_arguments()
            for a in preflight.filter_arguments()
        ):
            return unresolved(f"dynamic arguments in Template:{key}")

        values = _Parameters()
        for param in node.params:
            name = str(param.name).strip()
            if (
                name in values
                or param.name.filter_templates()
                or param.name.filter_arguments()
            ):
                return unresolved("duplicate or dynamic parameter names unsupported")
            # Values belong to the caller's argument scope, not the callee's.
            value = self._code(param.value, params, stack)
            values[name] = value.strip() if param.showkey else value
        try:
            rendered = self._code(body, values, stack + (key,))
        except _ExpansionLimit:
            return unresolved("template expansion budget exceeded")
        unused = [
            f"{name}: {value}"
            for name, value in values.items()
            if name not in values.used
        ]
        if unused:
            rendered += (
                "\n[Supplied template arguments not consumed by definition]\n"
                + "\n".join(unused)
            )
        return rendered

    def _exclude_tags(self, code, excluded: set[str], depth: int = 0) -> None:
        """Remove active excluded tags without entering literal examples."""
        if depth > self.MAX_TRAVERSAL_DEPTH:
            raise ValueError("Wiki preflight exceeds traversal depth budget")
        for node in list(code.nodes):
            if isinstance(node, nodes.Tag):
                tag = str(node.tag).lower()
                if tag in excluded:
                    code.remove(node, recursive=False)
                    continue
                if tag in {"pre", "nowiki", "code", "syntaxhighlight", "source"}:
                    continue
            for child in node.__children__():
                self._exclude_tags(child, excluded, depth + 1)

    def _node(self, node, params: Dict[str, str], stack: Tuple[str, ...]) -> str:
        """Convert one node, preserving literal contents and structural bounds."""
        if isinstance(node, nodes.Template):
            return self._template(node, params, stack)
        if isinstance(node, nodes.Argument):
            key = str(node.name).strip()
            if key in params:
                value = params[key]
                self.expansion_bytes += len(value.encode("utf-8"))
                if self.expansion_bytes > self.MAX_EXPANSION_BYTES:
                    raise _ExpansionLimit
                return value
            if node.default is not None:
                return self._code(node.default, params, stack)
            return self._gap(
                node, "argument has no supplied value or default", "argument"
            )
        if isinstance(node, nodes.Comment):
            return ""
        if isinstance(node, nodes.HTMLEntity):
            return node.normalize()
        if isinstance(node, nodes.Heading):
            return (
                "\n"
                + "#" * node.level
                + " "
                + self._code(node.title, params, stack).strip()
                + "\n"
            )
        if isinstance(node, nodes.Wikilink):
            title = str(node.title)
            label = (
                self._code(node.text, params, stack) if node.text is not None else title
            )
            if title.lower().startswith(("file:", "image:")):
                return f"\n[Image: {title}; {label}]\n"
            if title.lower().startswith("category:"):
                return ""
            return label
        if isinstance(node, nodes.ExternalLink):
            url = self._code(node.url, params, stack)
            if node.title:
                label = self._code(node.title, params, stack)
                self.external_links.append((label, url))
                return label
            return url
        if isinstance(node, nodes.Tag):
            tag = str(node.tag).lower()
            if tag in {"pre", "nowiki", "code", "syntaxhighlight", "source"}:
                # Preserve exact whitespace and markup inside literal spans.
                literal = str(node.contents or "")
                longest = max(
                    (len(run) for run in re.findall(r"`+", literal)), default=0
                )
                if tag in {"pre", "syntaxhighlight", "source"} or "\n" in literal:
                    fence = "`" * max(3, longest + 1)
                    return f"\n{fence}\n{literal}\n{fence}\n"
                fence = "`" * max(1, longest + 1)
                return f"{fence}{literal}{fence}"
            if tag == "noinclude" and stack:
                return ""
            if tag == "includeonly" and not stack:
                return ""
            contents = (
                self._code(node.contents, params, stack)
                if node.contents is not None
                else ""
            )
            if node.wiki_markup and node.self_closing:
                return str(node.wiki_markup)  # *, #, :, ; list/indent prefixes
            if tag in {"br", "hr"}:
                return "\n"
            if tag in {"td", "th"}:
                return " | " + contents
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                return "\n" + "#" * int(tag[1]) + " " + contents + "\n"
            if tag in {
                "p",
                "div",
                "section",
                "table",
                "tr",
                "ul",
                "ol",
                "dl",
                "blockquote",
            }:
                return "\n" + contents + "\n"
            if tag in {"li", "dd", "dt"}:
                return "\n* " + contents + "\n"
            if tag == "b":
                return "**" + contents + "**"
            if tag == "i":
                return "*" + contents + "*"
            return contents
        return str(node)
