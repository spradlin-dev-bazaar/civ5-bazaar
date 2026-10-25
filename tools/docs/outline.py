"""What each docs page says, before render.py writes it as HTML and render_md.py as Markdown. A link names the page it
points to by its path from the site's root, which each writer makes relative, or by a full URL, which they leave alone.
Prose is hand-written Markdown whose links are already relative to its page and end in .html."""

import collections

FOOTER = (
    "The game's code on these pages is © 1991-2012 Take-Two Interactive Software and its subsidiaries, developed "
    "by Firaxis Games, with changes by whoward69's Various Mod Components. All rights reserved. See {notice}."
)

Page = collections.namedtuple("Page", "path title heading trail blocks")
Facts = collections.namedtuple("Facts", "rows")
Section = collections.namedtuple("Section", "heading blocks anchor", defaults=(None,))
Entries = collections.namedtuple("Entries", "items fold_after summary", defaults=(None, None))
# text has LF line ends. first_line is the file line of its first line, or None for a block shown without numbers.
# links maps an offset into text to (target page, title); greyed and marks hold 0-based line indexes into text,
# marks naming the hand-placed hook called on that line.
Code = collections.namedtuple("Code", "text first_line links greyed marks file", defaults=(None, (), None, None))
Prose = collections.namedtuple("Prose", "markdown first_heading", defaults=(1,))
Paragraph = collections.namedtuple("Paragraph", "parts warning", defaults=(False,))

Link = collections.namedtuple("Link", "target label title line", defaults=(None, None))
Mono = collections.namedtuple("Mono", "text")
Badge = collections.namedtuple("Badge", "text")


def joined(groups, separator=", "):
    parts = []
    for i, group in enumerate(groups):
        if i:
            parts.append(separator)
        parts.extend(group)
    return parts
