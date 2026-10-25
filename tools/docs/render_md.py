"""The Markdown copy of the docs site, written from the same outlines as the HTML. It is meant to be read raw by coding
models, so names appear exactly as in the code; only a link's label escapes the brackets that would end the link."""

import re

from outline import FOOTER, Badge, Code, Entries, Facts, Link, Mono, Paragraph, Prose, Section
from paths import NOTICE_FILE, markdown_page, rel_link

# Read as Python-Markdown reads it for the HTML copy: a fence begins at the start of a line and ends only at a line
# that repeats it exactly, an unclosed fence is plain text, and any line that begins with # is a heading.
FENCE = re.compile(r"^(`{3,}|~{3,})")
HEADING = re.compile(r"^#")
HTML_LINK = re.compile(r"\]\((?![a-z]+://)([^)\s#]+)\.html(#[^)\s]*)?\)")
LINK = re.compile(r"(?<!\\)\]\(([^)\s]+)\)")
CODE_SPAN = re.compile(r"(`+).*?\1")


def label(value):
    return re.sub(r"([\\\[\]])", r"\\\1", value)


def code_span(value):
    return "`` %s ``" % value if "`" in value else "`%s`" % value


def fenced_lines(text):
    """Each line of text, and whether it belongs to a fenced code block, its fences included."""
    lines = text.split("\n")
    fenced = [False] * len(lines)
    i = 0
    while i < len(lines):
        fence = FENCE.match(lines[i])
        end = None
        if fence:
            end = next((j for j in range(i + 1, len(lines)) if lines[j].rstrip(" ") == fence.group(1)), None)
        if end is None:
            i += 1
        else:
            fenced[i : end + 1] = [True] * (end + 1 - i)
            i = end + 1
    return list(zip(lines, fenced))


def outside_code_spans(line, change):
    out, at = [], 0
    for found in CODE_SPAN.finditer(line):
        out += [change(line[at : found.start()]), found.group(0)]
        at = found.end()
    return "".join(out + [change(line[at:])])


def links(text):
    """The targets of the Markdown links in text, outside code and headings, where no link is written."""
    found = []
    for line, fenced in fenced_lines(text):
        if not fenced and not HEADING.match(line):
            found += LINK.findall(CODE_SPAN.sub("", line))
    return found


def target_of(path, link):
    """None for a link to a line, since a Markdown page has no anchors for its lines."""
    if link.line is not None:
        return None
    if "://" in link.target:
        return link.target
    return markdown_page(rel_link(path, link.target))


def inline(parts, path):
    out = []
    for part in parts:
        if isinstance(part, Link):
            target = target_of(path, part)
            out.append("[%s](%s)" % (label(part.label), target) if target else part.label)
        elif isinstance(part, Mono):
            out.append(code_span(part.text))
        elif isinstance(part, Badge):
            out.append("(%s)" % part.text)
        else:
            out.append(part)
    return "".join(out)


def runs(numbers):
    found = []
    for n in sorted(numbers):
        if found and n == found[-1][1] + 1:
            found[-1][1] = n
        else:
            found.append([n, n])
    return found


def listed(items):
    return items[0] if len(items) == 1 else "%s and %s" % (", ".join(items[:-1]), items[-1])


def span(first, last):
    return "line %d" % first if first == last else "lines %d to %d" % (first, last)


def left_out_note(first_line, greyed):
    spans = [span(first_line + s, first_line + e) for s, e in runs(greyed)]
    if not spans:
        return None
    return "Left out of this build by an `#if`: %s." % listed(spans)


def code(b):
    lines = b.text.split("\n")
    if b.text.endswith("\n"):
        lines.pop()
    if b.first_line is None:
        return "```cpp\n%s\n```" % "\n".join(lines)
    last = b.first_line + len(lines) - 1
    where = " of `%s`" % b.file if b.file else ""
    notes = ["%s%s, numbered." % (span(b.first_line, last).capitalize(), where), left_out_note(b.first_line, b.greyed)]
    notes += [
        "The hand-placed hook %s fires on line %d." % (hook, b.first_line + i)
        for i, hook in sorted((b.marks or {}).items())
    ]
    width = len(str(last))
    numbered = ["%*d  %s" % (width, b.first_line + i, line) for i, line in enumerate(lines)]
    return " ".join(filter(None, notes)) + "\n\n```cpp\n%s\n```" % "\n".join(numbered)


def prose(markdown, first_heading):
    lines = []
    for line, fenced in fenced_lines(markdown):
        if not fenced:
            if HEADING.match(line):
                line = "#" * (first_heading - 1) + line
            line = outside_code_spans(line, lambda part: HTML_LINK.sub(r"](\1.md\2)", part))
        lines.append(line)
    return "\n".join(lines).strip()


def block(b, path):
    if isinstance(b, Facts):
        rows = [(term, inline(parts, path)) for term, parts in b.rows]
        return "\n".join("- **%s:** %s" % (term, value) for term, value in rows if value)
    if isinstance(b, Section):
        body = "\n\n".join(filter(None, (block(inner, path) for inner in b.blocks)))
        return "## %s\n\n%s" % (b.heading, body) if body else ""
    if isinstance(b, Entries):
        items = "\n".join("- " + inline(item, path) for item in b.items)
        if items and b.fold_after is not None and len(b.items) > b.fold_after:
            return "%s:\n\n%s" % (b.summary, items)
        return items
    if isinstance(b, Code):
        return code(b)
    if isinstance(b, Prose):
        return prose(b.markdown, b.first_heading)
    if isinstance(b, Paragraph):
        return ("**Warning:** " if b.warning else "") + inline(b.parts, path)
    raise TypeError("no Markdown for %r" % (b,))


def trail(outline):
    if all(target == outline.path for _, target in outline.trail):
        return ""
    return " / ".join(
        crumb if target == outline.path else "[%s](%s)" % (label(crumb), markdown_page(rel_link(outline.path, target)))
        for crumb, target in outline.trail
    )


def page(outline):
    notice = "[NOTICE](%s)" % rel_link(outline.path, NOTICE_FILE)
    blocks = [block(b, outline.path) for b in outline.blocks]
    parts = ["# " + outline.heading, trail(outline)] + blocks + [FOOTER.format(notice=notice)]
    return "\n\n".join(filter(None, parts)) + "\n"
