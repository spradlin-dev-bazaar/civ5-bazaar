"""The HTML of the docs site, written from each page's outline."""

import html

import markdown
from pygments.formatters import HtmlFormatter
from pygments.lexers import CppLexer
from pygments.token import STANDARD_TYPES

from outline import FOOTER, Badge, Code, Entries, Facts, Link, Mono, Paragraph, Prose, Section
from paths import HOME_PAGE, NOTICE_FILE, rel_link

LEXER = CppLexer()
LIGHT_STYLE = "vs"
DARK_STYLE = "github-dark"
SITE_NAME = "Bazaar developer reference"
STYLE_FILE = "style.css"
SCRIPT_FILE = "search.js"
INDEX_FILE = "search-index.js"
INDEX_START = "window.BAZAAR_INDEX = "
SUPPORT_FILES = (STYLE_FILE, SCRIPT_FILE, INDEX_FILE, NOTICE_FILE)


def esc(text):
    return html.escape(text, quote=True)


def code_css():
    light = HtmlFormatter(style=LIGHT_STYLE).get_style_defs(".code")
    dark = HtmlFormatter(style=DARK_STYLE).get_style_defs(".code")
    return "%s\n@media (prefers-color-scheme: dark) {\n%s\n}\n" % (light, dark)


def token_class(ttype):
    while ttype not in STANDARD_TYPES:
        ttype = ttype.parent
    return STANDARD_TYPES[ttype]


def code_block(text, first_line, links=None, greyed=(), marks=None):
    """links are keyed by offsets into text after its CRLFs became LFs; only a token starting there is linked."""
    links, marks = links or {}, marks or {}
    lines, current, run = [], [], ["", ""]

    def flush():
        cls, value = run
        if value:
            current.append('<span class="%s">%s</span>' % (cls, esc(value)) if cls not in ("", "w") else esc(value))
        run[:] = ["", ""]

    for pos, ttype, value in LEXER.get_tokens_unprocessed(text):
        cls = token_class(ttype)
        link = links.get(pos)
        if link and "\n" not in value:
            flush()
            current.append('<a class="%s" href="%s" title="%s">%s</a>' % (cls, esc(link[0]), esc(link[1]), esc(value)))
            continue
        for i, part in enumerate(value.split("\n")):
            if i:
                flush()
                lines.append("".join(current))
                current = []
            if part and run[0] == cls:
                run[1] += part
            elif part:
                flush()
                run[:] = [cls, part]
    flush()
    lines.append("".join(current))
    if text.endswith("\n"):
        lines.pop()
    out = []
    for i, body in enumerate(lines):
        classes = "line" + (" greyed" if i in greyed else "") + (" marked" if i in marks else "")
        note = '<span class="note">hand-placed hook: %s</span>' % esc(marks[i]) if i in marks else ""
        if first_line is None:
            out.append('<span class="%s">%s%s</span>' % (classes, body, note))
            continue
        n = first_line + i
        out.append(
            '<span class="%s" id="L%d"><a class="ln" href="#L%d">%d</a>%s%s</span>' % (classes, n, n, n, body, note)
        )
    return '<pre class="code%s">%s</pre>' % (" plain" if first_line is None else "", "".join(out))


def anchor(href, label, title=None):
    return '<a href="%s"%s>%s</a>' % (esc(href), ' title="%s"' % esc(title) if title else "", esc(label))


def crumbs(items):
    parts = [
        anchor(href, label) if href else '<span aria-current="page">%s</span>' % esc(label) for label, href in items
    ]
    return '<nav class="crumbs">%s</nav>' % ' <span class="sep">/</span> '.join(parts)


def facts(rows):
    body = "".join("<dt>%s</dt><dd>%s</dd>" % (esc(term), value) for term, value in rows if value)
    return '<dl class="facts">%s</dl>' % body if body else ""


def entry_list(items, folded_after=None, summary=None):
    if not items:
        return ""
    body = '<ul class="entries">%s</ul>' % "".join("<li>%s</li>" % item for item in items)
    if folded_after is not None and len(items) > folded_after:
        return "<details><summary>%s</summary>%s</details>" % (esc(summary), body)
    return body


def section(heading, body, anchor=None):
    if not body:
        return ""
    return "<section%s><h2>%s</h2>%s</section>" % (' id="%s"' % anchor if anchor else "", esc(heading), body)


def to_html(md, first_heading=1):
    toc = {"baselevel": first_heading}
    return markdown.markdown(md, extensions=["tables", "fenced_code", "toc"], extension_configs={"toc": toc})


def href(path, link):
    if "://" in link.target:
        return link.target
    if link.line is not None and link.target == path:
        return "#L%d" % link.line
    return rel_link(path, link.target) + ("#L%d" % link.line if link.line is not None else "")


def inline(parts, path):
    out = []
    for part in parts:
        if isinstance(part, Link):
            out.append(anchor(href(path, part), part.label, part.title))
        elif isinstance(part, Mono):
            out.append("<code>%s</code>" % esc(part.text))
        elif isinstance(part, Badge):
            out.append('<span class="badge">%s</span>' % esc(part.text))
        else:
            out.append(esc(part))
    return "".join(out)


def block(b, path):
    if isinstance(b, Facts):
        return facts([(term, inline(parts, path)) for term, parts in b.rows])
    if isinstance(b, Section):
        return section(b.heading, "".join(block(inner, path) for inner in b.blocks), b.anchor)
    if isinstance(b, Entries):
        return entry_list([inline(item, path) for item in b.items], b.fold_after, b.summary)
    if isinstance(b, Code):
        links = {at: (rel_link(path, target), title) for at, (target, title) in (b.links or {}).items()}
        return code_block(b.text, b.first_line, links, b.greyed, b.marks)
    if isinstance(b, Prose):
        return to_html(b.markdown, b.first_heading)
    if isinstance(b, Paragraph):
        return "<p%s>%s</p>" % (' class="warn"' if b.warning else "", inline(b.parts, path))
    raise TypeError("no HTML for %r" % (b,))


def page(outline):
    root = "../" * outline.path.count("/")
    trail = [
        (label, None if target == outline.path else rel_link(outline.path, target)) for label, target in outline.trail
    ]
    body = "<h1>%s</h1>" % esc(outline.heading) + "".join(block(b, outline.path) for b in outline.blocks)
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>%(title)s - %(site)s</title>"
        '<link rel="stylesheet" href="%(root)s%(style)s">'
        '<script defer src="%(root)s%(script)s"></script>'
        '</head><body data-root="%(root)s" data-index="%(index)s">'
        '<header class="top"><a class="site" href="%(root)s%(home)s">%(site)s</a>'
        '<div class="search"><input type="search" placeholder="Search functions, classes, hooks and files" '
        'aria-label="Search" autocomplete="off"><ol class="results"></ol></div></header>'
        "%(trail)s<main>%(body)s</main>"
        "<footer>%(footer)s</footer>"
        "</body></html>\n"
    ) % {
        "title": esc(outline.title),
        "site": esc(SITE_NAME),
        "root": esc(root),
        "style": STYLE_FILE,
        "script": SCRIPT_FILE,
        "index": INDEX_FILE,
        "home": HOME_PAGE,
        "trail": crumbs(trail) if trail else "",
        "body": body,
        "footer": esc(FOOTER).format(notice=anchor(root + NOTICE_FILE, "NOTICE")),
    }
