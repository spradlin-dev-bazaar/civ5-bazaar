"""The HTML pieces of the docs site."""

import html

from pygments.formatters import HtmlFormatter
from pygments.lexers import CppLexer
from pygments.token import STANDARD_TYPES

LEXER = CppLexer()
LIGHT_STYLE = "vs"
DARK_STYLE = "github-dark"
SITE_NAME = "Bazaar developer reference"
STYLE_FILE = "style.css"
SCRIPT_FILE = "search.js"
INDEX_FILE = "search-index.js"
NOTICE_FILE = "NOTICE.txt"
SUPPORT_FILES = (STYLE_FILE, SCRIPT_FILE, INDEX_FILE, NOTICE_FILE)
FOOTER = (
    "The game's code on these pages is &copy; 1991-2012 Take-Two Interactive Software and its subsidiaries, "
    "developed by Firaxis Games, with changes by whoward69's Various Mod Components. All rights reserved. "
    'See <a href="{notice}">NOTICE</a>.'
)


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
        note = '<span class="note">%s</span>' % esc(marks[i]) if i in marks else ""
        if first_line is None:
            out.append('<span class="%s">%s%s</span>' % (classes, body, note))
            continue
        n = first_line + i
        out.append(
            '<span class="%s" id="L%d"><a class="ln" href="#L%d">%d</a>%s%s</span>' % (classes, n, n, n, body, note)
        )
    return '<pre class="code%s">%s</pre>' % (" plain" if first_line is None else "", "".join(out))


def link(href, label, title=None):
    return '<a href="%s"%s>%s</a>' % (esc(href), ' title="%s"' % esc(title) if title else "", esc(label))


def crumbs(items):
    parts = [link(href, label) if href else '<span aria-current="page">%s</span>' % esc(label) for label, href in items]
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


def page(title, root, trail, body):
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>%(title)s - %(site)s</title>"
        '<link rel="stylesheet" href="%(root)s%(style)s">'
        '<script defer src="%(root)s%(script)s"></script>'
        '</head><body data-root="%(root)s">'
        '<header class="top"><a class="site" href="%(root)sindex.html">%(site)s</a>'
        '<div class="search"><input type="search" placeholder="Search functions, classes and files" '
        'aria-label="Search" autocomplete="off"><ol class="results"></ol></div></header>'
        "%(trail)s<main>%(body)s</main>"
        "<footer>%(footer)s</footer>"
        "</body></html>\n"
    ) % {
        "title": esc(title),
        "site": esc(SITE_NAME),
        "root": esc(root),
        "style": STYLE_FILE,
        "script": SCRIPT_FILE,
        "trail": crumbs(trail) if trail else "",
        "body": body,
        "footer": FOOTER.format(notice=esc(root + NOTICE_FILE)),
    }
