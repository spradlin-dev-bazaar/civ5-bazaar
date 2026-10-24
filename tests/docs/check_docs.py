"""The test engine is copied with Windows line ends, as the game's source has them, so offset handling is tested."""

import glob
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools", "docs"))

import build_docs  # noqa: E402
import common  # noqa: E402
import history  # noqa: E402
import model  # noqa: E402
import pages  # noqa: E402

OUT = os.path.join(HERE, "out")
SITE = os.path.join(OUT, "site")
HAND_HOOKS = os.path.join(HERE, "hand-placed-hooks.md")
NO_HISTORY = os.path.join(OUT, "no-history.txt")
THING = "reference/docs_engine.cpp/Thing/"
DECLARATIONS = {
    "Thing::Score(bool) const": [
        "static bool BeforeThing_Score(const Thing* self, bool bFinal, int& result);",
        "static int ReplaceThing_Score(int (*original)(const Thing*, bool), const Thing* self, bool bFinal);",
        "host->RegisterHook(host->pluginIndex, CivHooks::Thing_Score::ID, CIV_HOOK_AFTER, (void*)&AfterThing_Score);",
    ],
    "Thing::Get(int)": ["static bool BeforeThing_Get(int i, Thing*& result);"],
    "Thing::Level() const": ["static bool BeforeThing_Level(const Thing* self, int& result);"],
    "Thing::Name() const": ["static bool BeforeThing_Name(const Thing* self, const char*& result);"],
    "Thing::Self() const": ["static bool BeforeThing_Self(const Thing* self, const Thing*& result);"],
    "Thing::Reset()": [
        "static bool BeforeThing_Reset(Thing* self);",
        "static void ReplaceThing_Reset(void (*original)(Thing*), Thing* self);",
    ],
    "Thing::Weight(int) const": ["static bool BeforeThing_Weight(const Thing* self, int arg0, int& result);"],
    "Thing::operator==(const Thing &) const": [
        "static bool BeforeThing_op_eq(const Thing* self, const Thing& other, bool& result);"
    ],
    "Setup::Option::GetValue() const": [
        "static bool BeforeSetup_Option_GetValue(const Setup::Option* self, int& result);"
    ],
}


def crlf_copy(sources, name):
    root = os.path.join(OUT, name)
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(root)
    for file_name, data in sources:
        with open(os.path.join(root, file_name), "wb") as f:
            f.write(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return root


def project(root, sources):
    return common.Project(root, sources, [root], os.path.join(root, "build"), os.path.join(root, "hook-ids.txt"))


def fixture_project(name, edits=()):
    fixture = {}
    for path in glob.glob(os.path.join(HERE, "fixture", "*")):
        with open(path, "rb") as f:
            fixture[os.path.basename(path)] = f.read().replace(b"\r\n", b"\n").decode("utf-8")
    for file_name, old, new in edits:
        if old not in fixture[file_name]:
            raise SystemExit("FAIL: the test's edit %r is not in %s" % (old, file_name))
        fixture[file_name] = fixture[file_name].replace(old, new, 1)
    sources = [(file_name, text.encode("utf-8")) for file_name, text in sorted(fixture.items())]
    return project(crlf_copy(sources, name), ["docs_engine.cpp"])


def build():
    return build_docs.build(fixture_project("fixture"), SITE, HAND_HOOKS, NO_HISTORY)


def fixture_line(text):
    with open(os.path.join(HERE, "fixture", "docs_engine.cpp"), encoding="utf-8") as f:
        return next(i for i, line in enumerate(f, 1) if text in line)


def by_title(site, title):
    return next((fn for fn in site.engine.functions if fn["title"] == title), None)


def expect(site, title, *texts):
    fn = by_title(site, title)
    if fn is None:
        return ["no function %s" % title]
    page = site.pages[fn["page"]]
    return ["the page of %s does not contain %r" % (title, t) for t in texts if t not in page]


def unwanted(site, title, *texts):
    fn = by_title(site, title)
    if fn is None:
        return ["no function %s" % title]
    page = site.pages[fn["page"]]
    return ["the page of %s contains %r" % (title, t) for t in texts if t in page]


def naming_problems(site):
    problems = []
    for path in ["Get.html", "Score-bool-const.html", "Score-int_int.html", "operator_eq.html", "Inline.html"]:
        if THING + path not in site.pages:
            problems.append("no page %s" % (THING + path))
    totals = [p for p in site.pages if p.startswith((THING + "Total-", THING + "total-"))]
    if len(totals) != 2 or len({p.lower() for p in totals}) != 2:
        problems.append("Total and total do not get pages whose names differ in more than case: %s" % totals)
    if THING + "index.html" not in site.pages or not [p for p in site.pages if p.startswith(THING + "index-")]:
        problems.append("the function named index took the class page's name")
    for path in site.pages:
        if not os.path.isfile(os.path.join(SITE, *path.split("/"))):
            problems.append("%s was not written" % path)
    return problems


def code_problems(site):
    greyed = [fixture_line(t) for t in ("#define DOCS_UNUSED", "return 0;")]
    plain = [fixture_line(t) for t in ("#if defined(DOCS_NEVER)", "#else", "return Inline()", "#endif")]
    problems = expect(
        site,
        "Thing::Score(bool) const",
        "/// The thing&#x27;s score.",
        'title="Thing::Inline() const">Inline</a>',
        *['<span class="line greyed" id="L%d">' % n for n in greyed],
        *['<span class="line" id="L%d">' % n for n in plain],
    )
    problems += unwanted(site, "Thing::Score(bool) const", "-----")
    problems += expect(
        site,
        "Thing::Score(int, int)",
        '<span class="line marked" id="L%d">' % fixture_line("CivHandPopupRaised(iBase)"),
        'title="Thing::Score(bool) const">Score</a>',
        "GameEvents.CityBuilt",
        "../../../hooks/PopupRaised.html",
        "does not call <code>original</code>",
    )
    problems += expect(site, "Thing::total()", 'href="Get.html" title="Thing::Get(int)">GET_THING</a>')
    problems += expect(site, "Measure(const Shape &)", 'title="Shape::Area() const">Area</a>')
    problems += expect(site, "Count()", ">Counter::Counter(int)</a>")
    problems += unwanted(site, "Count()", 'title="Counter::Counter(int)"')
    problems += expect(site, "Counter::Counter(int)", "Hand-placed hooks inside")
    problems += unwanted(site, "Counter::Counter(int)", "does not call")
    return problems


def fact_problems(site):
    problems = expect(site, "BetterThing::Score(bool) const", "Thing::Score(bool) const</a>")
    problems += expect(site, "Thing::Inline() const", "written in a header")
    problems += expect(site, "Square::Area() const", "Shape::Area() const</a>")
    problems += expect(site, "Shape::Area() const", model.PURE_REASON, "Square::Area() const</a>")
    problems += expect(site, "Thing::Score(int, int)", "CivHooks::Thing_Score_with_int_int")
    for title, lines in DECLARATIONS.items():
        fn = by_title(site, title)
        declarations = fn.get("declarations", "") if fn else ""
        problems += ["the hooks of %s do not include %r" % (title, line) for line in lines if line not in declarations]
    hook = site.pages.get("hooks/PopupRaised.html", "")
    for text in ["Thing::Score(int, int)</a>", "Score-int_int.html#L"]:
        if text not in hook:
            problems.append("hooks/PopupRaised.html does not contain %r" % text)
    if "reference/index.html" not in site.pages["index.html"]:
        problems.append("the home page does not link to the game's code")
    return problems


def search_problems(site):
    rows = site.search_rows()
    problems = ["the search index leads to %s, which has no page" % t for _, t in rows if t not in site.pages]
    labels = {label for label, _ in rows}
    for label in ["Thing::Get(int)", "Setup::Option (class)", "docs_shapes.h (file)"]:
        if label not in labels:
            problems.append("the search index does not list %s" % label)
    if "docs_engine.h (file)" in labels:
        problems.append("the search index lists docs_engine.h, whose code all sits under its classes")
    return problems


def stop_problems():
    problems = []
    broken = crlf_copy([("broken.cpp", b"int broken = ;\n")], "broken")
    try:
        build_docs.build(project(broken, ["broken.cpp"]), os.path.join(OUT, "broken-site"), HAND_HOOKS, NO_HISTORY)
        problems.append("a parse error outside a function did not stop the build")
    except SystemExit as e:
        if "parse errors" not in str(e):
            problems.append("a parse error stopped the build with %r" % str(e))
    with open(HAND_HOOKS, encoding="utf-8") as f:
        text = f.read()
    extra = os.path.join(OUT, "extra-hooks.md")
    with open(extra, "w", encoding="utf-8") as f:
        f.write(text + "\n## NotCalled\n\nNo engine function calls this one.\n")
    try:
        build_docs.build(fixture_project("extra"), os.path.join(OUT, "extra-site"), extra, NO_HISTORY)
        problems.append("a described hand-placed hook that nothing calls did not stop the build")
    except SystemExit as e:
        if "NotCalled" not in str(e):
            problems.append("an uncalled hand-placed hook stopped the build with %r" % str(e))
    marked = os.path.join(OUT, "bom-hooks.md")
    with open(marked, "w", encoding="utf-8-sig") as f:
        f.write(text)
    site = build_docs.build(fixture_project("bom"), os.path.join(OUT, "bom-site"), marked, NO_HISTORY)
    if site.pages["hooks/index.html"].count("<h1>") != 1:
        problems.append("a hand-placed hooks file saved with a byte order mark shows its title twice")
    return problems


ADD_FUNCTION = ("docs_engine.cpp", "int FreeHelper(int x)", "int Added()\n{\n\treturn 5;\n}\n\nint FreeHelper(int x)")
HOOK_TOTAL = (
    "docs_engine.cpp",
    "int Thing::Total()\n{\n\treturn 1;",
    "int Thing::Total()\n{\n#if defined(CIV_HOST_API)\n\tCivHandPopupRaised(1);\n#endif\n\treturn 1;",
)
SPACE_RESET = (
    "docs_engine.cpp",
    "void Thing::Reset()\n{\n\tm_i = 0;",
    "void Thing::Reset()\n{\n\t// Back to the start.\n\tm_i  =  0;",
)
TOTAL_RETURNS_2 = (
    "docs_engine.cpp",
    "CivHandPopupRaised(1);\n#endif\n\treturn 1;",
    "CivHandPopupRaised(1);\n#endif\n\treturn 2;",
)
RELEASE_EDITS = [ADD_FUNCTION, HOOK_TOTAL, SPACE_RESET]


def marked(site):
    return sorted(fn["title"] for fn in site.engine.functions if fn["added_in"] or fn["changed_in"])


def lines_of(copy, start):
    with open(os.path.join(OUT, copy, "docs_engine.cpp"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    first = next(i for i, line in enumerate(lines, 1) if start in line)
    return first, next(i for i, line in enumerate(lines[first - 1 :], first) if line == "}")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def history_problems():
    problems = []
    path = os.path.join(OUT, "function-history.txt")
    if os.path.exists(path):
        os.remove(path)

    def run(name, release, edits=()):
        site = os.path.join(OUT, name + "-site")
        return build_docs.build(fixture_project(name, edits), site, HAND_HOOKS, path, release)

    def refused(name, release, edits, reason):
        before = read(path)
        try:
            run(name, release, edits)
            problems.append("release %r did not stop the build" % release)
        except SystemExit as e:
            if reason not in str(e):
                problems.append("release %r stopped the build with %r" % (release, str(e)))
        if read(path) != before:
            problems.append("release %r changed the function history" % release)

    first = run("release-1", "0.1.0")
    if marked(first):
        problems.append("the first release marked %s" % marked(first))
    second = run("release-2", "0.2.0", RELEASE_EDITS)
    if marked(second) != ["Added()", "Thing::Total()"]:
        problems.append("release 0.2.0 marked %s, not Added() and Thing::Total()" % marked(second))
    problems += expect(second, "Added()", "<dt>Added in</dt><dd>0.2.0</dd>")
    blame = "blame/v0.2.0/tests/docs/out/release-2/docs_engine.cpp#L%d-L%d" % lines_of(
        "release-2", "int Thing::Total()"
    )
    problems += expect(second, "Thing::Total()", blame, ">0.2.0</a> (added hand-placed hook PopupRaised)")
    saved = read(path)
    again = run("release-2", "0.2.0", RELEASE_EDITS)
    if read(path) != saved:
        problems.append("building release 0.2.0 again changed the function history")
    if marked(again) != marked(second):
        problems.append("building release 0.2.0 again marked %s" % marked(again))
    refused("release-2-edited", "0.2.0", RELEASE_EDITS + [TOTAL_RETURNS_2], "the code has changed since")
    unreleased = by_title(run("unreleased", None, RELEASE_EDITS + [TOTAL_RETURNS_2]), "Thing::Total()") or {}
    saved_total = history.load(path)[1].get(unreleased.get("history_key"))
    if not saved_total or unreleased["fingerprint"] == saved_total.fingerprint:
        problems.append("the unreleased edit to Thing::Total() did not change its code")
    elif [c.release for c in unreleased["changed_in"]] != ["0.2.0"]:
        problems.append("an unreleased edit changed the marks of Thing::Total()")
    third = by_title(run("release-3", "0.3.0", [HOOK_TOTAL, SPACE_RESET, TOTAL_RETURNS_2]), "Thing::Total()") or {}
    releases = [c.release for c in third.get("changed_in", [])]
    if releases != ["0.2.0", "0.3.0"]:
        problems.append("after release 0.3.0, Thing::Total() is changed in %s, not 0.2.0 and 0.3.0" % releases)
    gone = history.load(path)[1].get("Added() @docs_engine.cpp")
    if not gone or gone.added != "0.2.0":
        problems.append("release 0.3.0 dropped the history of Added(), which its code no longer has")
    for release, reason in (("0.2.5", "later than"), ("1.0", "three numbers"), ("", "three numbers")):
        refused("refused", release, RELEASE_EDITS, reason)
    plural = pages.change_mark(history.Change("0.4.0", "x.cpp", 1, 2, ("PopupRaised", "DealResolved")))
    if "(added hand-placed hooks PopupRaised, DealResolved)" not in plural:
        problems.append("a change that added two hand-placed hooks reads %r" % plural)
    damaged = os.path.join(OUT, "damaged-history.txt")
    with open(damaged, "w", encoding="utf-8") as f:
        f.write("release\t0.1.0\nnot a history line\n")
    try:
        build_docs.build(fixture_project("damaged"), os.path.join(OUT, "damaged-site"), HAND_HOOKS, damaged)
        problems.append("a damaged function history did not stop the build")
    except SystemExit as e:
        if "line 2 of" not in str(e):
            problems.append("a damaged function history stopped the build with %r" % str(e))
    return problems


class FakeSite:
    def __init__(self, pages):
        self.pages = pages

    def search_index(self):
        return ""


def write_problems():
    problems = []
    stray = os.path.join(OUT, "stray")
    os.makedirs(stray, exist_ok=True)
    with open(os.path.join(stray, "keep.txt"), "w") as f:
        f.write("keep")
    try:
        build_docs.write(FakeSite({}), stray)
        problems.append("a folder that is not a docs build was emptied")
    except SystemExit:
        if not os.path.isfile(os.path.join(stray, "keep.txt")):
            problems.append("the stray folder was emptied")
    stopped = os.path.join(OUT, "stopped")
    if os.path.isdir(stopped):
        shutil.rmtree(stopped)
    try:
        build_docs.write(FakeSite({"index.html": "x", "bad\0.html": "x"}), stopped)
    except ValueError:
        pass
    try:
        build_docs.write(FakeSite({"index.html": "x"}), stopped)
    except SystemExit:
        problems.append("a write stopped part way blocked the next one")
    return problems


if __name__ == "__main__":
    site = build()
    problems = naming_problems(site) + code_problems(site) + fact_problems(site) + search_problems(site)
    problems += stop_problems() + write_problems() + history_problems()
    if problems:
        print("FAIL: " + "; ".join(problems))
        sys.exit(1)
    print("PASS: docs checks")
    sys.exit(0)
