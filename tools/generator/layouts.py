"""Check that the classes plugins are built against keep their layout.

Plugins compile the engine's headers into themselves, so each class's size, the position of each field and the order
of its virtual functions are baked into every plugin. This compiles every header the SDK ships with the compiler's own
layout report, once with the plugins' defines and once with the host's, and compares the plugins' report with the
committed record: a class that changed or is gone fails the build, and a new one is added to the record.

usage: layouts.py            (run by build-hooked.cmd)
       layouts.py --accept   (run by build-hooked.cmd accept-layouts: save the current layouts as the record; from 1.0
                              on, a changed class is refused unless the major version went up)
"""

import difflib
import os
import re
import subprocess
import sys

import common

RECORD = os.path.join(common.HERE, "class-layouts.txt")
API_HEADER = os.path.join(common.HOST_DIR, "CivPluginApi.h")
# Never included by the engine, and they do not compile beside the other headers.
NOT_COMPILED = {"cvdllfastarifacebase.h", os.path.join("lua", "cvluascopedindirectinstance.h")}

CLASS_HEADER = re.compile(r"^class (.+)\tsize\(\d+\):$")
TABLE_HEADER = re.compile(r"^(\S.*::\$v[fb]table@.*):$")
API_LINE = re.compile(r"^api (\d+)\.(\d+)$")
RELEASE_TAGS = "v[0-9]*"
API_NUMBER = r"^(#define CIV_HOST_API_%s )(\d+)(?=\r?$)"
MAX_CLASSES_SHOWN = 15
MAX_DIFF_LINES = 12


def api_version():
    with open(API_HEADER, encoding="cp1252") as f:
        text = f.read()
    major = re.search(API_NUMBER % "MAJOR", text, re.M)
    minor = re.search(API_NUMBER % "MINOR", text, re.M)
    if not major or not minor:
        raise RuntimeError(
            "%s has no '#define CIV_HOST_API_MAJOR <number>' and '#define CIV_HOST_API_MINOR <number>'"
            % common.shown(API_HEADER)
        )
    return int(major.group(2)), int(minor.group(2))


def set_api_version(major, minor, path=API_HEADER):
    with open(path, encoding="cp1252", newline="") as f:
        text = f.read()
    for name, value in (("MAJOR", major), ("MINOR", minor)):
        text, count = re.subn(API_NUMBER % name, r"\g<1>%d" % value, text, flags=re.M)
        if count != 1:
            raise SystemExit("version: %s does not define CIV_HOST_API_%s exactly once" % (common.shown(path), name))
    with open(path, "w", encoding="cp1252", newline="") as f:
        f.write(text)


def shipped_headers(project):
    headers = []
    for dirpath, _, names in os.walk(project.mirror_dir):
        for name in names:
            rel = os.path.relpath(os.path.join(dirpath, name), project.mirror_dir)
            if name.lower().endswith(".h") and rel.lower() not in NOT_COMPILED:
                headers.append(rel)
    return sorted(headers, key=str.lower)


def write_unit(project, path):
    lines = ['#include "CvGameCoreDLLPCH.h"', '#include "CivHooks.h"', '#include "CivPluginApi.h"']
    lines += ['#include "%s"' % h for h in shipped_headers(project)]
    with open(path, "w", encoding="cp1252") as f:
        f.write("\n".join(lines) + "\n")


def include_dirs(project):
    """Where a plugin finds its headers: the engine's generated copy, which the SDK ships, not the original."""
    support = [os.path.join(common.SOURCE_ROOT, inc) for inc in common.SUPPORT_INCLUDE]
    return [os.path.join(project.build_dir, "sdk"), common.HOST_DIR, project.mirror_dir] + support


def host_defines(project):
    path = os.path.join(project.mirror_dir, os.path.basename(project.vcproj))
    if not os.path.exists(path):
        raise RuntimeError(
            "%s does not exist; build-hooked.cmd generates it before the layout check." % common.shown(path)
        )
    with open(path, encoding="cp1252") as f:
        text = f.read()
    config = re.search(r'<Configuration\s+Name="Mod\|Win32".*?</Configuration>', text, re.S)
    compiler = config and re.search(r'<Tool\s+Name="VCCLCompilerTool"(.*?)/>', config.group(0), re.S)
    defines = compiler and re.search(r'PreprocessorDefinitions="([^"]*)"', compiler.group(1))
    if not defines:
        raise RuntimeError("%s has no Mod|Win32 compiler settings with preprocessor definitions." % common.shown(path))
    return defines.group(1).split(";")


def compile_report(unit, defines, includes):
    # Warnings would be printed into the middle of the report.
    args = ["cl", "/nologo", "/Zs", "/w", "/EHsc", "/MD", "/d1reportAllClassLayout"]
    args += ["/D" + d for d in defines] + ["/I" + i for i in includes] + [unit]
    try:
        done = subprocess.run(args, capture_output=True, cwd=os.path.dirname(unit))
    except FileNotFoundError:
        raise RuntimeError("cl.exe was not found: run this through build-hooked.cmd, which sets up Visual Studio 2008.")
    out = done.stdout.decode("cp1252", "replace")
    if done.returncode:
        lines = (out + done.stderr.decode("cp1252", "replace")).splitlines()
        errors = [line for line in lines if " error " in line] or lines[-20:]
        raise RuntimeError("The headers did not compile for the layout check:\n" + "\n".join(errors[:20]))
    return out


def parse_report(text):
    """The report's blocks as sorted (key, text) pairs: one per class and one per virtual function table."""
    blocks = []
    key, lines = None, []
    for line in text.splitlines():
        line = line.rstrip()
        m = CLASS_HEADER.match(line)
        header = "class " + m.group(1) if m else None
        if not header:
            m = TABLE_HEADER.match(line)
            header = m.group(1) if m else None
        if header:
            if key:
                blocks.append((key, "\n".join(lines)))
            key, lines = header, [line]
        elif key and line:
            lines.append(line)
    if key:
        blocks.append((key, "\n".join(lines)))
    return sorted(blocks)


def format_record(version, blocks):
    return "api %d.%d\n\n" % version + "".join(text + "\n\n" for _, text in sorted(blocks))


def parse_record(text):
    head, _, body = text.partition("\n\n")
    m = API_LINE.match(head)
    if not m:
        raise RuntimeError("%s does not start with 'api <major>.<minor>'" % common.shown(RECORD))
    return (int(m.group(1)), int(m.group(2))), parse_report(body)


def compare(recorded, current):
    """The recorded blocks the current report lacks, each with the current blocks of the same name (None when the name
    is gone), and the new blocks. Classes nested in different classes can share a name, so a name stands for a group of
    blocks."""
    leftover = {}
    for key, text in current:
        leftover.setdefault(key, []).append(text)
    missing = []
    for key, text in recorded:
        if text in leftover.get(key, ()):
            leftover[key].remove(text)
        else:
            missing.append((key, text))
    lost = [(key, text, leftover.get(key) or None) for key, text in missing]
    lost_keys = set(key for key, _ in missing)
    new = sorted((key, text) for key, texts in leftover.items() if key not in lost_keys for text in texts)
    return lost, new


def accept_allowed(recorded_version, version):
    """Before 1.0 a changed class may be accepted on purpose; 1.0 freezes the layouts, and only a later major version
    may change them."""
    return version[0] == 0 or version[0] > max(recorded_version[0], 1)


def shared_names(*reports):
    """The names that more than one block in a single report carries."""
    shared = set()
    for report in reports:
        seen = set()
        for key, _ in report:
            (shared if key in seen else seen).add(key)
    return shared


def describe(lost, shared):
    out = []
    for key, old, now in lost[:MAX_CLASSES_SHOWN]:
        nested = " (one of several classes of this name, nested in different classes)" if key in shared else ""
        if not now:
            out.append("  gone: %s%s" % (key, nested))
            continue
        out.append("  changed: %s%s" % (key, nested))
        closest = max(now, key=lambda text: difflib.SequenceMatcher(None, old, text).ratio())
        diff = list(difflib.unified_diff(old.splitlines(), closest.splitlines(), "record", "now", lineterm="", n=1))[2:]
        out += ["    " + line for line in diff[:MAX_DIFF_LINES]]
        if len(diff) > MAX_DIFF_LINES:
            out.append("    ...")
    if len(lost) > MAX_CLASSES_SHOWN:
        out.append("  and %d more" % (len(lost) - MAX_CLASSES_SHOWN))
    return out


def print_lost(lost, recorded, current):
    print("These classes differ from the record in %s, which every plugin was built against:" % common.shown(RECORD))
    print("\n".join(describe(lost, shared_names(recorded, current))))


def last_release_tag():
    try:
        done = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", RELEASE_TAGS],
            capture_output=True,
            text=True,
            cwd=common.REPO,
        )
    except FileNotFoundError:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def frozen_advice(recorded_version, tag):
    """The way out when a changed class is refused, which cannot tell a released major version from one still being
    worked on."""
    released = re.match(r"v(\d+)", tag or "")
    if recorded_version[0] == 0 and not (released and int(released.group(1)) >= 1):
        return [
            "1.0 freezes the layouts the 0.x versions left, and no 1.0 release is tagged yet. To change a class",
            "for it, set CIV_HOST_API_MAJOR in host\\CivPluginApi.h back to 0, run build-hooked.cmd accept-layouts,",
            "then set it to 1 again and rebuild every plugin.",
        ]
    return [
        "From 1.0 on, a class can change only in a new major version. Either:",
        "- raise CIV_HOST_API_MAJOR in host\\CivPluginApi.h, then run build-hooked.cmd accept-layouts and rebuild every"
        " plugin; or",
        "- if you already raised it and accepted another change for that version, and it is not released yet, put back",
        "  the record of the last release with: git checkout %s -- %s"
        % (tag or "<last release tag>", common.shown(RECORD)),
        "  then run build-hooked.cmd accept-layouts, which accepts all of the new version's changes together.",
    ]


def read_record(version):
    if os.path.exists(RECORD):
        with open(RECORD, encoding="cp1252") as f:
            return parse_record(f.read())
    if version[0] >= 1:
        raise RuntimeError(
            "%s is missing. From 1.0 on it cannot be made again: restore it from git." % common.shown(RECORD)
        )
    return None, []


def write_record(version, blocks):
    with open(RECORD, "w", encoding="cp1252", newline="\n") as f:
        f.write(format_record(version, blocks))


def current_layouts(project):
    folder = os.path.join(project.build_dir, "layouts")
    os.makedirs(folder, exist_ok=True)
    unit = os.path.join(folder, "all-headers.cpp")
    write_unit(project, unit)
    includes = include_dirs(project)
    plugin = parse_report(compile_report(unit, common.PLUGIN_DEFINES, includes))
    if not plugin:
        raise RuntimeError("The compiler reported no class layouts, so nothing could be checked.")
    defines = host_defines(project)
    host = parse_report(compile_report(unit, defines, includes))
    if host != plugin:
        keys = sorted(set(key for key, _ in set(host) ^ set(plugin)))
        lines = [
            "A header lays out these classes differently for the host than for plugins, because of a define only one"
            " side sets:"
        ]
        lines += ["  " + key for key in keys[:MAX_CLASSES_SHOWN]]
        if len(keys) > MAX_CLASSES_SHOWN:
            lines.append("  and %d more" % (len(keys) - MAX_CLASSES_SHOWN))
        for side, only in [
            ("the host sets, in the generated engine project", set(defines) - set(common.PLUGIN_DEFINES)),
            ("plugins set, in tools\\generator\\common.py", set(common.PLUGIN_DEFINES) - set(defines)),
        ]:
            if only:
                lines.append("Defines only %s: %s" % (side, ", ".join(sorted(only))))
        raise RuntimeError("\n".join(lines))
    return plugin


def check(project):
    current = current_layouts(project)
    version = api_version()
    recorded_version, recorded = read_record(version)
    lost, new = compare(recorded, current)
    if lost:
        print_lost(lost, recorded, current)
        if not any(now for _, _, now in lost):
            print("A gone class can be accepted at any version, once no plugin uses it:")
            print("run build-hooked.cmd accept-layouts.")
        elif accept_allowed(recorded_version, version):
            print("To change them on purpose, run build-hooked.cmd accept-layouts, then rebuild every plugin.")
        else:
            print("\n".join(frozen_advice(recorded_version, last_release_tag())))
        return 1
    if new or not recorded_version:
        write_record(recorded_version or version, recorded + new)
    print("class layouts: %d match %s, %d new added to it" % (len(recorded), common.shown(RECORD), len(new)))
    return 0


def accept(project):
    current = current_layouts(project)
    version = api_version()
    recorded_version, recorded = read_record(version)
    lost, _ = compare(recorded, current)
    changed = any(now for _, _, now in lost)
    if changed and not accept_allowed(recorded_version, version):
        print_lost(lost, recorded, current)
        print("\n".join(frozen_advice(recorded_version, last_release_tag())))
        return 1
    saved = version if changed or not recorded_version else recorded_version
    write_record(saved, current)
    print("Saved %d layouts as the record for API %d.%d." % (len(current), saved[0], saved[1]))
    if changed:
        print("Rebuild every plugin.")
    return 0


def main(args):
    if args not in ([], ["--accept"]):
        print(__doc__)
        return 1
    project = common.engine_project()
    try:
        return accept(project) if args else check(project)
    except RuntimeError as e:
        print(e)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
