"""The test engine is copied with Windows line ends, as the game's source has them, so offset handling is tested."""

import glob
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "..", "tools")
sys.path[:0] = [os.path.join(TOOLS, "docs"), os.path.join(TOOLS, "generator"), TOOLS]

import build_docs  # noqa: E402
import common  # noqa: E402
import handwritten  # noqa: E402
import history  # noqa: E402
import model  # noqa: E402
import pages  # noqa: E402
import render  # noqa: E402
import render_md  # noqa: E402
from outline import Entries  # noqa: E402

OUT = os.path.join(HERE, "out")
SITE = os.path.join(OUT, "site")
HAND_HOOKS = os.path.join(HERE, "hand-placed-hooks.md")
NO_HISTORY = os.path.join(OUT, "no-history.txt")
INPUTS = handwritten.Inputs(
    hand_hooks=HAND_HOOKS,
    task_guide=os.path.join(HERE, "task-guide.md"),
    class_summaries=os.path.join(HERE, "class-summaries.md"),
    function_notes=os.path.join(HERE, "function-notes.md"),
)
THING = "reference/docs_engine.cpp/Thing/"
OPTION = "reference/docs_engine.cpp/Setup.Option/"
DECLARATIONS = {
    "Thing::Score(bool) const": [
        "static bool BeforeThing_Score(const Thing* self, bool bFinal, int& result);",
        "static int ReplaceThing_Score(int (*original)(const Thing*, bool), const Thing* self, bool bFinal);",
        "CivRegisterAfter<CivHooks::Thing_Score>(host, &AfterThing_Score);",
    ],
    "Thing::Get(int)": ["static bool BeforeThing_Get(int i, Thing*& result);"],
    "Thing::Level() const": ["static bool BeforeThing_Level(const Thing* self, int& result);"],
    "Thing::Name() const": ["static bool BeforeThing_Name(const Thing* self, const char*& result);"],
    "Thing::Self() const": ["static bool BeforeThing_Self(const Thing* self, const Thing*& result);"],
    "Thing::Weight(int) const": ["static bool BeforeThing_Weight(const Thing* self, int arg0, int& result);"],
    "Thing::operator==(const Thing &) const": [
        "static bool BeforeThing_op_eq(const Thing* self, const Thing& other, bool& result);"
    ],
    "Setup::Option::GetValue() const": [
        "static bool BeforeSetup_Option_GetValue(const Setup::Option* self, int& result);"
    ],
}
WHOLE_DECLARATIONS = {
    "Thing::Reset()": """static bool BeforeThing_Reset(Thing* self);
static void AfterThing_Reset(Thing* self);
static void ReplaceThing_Reset(void (*original)(Thing*), Thing* self);

CivRegisterBefore<CivHooks::Thing_Reset>(host, &BeforeThing_Reset);
CivRegisterAfter<CivHooks::Thing_Reset>(host, &AfterThing_Reset);
CivRegisterReplace<CivHooks::Thing_Reset>(host, &ReplaceThing_Reset);
""",
    "Measure(const Shape &)": """static bool BeforeMeasure(const Shape& shape, int& result);
static void AfterMeasure(const Shape& shape, int& result);
static int ReplaceMeasure(int (*original)(const Shape&), const Shape& shape);

// CivHooks.h gives this hook point no types, so nothing checks these hooks' parameters.
host->RegisterHook(host->pluginIndex, CivHooks::Measure::ID, CIV_HOOK_BEFORE, (void*)&BeforeMeasure);
host->RegisterHook(host->pluginIndex, CivHooks::Measure::ID, CIV_HOOK_AFTER, (void*)&AfterMeasure);
host->RegisterHook(host->pluginIndex, CivHooks::Measure::ID, CIV_HOOK_REPLACE, (void*)&ReplaceMeasure);
""",
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
    registry = os.path.join(root, "hook-ids.txt")
    return common.Project(root, sources, [root], os.path.join(root, "build"), registry, plugin_include="docs_engine.h")


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
    return project(crlf_copy(sources, name), ["docs_engine.cpp", "docs_more.cpp"])


def build_fixture(project, out, history_path=NO_HISTORY, release=None, **inputs):
    return build_docs.build(project, out, inputs=INPUTS._replace(**inputs), history_path=history_path, release=release)


def fixture_build(name, edits=(), **options):
    return build_fixture(fixture_project(name, edits), os.path.join(OUT, name + "-site"), **options)


def stopped(what, reason, build):
    try:
        build()
    except SystemExit as e:
        return [] if reason in str(e) else ["%s stopped the build with %r" % (what, str(e))]
    return ["%s did not stop the build" % what]


def write_input(name, text, encoding="utf-8"):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding=encoding) as f:
        f.write(text)
    return path


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def fixture_line(text):
    with open(os.path.join(HERE, "fixture", "docs_engine.cpp"), encoding="utf-8") as f:
        return next(i for i, line in enumerate(f, 1) if text in line)


def closing_line(text):
    with open(os.path.join(HERE, "fixture", "docs_engine.cpp"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    start = fixture_line(text)
    return next(i for i, line in enumerate(lines[start - 1 :], start) if line == "}")


def by_title(site, title):
    return next((fn for fn in site.engine.functions if fn["title"] == title), None)


def page_problems(site, title, texts, wanted):
    fn = by_title(site, title)
    if fn is None:
        return ["no function %s" % title]
    page = site.html[fn["page"]]
    verb = "does not contain" if wanted else "contains"
    return ["the page of %s %s %r" % (title, verb, t) for t in texts if (t in page) != wanted]


def expect(site, title, *texts):
    return page_problems(site, title, texts, True)


def unwanted(site, title, *texts):
    return page_problems(site, title, texts, False)


def section_of(page, heading):
    start = page.find("<h2>%s</h2>" % heading)
    return page[start : page.find("</section>", start)] if start >= 0 else ""


def naming_problems(site):
    problems = []
    for path in ["Get.html", "Score-bool-const.html", "Score-int_int.html", "operator_eq.html", "Inline.html"]:
        if THING + path not in site.html:
            problems.append("no page %s" % (THING + path))
    totals = [p for p in site.html if p.startswith((THING + "Total-", THING + "total-"))]
    if len(totals) != 2 or len({p.lower() for p in totals}) != 2:
        problems.append("Total and total do not get pages whose names differ in more than case: %s" % totals)
    if THING + "index.html" not in site.html or not [p for p in site.html if p.startswith(THING + "index-")]:
        problems.append("the function named index took the class page's name")
    inline = [p for p in site.html if "Inline" in p]
    if inline != [THING + "Inline.html"]:
        problems.append("Thing::Inline, written in a header two source files include, has the pages %s" % inline)
    if [p for p in site.html if "DOCS_ENGINE" in p]:
        problems.append("a page takes its name from an #include spelled in another case")
    for path in site.html:
        if not os.path.isfile(os.path.join(SITE, *path.split("/"))):
            problems.append("%s was not written" % path)
    for name in render.SUPPORT_FILES:
        if not os.path.isfile(os.path.join(SITE, name)):
            problems.append("%s was not written" % name)
    if not read(os.path.join(SITE, render.INDEX_FILE)).startswith("window.BAZAAR_INDEX = [["):
        problems.append("the search index does not start with window.BAZAAR_INDEX = [[")
    if 'data-index="search-index.js"' not in site.html["index.html"]:
        problems.append("the pages do not tell search.js where the search index is")
    return problems


def code_problems(site):
    greyed = [
        fixture_line(t)
        for t in (
            "#define DOCS_UNUSED",
            "#ifdef DOCS_INNER",
            "CivHandPopupRaised(0)",
            "#endif // DOCS_INNER",
            "return 0;",
        )
    ]
    plain = [fixture_line(t) for t in ("#if defined(DOCS_NEVER)", "#else", "return Inline()", "#endif\n")]
    problems = expect(
        site,
        "Thing::Score(bool) const",
        "/// The thing&#x27;s score.",
        'title="Thing::Inline() const">Inline</a>',
        *['<span class="line greyed" id="L%d">' % n for n in greyed],
        *['<span class="line" id="L%d">' % n for n in plain],
    )
    problems += unwanted(site, "Thing::Score(bool) const", "-----", "Hand-placed hooks inside")
    problems += expect(site, "Count()", "// Counts.")
    problems += unwanted(site, "Count()", "-----")
    problems += expect(site, "Thing::Reset()", "// Resets.")
    problems += unwanted(site, "Thing::Reset()", "- - -")
    problems += unwanted(site, "Setup::Option::GetValue() const", "////")
    weight_greyed = [fixture_line(t) for t in ("#ifdef DOCS_OTHER", "return 30;", "#endif // DOCS_OTHER", "return 40;")]
    weight_plain = [fixture_line(t) for t in ("return 20;", "#else // not CIV_HOST_API", "#endif // CIV_HOST_API")]
    problems += expect(
        site,
        "Thing::Weight(int) const",
        *['<span class="line greyed" id="L%d">' % n for n in weight_greyed],
        *['<span class="line" id="L%d">' % n for n in weight_plain],
    )
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
    if not by_title(site, "Broken()") or site.engine.body_errors < 1:
        problems.append("an error inside a function body was not counted, or the function lost its page")
    return problems


def fact_problems(site):
    problems = expect(site, "BetterThing::Score(bool) const", "<dt>Overrides</dt><dd><a ")
    problems += expect(site, "Thing::Inline() const", "written in a header")
    problems += expect(site, "Square::Area() const", "Shape::Area() const</a>")
    problems += expect(site, "Shape::Area() const", model.PURE_REASON, "Square::Area() const</a>")
    problems += expect(site, "Thing::Score(int, int)", "CivHooks::Thing_Score_with_int_int")
    for title, lines in DECLARATIONS.items():
        fn = by_title(site, title)
        declarations = fn.get("declarations", "") if fn else ""
        problems += ["the hooks of %s do not include %r" % (title, line) for line in lines if line not in declarations]
    for title, block in WHOLE_DECLARATIONS.items():
        fn = by_title(site, title) or {}
        if fn.get("declarations") != block:
            problems.append("the hooks of %s read %r" % (title, fn.get("declarations")))
    square = site.html["reference/docs_engine.cpp/Square/index.html"]
    shape = site.html["reference/docs_shapes.h/Shape/index.html"]
    wanted = [
        (square, "<dt>Declared in</dt><dd>docs_shapes.h, line 9</dd>"),
        (square, '<dt>Based on</dt><dd><a href="../../docs_shapes.h/Shape/index.html">Shape</a></dd>'),
        (shape, '<dt>Classes based on it</dt><dd><a href="../../docs_engine.cpp/Square/index.html">Square</a></dd>'),
    ]
    problems += ["a class page does not contain %r" % text for page, text in wanted if text not in page]
    if "reference/index.html" not in site.html["index.html"]:
        problems.append("the home page does not link to the game's code")
    return problems


def caller_problems(site):
    problems = []
    wanted = {
        "Thing::Get(int)": [">Thing::total()</a>", ">FreeHelper(int)</a>", ">Second()</a>"],
        "Thing::Inline() const": [">Thing::Score(bool) const</a>", ">Second()</a>"],
        "Shape::Area() const": [">Measure(const Shape &amp;)</a>"],
    }
    for title, callers in wanted.items():
        fn = by_title(site, title)
        called_by = section_of(site.html[fn["page"]], "Called by") if fn else ""
        for caller in callers:
            if called_by.count(caller) != 1:
                problems.append("%s is not listed once among the callers of %s" % (caller, title))
    hook = section_of(site.html["hooks/PopupRaised.html"], "Where it fires")
    for text in ["Score-int_int.html#L%d" % fixture_line("CivHandPopupRaised(iBase)"), "Counter.html#L"]:
        if text not in hook:
            problems.append("hooks/PopupRaised.html does not list %r where it fires" % text)
    if "Score-bool-const.html" in hook:
        problems.append("hooks/PopupRaised.html lists a call in code the build leaves out")
    return problems


def search_problems(site):
    rows = site.search_rows()
    problems = ["the search index leads to %s, which has no page" % t for _, t in rows if t not in site.html]
    labels = {label for label, _ in rows}
    for label in ["Thing::Get(int)", "Setup::Option (class)", "docs_shapes.h (file)", "PopupRaised (hand-placed hook)"]:
        if label not in labels:
            problems.append("the search index does not list %s" % label)
    if "docs_engine.h (file)" in labels:
        problems.append("the search index lists docs_engine.h, whose code all sits under its classes")
    return problems


def stop_problems():
    broken = crlf_copy([("broken.cpp", b"int broken = ;\n")], "broken")
    problems = stopped(
        "a parse error outside a function",
        "parse errors",
        lambda: build_fixture(project(broken, ["broken.cpp"]), os.path.join(OUT, "broken-site")),
    )
    text = read(HAND_HOOKS)
    extra = write_input("extra-hooks.md", text + "\n## NotCalled\n\nNo engine function calls this one.\n")
    problems += stopped(
        "a described hand-placed hook that nothing calls", "NotCalled", lambda: fixture_build("extra", hand_hooks=extra)
    )
    site_folder = os.path.join(OUT, "dead-link-site")
    if os.path.isdir(site_folder):
        shutil.rmtree(site_folder)
    dead = write_input("dead-link-hooks.md", text + "\nSee [the other one](nope.html).\n")
    problems += stopped(
        "a link to a page that does not exist", "broken links", lambda: fixture_build("dead-link", hand_hooks=dead)
    )
    if os.path.exists(site_folder):
        problems.append("a build stopped by a broken link wrote its site")
    bom_hooks = write_input("bom-hooks.md", text, encoding="utf-8-sig")
    site = fixture_build("bom", hand_hooks=bom_hooks)
    if site.html["hooks/index.html"].count("<h1>") != 1:
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
MOVE_TOTAL = ("docs_engine.cpp", "int Thing::Total()", "// Moved down a line.\nint Thing::Total()")
CHANGE_ADDED = ("docs_engine.cpp", "int FreeHelper(int x)", "int Added()\n{\n\treturn 6;\n}\n\nint FreeHelper(int x)")
REMOVE_INDEX = ("docs_engine.cpp", "void Thing::index()\n{\n}\n", "")
RELEASE_EDITS = [ADD_FUNCTION, HOOK_TOTAL, SPACE_RESET]


def marked(site):
    return sorted(fn["title"] for fn in site.engine.functions if fn["added_in"] or fn["changed_in"])


def lines_of(copy, start):
    with open(os.path.join(OUT, copy, "docs_engine.cpp"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    first = next(i for i, line in enumerate(lines, 1) if start in line)
    return first, next(i for i, line in enumerate(lines[first - 1 :], first) if line == "}")


class Releases:
    """The release builds share one function history, so each scenario starts from what the one before saved."""

    def __init__(self):
        self.path = os.path.join(OUT, "function-history.txt")
        if os.path.exists(self.path):
            os.remove(self.path)

    def run(self, name, release, edits=()):
        fixture = fixture_project(name, edits)
        model.Engine(fixture).registry.save()
        return build_fixture(fixture, os.path.join(OUT, name + "-site"), history_path=self.path, release=release)

    def refused(self, name, release, edits, reason):
        before = read(self.path)
        problems = stopped("release %r" % release, reason, lambda: self.run(name, release, edits))
        if read(self.path) != before:
            problems.append("release %r changed the function history" % release)
        return problems


def first_releases(releases):
    problems = []
    first = releases.run("release-1", "0.1.0")
    if marked(first):
        problems.append("the first release marked %s" % marked(first))
    second = releases.run("release-2", "0.2.0", RELEASE_EDITS)
    if marked(second) != ["Added()", "Thing::Total()"]:
        problems.append("release 0.2.0 marked %s, not Added() and Thing::Total()" % marked(second))
    problems += expect(second, "Added()", "<dt>Added in</dt><dd>0.2.0</dd>")
    problems += unwanted(second, "Thing::Total()", "<dt>Added in</dt>")
    blame = "blame/v0.2.0/tests/docs/out/release-2/docs_engine.cpp#L%d-L%d" % lines_of(
        "release-2", "int Thing::Total()"
    )
    hook_link = '<a href="../../../hooks/PopupRaised.html">PopupRaised</a>'
    problems += expect(second, "Thing::Total()", blame, ">0.2.0</a> (added hand-placed hook %s)" % hook_link)
    return problems, second


def rebuilt_release(releases, second):
    problems = []
    saved = read(releases.path)
    again = releases.run("release-2", "0.2.0", RELEASE_EDITS)
    if read(releases.path) != saved:
        problems.append("building release 0.2.0 again changed the function history")
    if marked(again) != marked(second):
        problems.append("building release 0.2.0 again marked %s" % marked(again))
    moved = releases.run("release-2", "0.2.0", RELEASE_EDITS + [MOVE_TOTAL])
    change = history.load(releases.path)[1]["Thing::Total()"].changes[0]
    if (change.first, change.last) != lines_of("release-2", "int Thing::Total()") or marked(moved) != marked(second):
        problems.append("building release 0.2.0 again after Thing::Total() moved did not follow it")
    problems += releases.refused(
        "release-2-edited", "0.2.0", RELEASE_EDITS + [TOTAL_RETURNS_2], "the code has changed since"
    )
    return problems


def later_releases(releases):
    problems = []
    unreleased = by_title(releases.run("unreleased", None, RELEASE_EDITS + [TOTAL_RETURNS_2]), "Thing::Total()") or {}
    saved_total = history.load(releases.path)[1].get(unreleased.get("history_key"))
    if not saved_total or unreleased["fingerprint"] == saved_total.fingerprint:
        problems.append("the unreleased edit to Thing::Total() did not change its code")
    elif [c.release for c in unreleased["changed_in"]] != ["0.2.0"]:
        problems.append("an unreleased edit changed the marks of Thing::Total()")
    third_edits = [CHANGE_ADDED, HOOK_TOTAL, SPACE_RESET, TOTAL_RETURNS_2, REMOVE_INDEX]
    third = releases.run("release-3", "0.3.0", third_edits)
    changes = [c.release for c in (by_title(third, "Thing::Total()") or {}).get("changed_in", [])]
    if changes != ["0.2.0", "0.3.0"]:
        problems.append("after release 0.3.0, Thing::Total() is changed in %s, not 0.2.0 and 0.3.0" % changes)
    added = by_title(third, "Added()") or {}
    if (added.get("added_in"), [c.release for c in added.get("changed_in", [])]) != ("0.2.0", ["0.3.0"]):
        problems.append("Added(), changed in 0.3.0, no longer reads added in 0.2.0 and changed in 0.3.0")
    if "Thing::index()" not in history.load(releases.path)[1]:
        problems.append("release 0.3.0 dropped the history of Thing::index(), which its code no longer has")
    problems += releases.refused("refused", "0.2.5", RELEASE_EDITS, "later than")
    for release in ("1.0", "", "0.4.0\n", "0.04.0"):
        problems += releases.refused("refused", release, RELEASE_EDITS, "three numbers")
    return problems


def history_file_problems():
    problems = []
    change = history.Change("0.4.0", "x.cpp", 1, 2, ("PopupRaised", "DealResolved"))
    plural = render.inline(pages.change_mark(change, {"PopupRaised": []}), THING + "Total.html")
    if (
        '(added hand-placed hooks <a href="../../../hooks/PopupRaised.html">PopupRaised</a>, DealResolved)'
        not in plural
    ):
        problems.append("a change that added two hand-placed hooks, one no longer called, reads %r" % plural)
    if history.fingerprint(["-", "-", "x"]) == history.fingerprint(["--", "x"]):
        problems.append("the fingerprint joins - - x and -- x into the same code")
    for name, text, reason in (
        ("damaged-history.txt", "release\t0.1.0\nnot a history line\n", "line 2 of"),
        ("damaged-release.txt", "release\tbanana\n", "line 1 of"),
    ):
        damaged = write_input(name, text)
        problems += stopped(
            "the function history %s" % name, reason, lambda: fixture_build("damaged", history_path=damaged)
        )
    site_folder = os.path.join(OUT, "unregistered-site")
    unregistered_history = os.path.join(OUT, "unregistered-history.txt")
    if os.path.isdir(site_folder):
        shutil.rmtree(site_folder)
    if os.path.exists(unregistered_history):
        os.remove(unregistered_history)
    problems += stopped(
        "a release with hook points missing from the hook list",
        "build the host before a release",
        lambda: fixture_build("unregistered", history_path=unregistered_history, release="0.1.0"),
    )
    if os.path.exists(site_folder) or os.path.exists(unregistered_history):
        problems.append("a release stopped by an out-of-date hook list wrote its site or history")
    return problems


def history_problems():
    releases = Releases()
    problems, second = first_releases(releases)
    problems += rebuilt_release(releases, second) + later_releases(releases)
    return problems + history_file_problems()


def guide_problems(site):
    home = site.html["index.html"]
    wanted = [
        '<a href="reference/docs_engine.cpp/Thing/Score-bool-const.html"><code>Thing::Score(bool)</code></a>',
        '<a href="reference/docs_engine.cpp/Thing/Get.html"><code>Thing::Get</code></a>',
        '<a href="hooks/PopupRaised.html"><code>PopupRaised</code></a>',
        '<h2 id="things-to-do">Things to do</h2>',
        '<h3 id="scores">Scores</h3>',
        "#include &quot;CivPluginApi.h&quot;",
    ]
    problems = ["the front page does not contain %r" % text for text in wanted if text not in home]
    if "##include" in home:
        problems.append("the front page shifted the #include line in the guide's code as if it were a heading")
    for name, text, reason in (
        ("ambiguous", "- [[Thing::Score]]\n", "names Thing::Score,"),
        ("unknown", "- [[Nothing]]\n", "names Nothing,"),
        ("unclosed", "- [[Nothing\n- [[Thing::Get]]\n", "has a [[ link with no closing ]]: [[Nothing"),
    ):
        guide = write_input("guide-%s.md" % name, "# Guide\n\n" + text)
        problems += stopped(
            "a task guide with an %s link" % name, reason, lambda: fixture_build("guide", task_guide=guide)
        )
    return problems


def note_problems(site):
    problems = expect(
        site, "Thing::Total()", 'Counts the things; <a href="Get.html"><code>Thing::Get</code></a> finds one.'
    )
    problems += expect(site, "Count()", 'Counts with <a href="Thing/Get.html"><code>Thing::Get</code></a>.')
    for name, text, reason in (
        ("unknown", "## Nothing\n\nNo such function.\n", "functions noted in %s that are not one function: Nothing"),
        ("ambiguous", "## Thing::Score\n\nTwo of them.\n", "functions noted in %s that are not one function"),
        ("twice", "## Thing::Total\n\nOne.\n\n## Thing::Total()\n\nTwo.\n", "%s has two notes for one function"),
    ):
        notes = write_input("notes-%s.md" % name, "# Function notes\n\n" + text)
        problems += stopped(
            "the function notes in %s" % notes, reason % notes, lambda: fixture_build("notes", function_notes=notes)
        )
    return problems


def summary_problems(site):
    wanted = {
        THING + "index.html": [
            '<a href="Score-bool-const.html"><code>Thing::Score</code></a>',
            '<a href="../Setup.Option/index.html"><code>Setup::Option</code></a>',
            '<a href="../../../hooks/PopupRaised.html"><code>PopupRaised</code></a>',
        ],
        OPTION + "index.html": ['<a href="../Thing/index.html"><code>Thing</code></a>'],
        "index.html": [
            'Main classes: <a href="%sindex.html">Thing</a>, <a href="%sindex.html">Setup::Option</a>' % (THING, OPTION)
        ],
    }
    problems = []
    for path, texts in wanted.items():
        problems += ["%s does not contain %r" % (path, text) for text in texts if text not in site.html[path]]
    for name, text, reason in (
        ("Nobody", "## Nobody\n\nNo such class.\n", "classes summarized in %s that have no page: Nobody"),
        ("Nothing", "## Thing\n\n[[Nothing]]\n", "%s names Nothing,"),
        ("twice", "## Thing\n\nOne.\n\n## Thing\n\nTwo.\n", "%s has two sections named Thing"),
    ):
        summaries = write_input("summaries-%s.md" % name, "# Class summaries\n\n" + text)
        problems += stopped(
            "the class summaries in %s" % summaries,
            reason % summaries,
            lambda: fixture_build("summaries", class_summaries=summaries),
        )
    return problems


FOOTER_START = "© 1991-2012 Take-Two Interactive Software and its subsidiaries"


def markdown_problems(site):
    score = (fixture_line("/// The thing's score."), closing_line("int Thing::Score(bool bFinal) const"))
    left_out = (fixture_line("#define DOCS_UNUSED"), fixture_line("return 0;"))
    hand_hook = fixture_line("CivHandPopupRaised(iBase)")
    wanted = {
        THING + "Score-bool-const.md": [
            "# Thing::Score(bool) const\n\n"
            "[Game code](../../index.md) / [docs_engine.cpp](../index.md) / [Thing](index.md) / Score\n",
            "- **Hook name:** `CivHooks::Thing_Score`\n",
            "## Hooks\n\n```cpp\nstatic bool BeforeThing_Score(const Thing* self, bool bFinal, int& result);\n",
            "Lines %d to %d of `docs_engine.cpp`, numbered." % score,
            "Left out of this build by an `#if`: lines %d to %d." % left_out,
            "\n%d  int Thing::Score(bool bFinal) const\n" % fixture_line("int Thing::Score(bool bFinal) const"),
            "- [Thing::Inline() const](Inline.md)\n",
            FOOTER_START,
        ],
        THING + "Score-int_int.md": [
            "**Warning:** A replacement for this function that does not call `original` stops these hooks",
            "The hand-placed hook PopupRaised fires on line %d." % hand_hook,
            "- [PopupRaised](../../../hooks/PopupRaised.md), line %d\n" % hand_hook,
        ],
        THING + "index.md": [
            "[`Thing::Score`](Score-bool-const.md) scores it",
            "- [Inline() const](Inline.md) (not a hook point)\n",
            "- [operator\\[\\](int) const](operator_index.md)\n",
        ],
        THING + "operator_index.md": ["# Thing::operator[](int) const\n"],
        "hooks/index.md": ["# Hand-placed hooks\n\nThe test engine's one hand-placed hook."],
        "hooks/PopupRaised.md": [
            "## Where it fires\n",
            "](../reference/docs_engine.cpp/Thing/Score-int_int.md), line ",
        ],
        "index.md": [
            "\n## Things to do\n",
            "[`Thing::Get`](reference/docs_engine.cpp/Thing/Get.md)",
            '\n#include "CivPluginApi.h"\n',
        ],
    }
    problems = []
    for path, texts in wanted.items():
        page = site.markdown.get(path, "")
        problems += ["%s does not contain %r" % (path, text) for text in texts if text not in page]
    if not site.markdown.get(THING + "Score-bool-const.md", "").endswith("See [NOTICE](../../../NOTICE.txt).\n"):
        problems.append("the Markdown footer does not end with a link to NOTICE")
    missing = [p for p in site.markdown if not os.path.isfile(os.path.join(SITE, *p.split("/")))]
    problems += ["%s was not written" % p for p in missing[:5]]
    fake = FakeSite({})
    fake.markdown = {
        "a/b.md": "# X::operator[](int)\n\nSee `a[1](b)`, [gone](../nope.md) and [op\\[\\] x](b.md).\n\n"
        "```cpp\nb[1](2);\n```\n\n~~~\n[tilde](fenced.md)\n~~~\n"
    }
    if build_docs.broken_links(fake) != [("a/b.md", "../nope.md")]:
        problems.append("the Markdown link check reads %r" % build_docs.broken_links(fake))
    return problems + markdown_writer_problems()


def markdown_writer_problems():
    folded = Entries([["a"], ["b"], ["c"]], 2, "3 functions in 1 file")
    cases = [
        ("a folded list", render_md.block(folded, "x.html"), "3 functions in 1 file:\n\n- a\n- b\n- c"),
        (
            "left-out lines",
            render_md.left_out_note(10, {0, 1, 2, 5, 9}),
            "Left out of this build by an `#if`: lines 10 to 12, line 15 and line 19.",
        ),
        ("a code span holding a backtick", render_md.code_span("a`b"), "`` a`b ``"),
        (
            "hand-written Markdown",
            render_md.prose("#include x\n  ```\n# indented\n  ```\n~~~\n# fenced\n[a](x.html)\n~~~\n[a](x.html)", 2),
            "##include x\n  ```\n## indented\n  ```\n~~~\n# fenced\n[a](x.html)\n~~~\n[a](x.md)",
        ),
        ("an unclosed fence", render_md.prose("```\n# out\n[a](x.html)", 2), "```\n## out\n[a](x.md)"),
        (
            "a fence closed only by its own fence",
            render_md.prose("```\n# in\n````\n# still in\n``` x\n# still in\n```\n# out", 2),
            "```\n# in\n````\n# still in\n``` x\n# still in\n```\n## out",
        ),
        ("a link in a code span", render_md.prose("`[a](x.html)` and [b](y.html)", 1), "`[a](x.html)` and [b](y.md)"),
    ]
    problems = ["the Markdown of %s reads %r" % (what, got) for what, got, want in cases if got != want]
    if not render.block(folded, "x.html").startswith("<details><summary>3 functions in 1 file</summary>"):
        problems.append("the HTML of a folded list does not fold")
    return problems


def html_problems(site):
    wanted = {
        THING + "Score-bool-const.html": [
            "<title>Thing::Score(bool) const - Bazaar developer reference</title>",
            '<span aria-current="page">Score</span>',
            '<section id="hooks"><h2>Hooks</h2>',
            '<section id="code"><h2>Code</h2>',
            "<footer>The game&#x27;s code on these pages is " + FOOTER_START,
            'See <a href="../../../NOTICE.txt">NOTICE</a>.</footer>',
        ],
        THING + "Score-int_int.html": ['<p class="warn">A replacement for this function that does not call'],
        THING + "index.html": [
            '<a href="Inline.html" title="Thing::Inline() const">Inline() const</a> <span class="badge">'
        ],
        "index.html": ["<title>Bazaar developer reference</title>"],
    }
    problems = []
    for path, texts in wanted.items():
        problems += ["%s does not contain %r" % (path, text) for text in texts if text not in site.html[path]]
    return problems


class FakeSite:
    def __init__(self, html):
        self.html = html
        self.markdown = {}

    def search_index(self):
        return "window.BAZAAR_INDEX = [];\n"

    def search_rows(self):
        return []


def write_problems():
    problems = []
    stray = os.path.join(OUT, "stray")
    if os.path.isdir(stray):
        shutil.rmtree(stray)
    os.makedirs(stray)
    with open(os.path.join(stray, "keep.txt"), "w") as f:
        f.write("keep")
    with open(os.path.join(stray, render.INDEX_FILE), "w") as f:
        f.write("var lunr = {};\n")
    try:
        build_docs.write(FakeSite({}), stray)
        problems.append("a folder that is not a docs build, holding another site's search index, was emptied")
    except SystemExit:
        if not os.path.isfile(os.path.join(stray, "keep.txt")):
            problems.append("the stray folder was emptied")
    stopped_folder = os.path.join(OUT, "stopped")
    if os.path.isdir(stopped_folder):
        shutil.rmtree(stopped_folder)
    try:
        build_docs.write(FakeSite({"index.html": "x", "bad\0.html": "x"}), stopped_folder)
    except ValueError:
        pass
    try:
        build_docs.write(FakeSite({"index.html": "x"}), stopped_folder)
    except SystemExit:
        problems.append("a write stopped part way blocked the next one")
    for name in ("LICENSE.txt", "NOTICE.txt"):
        if not os.path.isfile(os.path.join(stopped_folder, name)):
            problems.append("the site has no %s" % name)
    return problems


if __name__ == "__main__":
    site = build_fixture(fixture_project("fixture"), SITE)
    problems = naming_problems(site) + code_problems(site) + fact_problems(site) + caller_problems(site)
    problems += search_problems(site) + guide_problems(site) + summary_problems(site) + note_problems(site)
    problems += markdown_problems(site) + html_problems(site)
    problems += stop_problems() + write_problems() + history_problems()
    if problems:
        print("FAIL: " + "; ".join(problems))
        sys.exit(1)
    print("PASS: docs checks")
    sys.exit(0)
