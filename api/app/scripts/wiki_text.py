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
        super().__init__()
        self.used = set()

    def __getitem__(self, key):
        self.used.add(key)
        return super().__getitem__(key)


def template_key(name: str) -> str:
    """MediaWiki's space/underscore and first-letter title normalization."""
    name = name.replace("_", " ").strip()
    if name.lower().startswith("template:"):
        name = name.split(":", 1)[1].strip()
    return name[:1].upper() + name[1:]


@dataclass
class RenderResult:
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

    def __init__(self, templates: Optional[Dict[str, str]] = None):
        self.templates = {template_key(k): v for k, v in (templates or {}).items()}
        self.gaps: List[Dict[str, str]] = []
        self.expansions = 0
        self.expansion_bytes = 0
        self.external_links = []

    def render(self, text: str) -> RenderResult:
        self.gaps = []
        self.expansions = 0
        self.expansion_bytes = 0
        self.external_links = []
        result = self._code(mwparserfromhell.parse(text), {}, ())
        if self.external_links:
            result += "\n\n[External links from article]\n" + "\n".join(
                f"{label}: {url}" for label, url in dict.fromkeys(self.external_links)
            )
        return RenderResult(result.strip("\n"), self.gaps.copy())

    def _gap(self, node, reason: str, kind: str = "template") -> str:
        name = str(getattr(node, "name", "")).strip()
        gap = {
            "kind": kind,
            "template": name,
            "reason": reason,
            "invocation": str(node),
        }
        definition = self.templates.get(template_key(name))
        if definition is not None:
            gap["definition_sha256"] = hashlib.sha256(
                definition.encode("utf-8")
            ).hexdigest()
        self.gaps.append(gap)
        # Keep the original call intact: every argument, negation, number and
        # nested call survives, even when execution is deliberately unsupported.
        return f"\n[Unresolved {kind}: {name}; {reason}]\n{node}\n"

    def _code(self, code, params: Dict[str, str], stack: Tuple[str, ...]) -> str:
        return "".join(self._node(node, params, stack) for node in code.nodes)

    def _template(self, node, params: Dict[str, str], stack: Tuple[str, ...]) -> str:
        def arguments():
            return [
                (str(p.name).strip(), self._code(p.value, params, stack))
                for p in node.params
            ]

        def unresolved(reason: str) -> str:
            text = self._gap(node, reason)
            # Raw syntax remains available for audit; readable supplied prose is
            # separate from an expansion, so conditional arguments are not
            # presented as an evaluated result.
            if node.params and reason != "template expansion budget exceeded":
                text += "[Supplied arguments; template not expanded]\n"
                text += (
                    "\n".join(f"{name}: {value}" for name, value in arguments()) + "\n"
                )
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
        if raw_name.startswith("#") or ":" in key:
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
        if definition.lstrip().upper().startswith("#REDIRECT"):
            return unresolved(f"redirect definition Template:{key} unsupported")

        self.expansions += 1
        self.expansion_bytes += len(definition.encode("utf-8")) + len(
            str(node).encode("utf-8")
        )
        if self.expansion_bytes > self.MAX_EXPANSION_BYTES:
            return unresolved("template expansion budget exceeded")
        body = mwparserfromhell.parse(definition)
        # Do not guess conditional branch evaluation, Lua, magic words, dynamic
        # parameter names or selective transclusion semantics. Preserve the call
        # and identify which definition prevented a complete expansion.
        if any(
            str(t.name).strip().startswith("#")
            or t.name.filter_templates()
            or t.name.filter_arguments()
            for t in body.filter_templates()
        ) or any(str(t.tag).lower() == "onlyinclude" for t in body.filter_tags()):
            return unresolved(f"unsupported constructs in Template:{key}")
        if any(
            a.name.filter_templates() or a.name.filter_arguments()
            for a in body.filter_arguments()
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

    def _node(self, node, params: Dict[str, str], stack: Tuple[str, ...]) -> str:
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
