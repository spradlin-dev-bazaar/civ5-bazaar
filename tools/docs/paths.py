"""Where each page of the docs site goes."""

import os
import posixpath

HOME_PAGE = "index.html"
HOOKS_PAGE = "hooks/index.html"


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
