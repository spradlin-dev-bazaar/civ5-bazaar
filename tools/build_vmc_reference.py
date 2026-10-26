"""Write the new-lua-mod skill's references/vmc-events.md and references/vmc-options.txt from Bazaar's sources.

VMC's notes in CustomModOptions.xml give each option and the GameEvents it switches on; the engine source gives how
each event is called, the events VMC's notes leave out, and the events the base game fires with no option. Run after
VMC or the engine changes; --check only reports whether the files in the skill are current:

    python tools/build_vmc_reference.py [--check]
"""

import argparse
import bisect
import difflib
import re
import sys
from collections import namedtuple
from pathlib import Path
from xml.etree import ElementTree

REPO = Path(__file__).resolve().parents[1]
VMC = REPO / "mod" / "vmc"
ENGINE = REPO / "CvGameCoreSource" / "CvGameCoreDLL_Expansion2"
REFERENCES = REPO / "claude-plugin" / "skills" / "new-lua-mod" / "references"

KINDS = {
    "HOOK": "hook",
    "Hook": "hook",
    "TESTALL": "test-all",
    "TestAll": "test-all",
    "TESTANY": "test-any",
    "TestAny": "test-any",
    "VALUE": "value",
    "Accumulator": "value",
}
TYPES = {"i": "number", "b": "true/false", "s": "text"}
VMC_CALL = re.compile(r"GAMEEVENTINVOKE_(HOOK|TESTALL|TESTANY|VALUE)\s*\(\s*(?:\w+\s*,\s*)?GAMEEVENT_(\w+)")
BASE_CALL = re.compile(r'LuaSupport::Call(Hook|TestAll|TestAny|Accumulator)\s*\(\s*pkScriptSystem\s*,\s*"(\w+)"')
DEFINE = re.compile(r'#define\s+GAMEEVENT_(\w+)\s+"(\w+)"\s*,\s*"(\w*)"')
MOD_MACRO = re.compile(r"\s*#\s*define\s+(MOD_\w+)")
DEFINED = re.compile(r"defined\s*\(?\s*(\w+)\s*\)?")
NOT_CODE = re.compile(
    r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|^[ \t]*#[ \t]*(?:if|el|endif)[^\n]*", re.S | re.M
)
MACRO_HEAD = re.compile(r"^([ \t]*#[ \t]*define[ \t]+\w+(?:\([^)\n]*\))?)([^\n]*)\n", re.M)
OPTION_TEST = re.compile(r"(?<![!\w])MOD_(\w+)")
IF_HEAD = re.compile(r"\bif\s*\(")
PUSH = re.compile(r"->Push\((.*?)\);")
SIGNATURE = re.compile(r"GameEvents\.(\w+)\.Add\(function\(([^)]*)\)\s*(.*?)\s*end\)\s*(\(v\d+\))?")
DEFAULT_VALUE = re.compile(r"\s*=[^,]*")
BLANK_LINE = re.compile(r"\n[ \t]*\n")
# The rest of a base-game call after the event's name: its arguments, then the variable it fills with the answer.
FILLED_ANSWER = re.compile(r"\s*,[^,;]*,\s*(\w+)\s*\)")
# The engine's own test calls, made from Lua functions in CvLuaGame.cpp, not events the game fires.
NOT_EVENTS = {"TestEvent", "TestAccumulator"}
EXTRA_NOTES = {
    "PlayerCanAdoptTenet": "VMC also fires it to ask whether the player can adopt an ideology, with the ideology's "
    "policy branch ID as `iTenet` (CvPolicyClasses.cpp). A handler cannot tell which it is asked, so blocking a tenet "
    "by its ID can also block the ideology whose branch has that ID.",
    "PlayerCanAdoptIdeology": "To block an ideology, subscribe to `PlayerCanAdoptTenet`: VMC asks that event about "
    "ideologies too, with the ideology's policy branch ID as `iTenet` (CvPolicyClasses.cpp).",
}
FALSE_BY_DEFAULT = (
    "**Answer `false` by default**: the game acts only when every handler answers `true`, so answer `false` in every "
    "case the mod does not mean to change."
)

Option = namedtuple("Option", "name kind default notes")
# options: the options the code checks around the call; blocks: those whose `#if defined(MOD_...)` code it sits in,
# which says whose code it is but not that the option is checked.
Site = namedtuple("Site", "file options blocks pushed")
Engine = namedtuple("Engine", "types kinds vmc_sites base_sites acts_on_true unused")


def read_version():
    return str(int(ElementTree.parse(next(VMC.glob("*.modinfo"))).getroot().attrib["version"]))


def option_nodes(element):
    """The comments, rows and text between them, in file order, without going into a row."""
    yield "text", element.text or ""
    for child in element:
        if child.tag is ElementTree.Comment:
            yield "comment", child.text or ""
        elif child.tag == "Row":
            yield "row", child.attrib
        else:
            yield from option_nodes(child)
        yield "text", child.tail or ""


def read_options():
    """Each option row in file order, with the comments just above it and any comment after it on the same line; a
    blank line drops the comments above it, and comments outside the root element are not read.

    Class 0 rows hold numbers that other options use; every other row is an on/off switch."""
    parser = ElementTree.XMLParser(target=ElementTree.TreeBuilder(insert_comments=True))
    root = ElementTree.parse(VMC / "CustomModOptions.xml", parser).getroot()
    options, pending, on_row_line = [], [], False
    for kind, value in option_nodes(root):
        if kind == "text":
            if BLANK_LINE.search(value):
                pending = []
            if "\n" in value:
                on_row_line = False
        elif kind == "row":
            option_kind = "number" if value.get("Class") == "0" else "switch"
            options.append(Option(value["Name"], option_kind, value.get("Value", "0"), pending))
            pending, on_row_line = [], True
        else:
            note = " ".join(part.strip() for part in value.splitlines()).strip().rstrip("-").strip()
            if on_row_line:
                options[-1].notes.append(note)
            elif not note.startswith("Row "):
                pending.append(note)
    return options


def judged_names(directive):
    """The MOD_ names an `#if` tests, when its condition is only `defined(MOD_...)` joined by &&; otherwise None."""
    condition = re.sub(r"^ifdef\b", "if defined", directive.split("//")[0].strip())
    if not condition.startswith("if "):
        return None
    parts = [DEFINED.fullmatch(part.strip()) for part in condition[3:].split("&&")]
    if all(parts) and all(part.group(1).startswith("MOD_") for part in parts):
        return [part.group(1) for part in parts]
    return None


def compiled(lines, macros):
    """Each line paired with the MOD_ names of the `#if defined(...)` blocks it sits in, blanked where such a block
    leaves it out of the build. Lines under any other kind of condition, and every branch after an `#if`, count as
    compiled unless that `#if` was taken."""
    frames, out = [], []
    for line in lines:
        directive = line.strip()
        if directive.startswith("#"):
            word = directive[1:].strip()
            if word.startswith("if"):
                names = judged_names(word)
                frames.append([names, names is not None and all(n in macros for n in names), False])
            elif word.startswith("el") and frames:
                frames[-1][2] = True
            elif word.startswith("endif") and frames:
                frames.pop()
        live = all(names is None or taken != in_else for names, taken, in_else in frames)
        blocks = {n for names, taken, in_else in frames if names and taken and not in_else for n in names}
        out.append((line if live else "", blocks))
    return out


def code_only(text):
    """The text with comments, string contents and #if lines turned to spaces, keeping every offset. A macro's body
    stays, as a statement of its own, since some events are fired from macros."""

    def blank(match):
        part = match.group(0)
        if part[0] in "\"'":
            return part[0] + " " * (len(part) - 2) + part[-1]
        return re.sub(r"[^\n]", " ", part)

    def macro_body(match):
        return ";" + " " * (len(match.group(1)) - 1) + match.group(2) + ";"

    return MACRO_HEAD.sub(macro_body, NOT_CODE.sub(blank, text))


def statement_start(code, end):
    return max(code.rfind(mark, 0, end) for mark in ";{}") + 1


def tested_options(code, braces, position):
    """The MOD_ names the game checks at run time before reaching position: those in its own statement and in the
    `if` of each block around it. A name after `!`, and a condition with `||`, are left out. braces holds the offset of
    every brace in code, in order."""
    start = statement_start(code, position)
    heads = [code[start:position]]
    depth = 0
    for i in reversed(braces[: bisect.bisect_left(braces, start)]):
        if code[i] == "}":
            depth += 1
        elif depth:
            depth -= 1
        else:
            heads.append(code[statement_start(code, i) : i])
    names = set()
    for index, head in enumerate(heads):
        if (index == 0 or IF_HEAD.search(head)) and "||" not in head:
            names.update(OPTION_TEST.findall(head))
    return names


def pushed_before(lines, number):
    """The arguments pushed between a base-game call and the CvLuaArgsHandle above it, in order."""
    pushed = []
    for line in reversed(lines[max(number - 60, 0) : number]):
        if "CvLuaArgsHandle" in line:
            break
        pushed[:0] = [p.strip() for p in PUSH.findall(line)]
    return pushed


def answer_reading(code, end, answer):
    """How the code after a test-all call, from end, reads the answer: "refuses" when any false refuses (the answer
    compared with false, or used as it is), "acts" when the game acts on true from every handler, "unused" when the
    statement the call opens does not look at it, or None for a shape this script does not know. answer is the variable
    a base-game call fills, or None for a VMC call, whose answer is compared where it is made."""
    if answer is None:
        refuses = re.compile(r"[^;{]*?==\s*GAMEEVENTRETURN_FALSE")
        acts = re.compile(r"[^;{]*?==\s*GAMEEVENTRETURN_TRUE")
    else:
        stop = code.find(";", end)
        following = code[end : stop if stop >= 0 else len(code)]
        if not following.strip(" \t\r\n){"):
            return None
        if not re.search(r"\b%s\b" % re.escape(answer), following):
            return "unused"
        a = re.escape(answer)
        refuses = re.compile(r"[^;]*?(?:\bif\s*\(\s*(?:%s\s*==\s*false|!\s*%s)\s*\)|\b\w+\s*=\s*%s\s*;)" % (a, a, a))
        acts = re.compile(r"[^;]*?\bif\s*\(\s*%s\s*(?:==\s*true\s*)?\)" % a)
    refused, acted = refuses.match(code, end), acts.match(code, end)
    if refused and not (acted and acted.end() < refused.end()):
        return "refuses"
    return "acts" if acted else None


def read_engine(option_names):
    """The argument types VMC declares for each event, how each event is called, and where."""
    sources = [path for path in sorted(ENGINE.rglob("*")) if path.suffix.lower() in (".cpp", ".h")]
    files = [(path, path.read_text(encoding="latin-1").splitlines()) for path in sources]
    by_macro, types, macros = {}, {}, set()
    for _, lines in files:
        for line in lines:
            for macro, name, signature in DEFINE.findall(line):
                by_macro[macro] = name
                types[name] = signature
            match = MOD_MACRO.match(line)
            if match:
                macros.add(match.group(1))
    kinds, vmc_sites, base_sites, readings, unused, skipped = {}, {}, {}, {}, {}, set()
    for path, raw in files:
        pairs = compiled(raw, macros)
        lines = [line for line, _ in pairs]
        text = "\n".join(lines)
        code = code_only(text)
        braces = [match.start() for match in re.finditer(r"[{}]", code)]
        for call, sites in ((VMC_CALL, vmc_sites), (BASE_CALL, base_sites)):
            for match in call.finditer(text):
                if code[match.start()] == " ":
                    continue
                kind, name = match.groups()
                name = by_macro.get(name, name) if call is VMC_CALL else name
                if name in NOT_EVENTS:
                    skipped.add(name)
                    continue
                kinds.setdefault(name, set()).add(KINDS[kind])
                number = text.count("\n", 0, match.start())
                if KINDS[kind] == "test-all":
                    reading = test_all_reading(code, match.end(), call is VMC_CALL)
                    if reading is None:
                        raise SystemExit(
                            "build_vmc_reference: %s line %d reads a test-all event's answer in a way this script "
                            "does not know; add its shape to answer_reading" % (path.name, number + 1)
                        )
                    if reading == "unused":
                        unused.setdefault(name, []).append(path.name)
                    else:
                        readings.setdefault(name, set()).add(reading)
                options = sorted(o for o in tested_options(code, braces, match.start()) if o in option_names)
                blocks = sorted(b[4:] for b in pairs[number][1] if b[4:] in option_names)
                pushed = pushed_before(lines, number) if call is BASE_CALL else []
                sites.setdefault(name, []).append(Site(path.name, options, blocks, pushed))
    problems = read_problems(readings, skipped, set(kinds) | set(types))
    if problems:
        raise SystemExit("build_vmc_reference: " + "; ".join(problems))
    acts_on_true = {name for name, seen in readings.items() if seen == {"acts"}}
    return Engine(types, kinds, vmc_sites, base_sites, acts_on_true, unused)


def test_all_reading(code, end, vmc_call):
    """answer_reading for the test-all call that ends at end: a VMC call compares its answer where it is made, and a
    base-game call fills a variable first."""
    if vmc_call:
        return answer_reading(code, end, None)
    filled = FILLED_ANSWER.match(code, end)
    return filled and answer_reading(code, filled.end(), filled.group(1))


def read_problems(readings, skipped, events):
    """Why what read_engine read cannot be trusted: an event read both ways, or a hand list naming something the engine
    no longer has."""
    problems = []
    mixed = sorted(name for name, seen in readings.items() if len(seen) > 1)
    if mixed:
        problems.append("test-all events read one way at one call and the other way at another: " + ", ".join(mixed))
    gone = sorted(NOT_EVENTS - skipped)
    if gone:
        problems.append("NOT_EVENTS names test calls the engine no longer makes: " + ", ".join(gone))
    unknown = sorted(name for name in EXTRA_NOTES if name not in events)
    if unknown:
        problems.append("EXTRA_NOTES names events the engine no longer has: " + ", ".join(unknown))
    return problems


def closest(event, engine):
    names = sorted(set(engine.kinds) | set(engine.types))
    close = difflib.get_close_matches(event, names, n=1, cutoff=0.8)
    return close[0] if close else None


def describe(event, engine):
    """The event's kind, or a warning when VMC's notes name an event the code does not fire."""
    if event in engine.kinds:
        return " / ".join(sorted(engine.kinds[event]))
    if event in engine.types:
        return "**never fired**: VMC defines this event, but nothing in Bazaar's code fires it"
    close = closest(event, engine)
    if close in engine.kinds:
        return "**misnamed in VMC's notes**: subscribe to `%s`, which is %s" % (close, describe(close, engine))
    if close:
        return "**misnamed in VMC's notes, and never fired**: the code's name is `%s`, and nothing fires it" % close
    return "**not in Bazaar's code**: nothing defines or fires this event"


def files_of(sites):
    return ", ".join(sorted({site.file for site in sites}))


def quoted(options):
    return " and ".join("`%s`" % o for o in sorted(options))


def all_on(options):
    return quoted(options) + (" is on" if len(options) == 1 else " are on")


def also_needs(event, option, engine):
    """The other options the code checks before firing an event VMC's notes list under option. Each site needs all of
    its own options; a file fires the event when any of its sites does."""
    sites = engine.vmc_sites.get(event, [])
    if not sites:
        return []
    extras = [frozenset(site.options) - {option} for site in sites]
    everywhere = frozenset.intersection(*extras)
    parts = ["**Also needs** %s on." % quoted(everywhere)] if everywhere else []
    by_file = {}
    for site, extra in zip(sites, extras):
        by_file.setdefault(site.file, set()).add(extra - everywhere)
    for file, conditions in sorted(by_file.items()):
        if frozenset() not in conditions:
            parts.append(
                "Where %s fires it, only when %s." % (file, " or when ".join(sorted(all_on(c) for c in conditions)))
            )
    return parts


def site_condition(site):
    if site.options:
        return "when %s" % all_on(site.options)
    if site.blocks:
        return "probably when %s, since the call sits inside its code (read the file to check)" % all_on(site.blocks)
    return "under no option this script can find (read the file to see what switches it on)"


def option_event(signature, option, engine):
    """One line for an event VMC's notes list under an option, and the event's name (None if the line is not a
    GameEvents signature)."""
    match = SIGNATURE.search(signature)
    if not match:
        return "- `%s`" % signature, None
    event, arguments, body, version = match.groups()
    arguments = DEFAULT_VALUE.sub("", arguments.strip())
    in_code = event if event in engine.kinds or event in engine.types else closest(event, engine) or event
    parts = [describe(event, engine) + "."]
    # VMC's notes show a handler that changes nothing; only a value event's says what kind of value it returns.
    if body.startswith("return") and engine.kinds.get(in_code) == {"value"}:
        parts.append("VMC's example handler returns `%s`." % body[len("return") :].rstrip(";").strip())
    parts += notes_on(in_code, engine)
    parts += also_needs(in_code, option, engine)
    listed = len([a for a in arguments.split(",") if a.strip()])
    declared = engine.types.get(in_code)
    if declared is not None and len(declared) != listed:
        parts.append(
            "**Argument count differs**: VMC's notes list %d, the code declares %d; read the call in %s before "
            "relying on more than the first %d."
            % (listed, len(declared), files_of(engine.vmc_sites.get(in_code, [])), min(listed, len(declared)))
        )
    if in_code in engine.base_sites:
        parts.append(
            "**Always on**: with this option off the base game still fires it, with the arguments listed under "
            "the base-game events below."
        )
    if version:
        parts.append("Since VMC %s." % version.strip("()"))
    return "- `GameEvents.%s.Add(function(%s) ... end)`: %s" % (event, arguments, " ".join(parts)), event


def notes_on(event, engine):
    notes = [FALSE_BY_DEFAULT] if event in engine.acts_on_true else []
    if event in engine.unused:
        calls = engine.unused[event]
        notes.append(
            "The game ignores the answer at %s of the places it asks it (%s)."
            % ("one" if len(calls) == 1 else len(calls), ", ".join(sorted(set(calls))))
        )
    return notes + ([EXTRA_NOTES[event]] if event in EXTRA_NOTES else [])


def with_notes(line, event, engine):
    return " ".join([line] + notes_on(event, engine))


def option_sections(options, engine):
    """The VMC events section, and the events VMC's notes list."""
    out, listed = [], set()
    for option in options:
        signatures = [n for n in option.notes if "GameEvents." in n]
        if not signatures:
            continue
        out += ["### %s%s" % (option.name, " (on by default)" if option.default != "0" else ""), ""]
        for note in option.notes:
            if "GameEvents." not in note:
                out += [note, ""]
        for signature in signatures:
            line, event = option_event(signature, option.name, engine)
            out.append(line)
            if event:
                listed.add(event)
        out.append("")
    return out, listed


def unlisted_events(engine, listed):
    """Events VMC fires that its notes do not mention, by name or by a misspelling of it."""
    covered = listed | {closest(event, engine) for event in listed} | set(engine.base_sites)
    out = []
    for event in sorted(set(engine.vmc_sites) - covered):
        sites = engine.vmc_sites[event]
        switch = " or ".join(sorted({site_condition(site) for site in sites}))
        arguments = ", ".join(TYPES.get(t, t) for t in engine.types.get(event, "")) or "none"
        line = "- `%s` (%s), fired in %s %s. Arguments: %s." % (
            event,
            describe(event, engine),
            files_of(sites),
            switch,
            arguments,
        )
        out.append(with_notes(line, event, engine))
    return out


def base_events(engine, defaults):
    """Events fired the base game's way. The few VMC fires that way inside an option's code are marked with it."""
    out = []
    for event in sorted(engine.base_sites):
        sites = engine.base_sites[event]
        arguments = next((site.pushed for site in sites if site.pushed), [])
        checked = set.intersection(*(set(site.options) for site in sites))
        inside = set.intersection(*(set(site.blocks) for site in sites))
        note = ""
        if checked or inside:
            note = ". %s when %s%s" % (
                "Only" if checked else "Probably only",
                all_on(checked or inside),
                " (on by default)" if all(defaults[o] != "0" for o in checked or inside) else "",
            )
        line = "- `%s` (%s), fired in %s. Arguments: %s%s." % (
            event,
            describe(event, engine),
            files_of(sites),
            ", ".join("`%s`" % a for a in arguments) if arguments else "none",
            note,
        )
        out.append(with_notes(line, event, engine))
    return out


def other_options(options):
    out = []
    for option in options:
        if any("GameEvents." in n for n in option.notes):
            continue
        if option.kind == "number":
            label = " (**number**, default %s)" % option.default
        else:
            label = " (**on by default**)" if option.default != "0" else ""
        description = " ".join(option.notes).strip()
        out.append("- `%s`%s%s" % (option.name, label, (": " + description) if description else ""))
    return out


def render(version, options, engine):
    events, listed = option_sections(options, engine)
    unlisted = unlisted_events(engine, listed)
    out = [
        "# Lua events for Bazaar mods",
        "",
        "Generated by `tools/build_vmc_reference.py` in Bazaar's repository, from VMC v%s's `CustomModOptions.xml` "
        "and Bazaar's engine source. Do not edit by hand; run the script again instead." % version,
        "",
        "Each event is one of these kinds:",
        "",
        "- **hook**: the game tells every handler; what they return is ignored.",
        "- **test-all**: the game asks a yes-or-no question and treats the answer as yes only if every handler "
        "returns `true`.",
        "- **test-any**: the game treats the answer as yes if any handler returns `true`.",
        "- **value**: handlers return a number the game uses.",
        "",
        "Subscribe with `GameEvents.<Name>.Add(function(<arguments>) ... end)`.",
        "",
        "## VMC events: switched off until a mod switches on their option",
        "",
        "Switch an option on in the mod's SQL: `UPDATE CustomModOptions SET Value = 1 WHERE Name = '<OPTION>';`",
        "",
    ]
    out += events
    out += [
        "## VMC events that VMC's notes leave out",
        "",
        "The code fires these, but VMC's notes do not list them, so only the types of their arguments are known; "
        "read the named file for their meaning.",
        "",
    ]
    out += unlisted
    out += [
        "",
        "## Base-game events: always on, no option needed",
        "",
        "The arguments are the expressions the engine pushes, in order; read the named file for their meaning.",
        "",
    ]
    out += base_events(engine, {o.name: o.default for o in options})
    out += [
        "",
        "## VMC's other options",
        "",
        "These change rules or add Lua functions rather than events. Switch them on the same way. An option marked "
        "**number** holds a number instead: set it with `UPDATE CustomModOptions SET Value = <number> WHERE Name = "
        "'<OPTION>';`.",
        "",
    ]
    out += other_options(options)
    out.append("")
    counts = (len(options), len(listed), len(unlisted), len(engine.base_sites))
    return "\n".join(out), counts


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the files in the skill are out of date")
    args = parser.parse_args()

    options = read_options()
    engine = read_engine({o.name for o in options})
    events, counts = render(read_version(), options, engine)
    outputs = {
        REFERENCES / "vmc-events.md": events,
        REFERENCES / "vmc-options.txt": "".join("%s\t%s\n" % (o.name, o.kind) for o in options),
    }
    if args.check:
        stale = [path for path, text in outputs.items() if not path.exists() or path.read_text("utf-8") != text]
        for path in stale:
            print("%s is out of date; run tools/build_vmc_reference.py" % path.relative_to(REPO), file=sys.stderr)
        return 1 if stale else 0
    for path, text in outputs.items():
        path.write_bytes(text.encode("utf-8"))
    print("%d options, %d events in VMC's notes, %d more VMC events, %d base-game events" % counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
