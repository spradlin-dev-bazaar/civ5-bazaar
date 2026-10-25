"""Where each page of the docs site goes."""

import os
import posixpath

HOME_PAGE = "index.html"
HOOKS_PAGE = "hooks/index.html"
NOTICE_FILE = "NOTICE.txt"
LICENSE_FILE = "LICENSE.txt"


def posix(rel):
    return rel.replace(os.sep, "/")


def file_dir(rel):
    return "reference/" + posix(rel)


def file_page(rel):
    return file_dir(rel) + "/index.html"


def folder_page(folder):
    return "reference/%sindex.html" % (folder + "/" if folder else "")


def hook_page(hook):
    return "hooks/%s.html" % hook


def rel_link(page, target):
    return posixpath.relpath(target, posixpath.dirname(page) or ".")


def markdown_page(page):
    if not page.endswith(".html"):
        raise ValueError("%s is not a page" % page)
    return page[: -len(".html")] + ".md"
