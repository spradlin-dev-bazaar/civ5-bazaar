"""Run a checks file: start Civilization V with the mods it names and the mods they depend on, play its steps, check
what happened, and put the player's game back as it was.

    python -m bazaar_check checks.toml
"""

import collections
import os
import re
import shutil
import tempfile
import tomllib

from . import CheckError, files, game

SETTINGS = {"mods": list, "plugin_order": list, "steps": list, "crash_expected": bool, "lua_errors_expected": bool}
TYPE_NAMES = {str: "text", int: "a whole number", bool: "true or false", list: "a list"}
Step = collections.namedtuple("Step", "value needs may")
STEPS = {
    "start_game": Step(str, {}, {}),
    "end_turns": Step(int, {}, {}),
    "save": Step(str, {}, {}),
    "load": Step(str, {}, {}),
    "main_menu": Step(bool, {}, {}),
    "lua": Step(str, {}, {"state": str, "what": str}),
    "run": Step(str, {}, {"state": str}),
    "log": Step(str, {}, {"has": str, "lacks": str, "what": str}),
    "plugin": Step(str, {}, {"status": str, "problems": str, "what": str}),
    "description_of": Step(str, {"version": int, "is": str}, {"what": str}),
}
PATTERNS = ("has", "lacks", "problems")
CRASH = r"^Plugin .+: (Faulted \(code |It stopped working)"
LUA_ERROR = r"(Runtime|Syntax) Error:"

Checks = collections.namedtuple(
    "Checks", "mods plugin_order steps crash_expected lua_errors_expected", defaults=((), (), False, False)
)
Result = collections.namedtuple("Result", "what passed found")


def kind_of(step):
    return next(key for key in step if key in STEPS)


def check_step(number, step):
    kinds = [key for key in step if key in STEPS] if isinstance(step, dict) else []
    if len(kinds) != 1:
        raise CheckError("step %d must do one of %s" % (number, ", ".join(sorted(STEPS))))
    kind = kinds[0]
    spec = STEPS[kind]
    missing = set(spec.needs) - set(step)
    if missing:
        raise CheckError("step %d (%s) needs %s" % (number, kind, ", ".join(sorted(missing))))
    types = dict(spec.needs, **spec.may, **{kind: spec.value})
    for key, value in step.items():
        if key not in types:
            raise CheckError("step %d (%s) does not take %s" % (number, kind, key))
        if type(value) is not types[key]:
            raise CheckError("step %d (%s): %s needs %s" % (number, kind, key, TYPE_NAMES[types[key]]))
    if kind == "log" and len({"has", "lacks"} & set(step)) != 1:
        raise CheckError("step %d (log) needs has or lacks, not both" % number)
    if kind == "start_game" and step[kind] != "duel":
        raise CheckError('step %d (start_game) can only start a "duel" game' % number)
    if kind == "end_turns" and step[kind] < 1:
        raise CheckError("step %d (end_turns) needs 1 or more" % number)
    if kind == "main_menu" and not step[kind]:
        raise CheckError("step %d (main_menu) needs true" % number)
    for key in set(PATTERNS) & set(step):
        try:
            re.compile(step[key])
        except re.error as e:
            raise CheckError("step %d (%s) has a %s pattern Python cannot read: %s" % (number, kind, key, e))


def validate(checks):
    """Refuse checks the game would only trip over part way through."""
    if not checks.mods:
        raise CheckError("the checks name no mods")
    if not all(isinstance(mod, str) for mod in checks.mods):
        raise CheckError("mods needs a list of folders and packages")
    for number, entry in enumerate(checks.plugin_order, 1):
        problem = files.order_entry_problem(entry)
        if problem:
            raise CheckError("plugin_order entry %d: %s" % (number, problem))
    for number, step in enumerate(checks.steps, 1):
        check_step(number, step)


def read_checks(path):
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise CheckError("%s could not be read: %s" % (path, e))
    for name, value in data.items():
        if name not in SETTINGS:
            raise CheckError("%s has a setting the checks do not know: %s" % (path, name))
        if type(value) is not SETTINGS[name]:
            raise CheckError("%s: %s needs %s" % (path, name, TYPE_NAMES[SETTINGS[name]]))
    checks = Checks(
        data.get("mods", []),
        data.get("plugin_order", []),
        data.get("steps", []),
        data.get("crash_expected", False),
        data.get("lua_errors_expected", False),
    )
    try:
        validate(checks)
    except CheckError as e:
        raise CheckError("%s: %s" % (path, e))
    folder = os.path.dirname(os.path.abspath(path))
    return checks._replace(mods=[os.path.normpath(os.path.join(folder, mod)) for mod in checks.mods])


def versions_text(low, high):
    if (low, high) == (0, 999):
        return "any version"
    return "version %d" % low if low == high else "version %d to %d" % (low, high)


def checked_versions(expected):
    wanted = {}
    for folder in expected:
        info = files.read_modinfo(folder)
        if info.id in wanted:
            raise CheckError(
                "mods lists two versions of %s (%d and %d): keep one" % (info.name, wanted[info.id], info.version)
            )
        wanted[info.id] = info.version
    return wanted


def dependencies(expected, installed, mods_folder):
    """The (id, version) pairs to switch on: the checked mods, then, for each mod they need and each mod those need,
    the newest installed version that every need allows. A test build is used only when the checks file lists it."""
    wanted = checked_versions(expected)
    checked = set(wanted)
    allowed = {}
    needing = [files.read_modinfo(folder) for folder in expected]
    while needing:
        info = needing.pop()
        for need in info.dependencies:
            needs = "%s needs %s, %s" % (info.name, need.title, versions_text(need.low, need.high))
            if need.id in checked:
                if not need.low <= wanted[need.id] <= need.high:
                    raise CheckError("%s, but the checks file lists version %d" % (needs, wanted[need.id]))
                continue
            low, high = allowed.get(need.id, (need.low, need.high))
            low, high = max(low, need.low), min(high, need.high)
            if need.id in allowed and low <= wanted[need.id] <= high:
                allowed[need.id] = (low, high)
                continue
            versions = [v for m, v, _ in installed if m == need.id and low <= v <= high]
            released = [v for v in versions if v != files.TEST_VERSION]
            if not released and need.id in allowed:
                other = versions_text(*allowed[need.id])
                raise CheckError("%s, and another mod needs %s; no installed version suits both" % (needs, other))
            if not released:
                test_build = " (only a test build is: list it in mods to use it)" if versions else ""
                raise CheckError("%s, which is not installed%s" % (needs, test_build))
            allowed[need.id] = (low, high)
            wanted[need.id] = max(released)
            found = files.mod_folders(mods_folder, (need.id, wanted[need.id]))
            if found:
                needing.append(files.read_modinfo(found[0]))
    return list(wanted.items())


def log_check(g, name, has=None, lacks=None, what=None):
    lines = g.log(name)
    if has is not None:
        found = [line for line in lines if re.search(has, line)]
        return Result(what or "%s has %s" % (name, has), bool(found), "%s has no such line" % name)
    found = [line for line in lines if re.search(lacks, line)]
    return Result(what or "%s lacks %s" % (name, lacks), not found, "it has: " + found[0] if found else "")


def lua_check(g, step):
    state = step.get("state", game.IN_GAME)
    value = g.text(state, step["lua"])
    what = step.get("what") or "%s: %s" % (state, step["lua"])
    return Result(what, value not in ("false", "nil"), "it gave %s" % value)


def plugin_check(g, step):
    rows = {file.lower(): (status, problems) for file, status, problems in g.plugins()}
    what = step.get("what") or "the Plugins screen shows %s as %s" % (step["plugin"], step.get("status", "listed"))
    row = rows.get(step["plugin"].lower())
    if row is None:
        return Result(what, False, "it does not list %s" % step["plugin"])
    status, problems = row
    passed = step.get("status", status) == status and re.search(step.get("problems", ""), problems) is not None
    return Result(what, passed, "it shows %s%s" % (status, ": " + problems if problems else ""))


def description_check(g, step):
    description = g.mod_description(step["description_of"], step["version"])
    what = step.get("what") or "the Mods menu describes %s v%d as expected" % (step["description_of"], step["version"])
    found = "it reads: ...%s" % description[-70:] if description else "the game gave no description"
    return Result(what, (description or "").strip() == step["is"].strip(), found)


def do_step(g, step, results):
    kind = kind_of(step)
    if kind == "start_game":
        g.start_game()
    elif kind == "end_turns":
        for _ in range(step[kind]):
            g.end_turn()
    elif kind == "save":
        g.save(step[kind])
    elif kind == "load":
        g.load(step[kind])
    elif kind == "main_menu":
        g.to_main_menu()
    elif kind == "run":
        g.lua(step.get("state", game.IN_GAME), step[kind])
    elif kind == "lua":
        results.append(lua_check(g, step))
    elif kind == "log":
        results.append(log_check(g, step["log"], step.get("has"), step.get("lacks"), step.get("what")))
    elif kind == "plugin":
        results.append(plugin_check(g, step))
    elif kind == "description_of":
        results.append(description_check(g, step))
    else:
        raise AssertionError("STEPS has %s, which do_step does not do" % kind)


def play(checks, g, expected, results):
    """The part of a run inside the game; it adds a Result to results as each check is made."""
    keys = [files.mod_key(folder) for folder in expected]

    def listed():
        return set(keys) <= {(m, v) for m, v, _ in g.mods(enabled_only=False)}

    g.wait("the game listing the mods", listed, 120)
    problems = g.files.installed_problems(expected)
    if problems:
        raise CheckError("; ".join(problems))
    g.files.use_plugin_order(checks.plugin_order)
    installed = g.mods(enabled_only=False)
    wanted = dependencies(expected, installed, g.files.path("MODS"))
    names = {(m, v): name for m, v, name in installed}
    g.say("choosing " + ", ".join("%s (v %d)" % (names[key], key[1]) for key in wanted))
    g.set_mods(wanted)
    g.activate()
    for step in checks.steps:
        do_step(g, step, results)
    if not checks.crash_expected:
        results.append(log_check(g, "Bazaar.log", lacks=CRASH, what="no plugin stopped working"))
    if not checks.lua_errors_expected:
        results.append(log_check(g, "Lua.log", lacks=LUA_ERROR, what="Lua.log has no Lua errors"))


def run_checks(checks, g, results):
    """The game reads MODS as it starts, so the mods go in before it does, and only once preflight has found it
    closed."""
    g.preflight()
    staging = tempfile.mkdtemp(prefix="Bazaar check mods ")
    try:
        expected = g.files.install(checks.mods, staging)
        with game.session(g):
            play(checks, g, expected, results)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def print_results(results):
    for result in results:
        print("  %s  %s" % ("PASS" if result.passed else "FAIL", result.what), flush=True)
        if not result.passed and result.found:
            print("        " + result.found, flush=True)


def log_tail(g):
    """The end of Bazaar.log to follow a failure, or nothing if the game never started."""
    if g.started is None:
        return ""
    lines = g.log()[-15:]
    return "\nThe end of Bazaar.log:\n" + "\n".join(lines) if lines else "\nBazaar.log was not written in this run."


def run(checks, g):
    """Run the checks and print what each found; returns why they did not all pass, or None."""
    try:
        validate(checks)
    except CheckError as e:
        return "could not start: %s" % e
    results = []
    try:
        run_checks(checks, g, results)
    except game.ERRORS + (OSError,) as e:
        print_results(results)
        return "could not finish: %s%s" % (e, log_tail(g))
    print_results(results)
    if all(result.passed for result in results):
        return None
    return "failed." + log_tail(g)


def main(argv):
    if len(argv) != 1:
        print(__doc__.strip())
        return 2
    try:
        checks = read_checks(argv[0])
        g = game.Game()
    except game.ERRORS as e:
        print(e)
        return 1
    failed = run(checks, g)
    print("The checks " + (failed or "passed."))
    return 1 if failed else 0
