"""tools/build_vmc_reference.py, which writes the new-lua-mod skill's list of Lua events: how it reads VMC's options and
the engine's calls, on small made-up sources and on the real ones, and that the list in the skill is current.

python -m unittest discover -s tests/claude_plugin
"""

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools"))

import build_vmc_reference as reference  # noqa: E402

SKILL = os.path.join(REPO, "claude-plugin", "skills", "new-lua-mod", "SKILL.md")


def temp_folder(test):
    folder = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, folder)
    return folder


class ReadOptionsTest(unittest.TestCase):
    def read(self, rows):
        folder = temp_folder(self)
        with open(os.path.join(folder, "CustomModOptions.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<!-- before the root -->\n')
            f.write("<GameData>\n  <CustomModOptions>\n" + rows + "  </CustomModOptions>\n</GameData>\n")
        with mock.patch.object(reference, "VMC", Path(folder)):
            return {o.name: o for o in reference.read_options()}

    def test_comments_above_a_row_and_on_its_line_are_its_notes_and_a_blank_line_drops_them(self):
        options = self.read(
            "    <!-- dropped -->\n\n"
            "    <!-- above - -->\n"
            '    <Row Class="3" Name="A" Value="1"/> <!-- same line -->\n'
            "    <!-- Row 2 -->\n"
            '    <Row Class="0" Name="B" Value="7"/>\n'
            '    <Row Class="1" Name="C"/>\n'
        )
        self.assertEqual(options["A"].notes, ["above", "same line"])
        self.assertEqual((options["A"].kind, options["A"].default), ("switch", "1"))
        self.assertEqual((options["B"].notes, options["B"].kind, options["B"].default), ([], "number", "7"))
        self.assertEqual(options["C"].default, "0")

    def test_every_row_of_the_real_file_is_an_option(self):
        rows = ElementTree.parse(reference.VMC / "CustomModOptions.xml").getroot().iter("Row")
        self.assertEqual([o.name for o in reference.read_options()], [row.get("Name") for row in rows])


class AnswerReadingTest(unittest.TestCase):
    def base(self, after):
        code = '"Event", args.get(), bResult))\n{\n' + after
        filled = reference.FILLED_ANSWER.match(code, code.index(","))
        return reference.answer_reading(code, filled.end(), filled.group(1))

    def vmc(self, after):
        return reference.answer_reading(", GetID()) " + after, 0, None)

    def test_a_false_answer_that_refuses_is_the_usual_reading(self):
        self.assertEqual(self.vmc("== GAMEEVENTRETURN_FALSE) { return false; }"), "refuses")
        self.assertEqual(self.base("if (bResult == false) { return false; }"), "refuses")
        self.assertEqual(self.base("if(!bResult) return false;"), "refuses")
        self.assertEqual(self.base("bUseTech = bResult;"), "refuses")

    def test_a_true_answer_that_makes_the_game_act_is_read_as_acting(self):
        self.assertEqual(self.vmc("== GAMEEVENTRETURN_TRUE) { return false; }"), "acts")
        self.assertEqual(self.base("if(bResult) { return; }"), "acts")
        self.assertEqual(self.base("if (bResult == true) return true;"), "acts")

    def test_the_reading_that_comes_first_wins(self):
        self.assertEqual(self.base("if(bResult) { bUseTech = bResult; }"), "acts")

    def test_an_answer_the_next_statement_never_reads_is_unused(self):
        self.assertEqual(self.base("bUseTech = bOther;"), "unused")

    def test_a_shape_it_does_not_know_is_none(self):
        self.assertIsNone(self.vmc("!= GAMEEVENTRETURN_FALSE) { return false; }"))
        self.assertIsNone(self.base("if (bResult != false) { return false; }"))

    def test_a_call_that_ends_its_own_statement_is_a_shape_it_does_not_know(self):
        code = '"Event", args.get(), bResult);\nif (bResult) { return; }'
        filled = reference.FILLED_ANSWER.match(code, code.index(","))
        self.assertIsNone(reference.answer_reading(code, filled.end(), filled.group(1)))


class FakeEngineTest(unittest.TestCase):
    """read_engine on a few made-up engine files."""

    def read(self, sources, **patches):
        folder = temp_folder(self)
        for name, text in sources.items():
            with open(os.path.join(folder, name), "w", encoding="latin-1") as f:
                f.write(text)
        patches = dict({"ENGINE": Path(folder), "NOT_EVENTS": set(), "EXTRA_NOTES": {}}, **patches)
        with contextlib.ExitStack() as stack:
            for name, value in patches.items():
                stack.enter_context(mock.patch.object(reference, name, value))
            return reference.read_engine({"EVENTS_X", "EVENTS_Y", "EVENTS_Z"})

    def stop(self, sources, **patches):
        with self.assertRaises(SystemExit) as stop:
            self.read(sources, **patches)
        return str(stop.exception)

    def test_options_joined_by_and_are_all_needed_and_an_or_or_a_negation_is_not_counted(self):
        engine = self.read(
            {
                "A.cpp": '#define MOD_EVENTS_Z\n#define GAMEEVENT_Go "Go", "i"\n'
                "void a() {\n"
                "  if (MOD_EVENTS_X && MOD_EVENTS_Y) { GAMEEVENTINVOKE_HOOK(GAMEEVENT_Go, 1); }\n"
                "  if (MOD_EVENTS_X || MOD_EVENTS_Y) { GAMEEVENTINVOKE_HOOK(GAMEEVENT_Go, 2); }\n"
                "  if (!MOD_EVENTS_X) { GAMEEVENTINVOKE_HOOK(GAMEEVENT_Go, 3); }\n"
                "#if defined(MOD_EVENTS_Z)\n  GAMEEVENTINVOKE_HOOK(GAMEEVENT_Go, 4);\n#endif\n"
                "#if defined(MOD_EVENTS_UNDEFINED)\n  GAMEEVENTINVOKE_HOOK(GAMEEVENT_Gone, 5);\n#endif\n"
                "  // GAMEEVENTINVOKE_HOOK(GAMEEVENT_Commented, 6);\n"
                "}\n"
            }
        )
        sites = engine.vmc_sites["Go"]
        self.assertEqual([site.options for site in sites], [["EVENTS_X", "EVENTS_Y"], [], [], []])
        self.assertEqual(sites[3].blocks, ["EVENTS_Z"])
        self.assertNotIn("Gone", engine.kinds)
        self.assertNotIn("Commented", engine.kinds)

    def test_an_event_read_one_way_at_one_call_and_the_other_way_at_another_stops_the_script(self):
        message = self.stop(
            {
                "A.cpp": "void a() {\n"
                "  if (GAMEEVENTINVOKE_TESTALL(GAMEEVENT_Ask, 1) == GAMEEVENTRETURN_FALSE) { return; }\n}\n",
                "B.cpp": 'void b() {\n  if (LuaSupport::CallTestAll(pkScriptSystem, "Ask", args.get(), bResult)) {\n'
                "    if (bResult) { return; }\n  }\n}\n",
            }
        )
        self.assertIn("read one way at one call and the other way at another: Ask", message)

    def test_a_reading_it_does_not_know_stops_the_script_naming_the_line(self):
        message = self.stop(
            {
                "A.cpp": "void a() {\n"
                "  if (GAMEEVENTINVOKE_TESTALL(GAMEEVENT_Ask, 1) != GAMEEVENTRETURN_FALSE) { return; }\n}\n"
            }
        )
        self.assertIn("A.cpp line 2", message)

    def test_a_hand_list_name_the_engine_no_longer_has_stops_the_script(self):
        source = {"A.cpp": "void a() { GAMEEVENTINVOKE_HOOK(GAMEEVENT_Go, 1); }\n"}
        self.assertIn(
            "NOT_EVENTS names test calls the engine no longer makes: TestEvent",
            self.stop(source, NOT_EVENTS={"TestEvent"}),
        )
        self.assertIn(
            "EXTRA_NOTES names events the engine no longer has: Gone", self.stop(source, EXTRA_NOTES={"Gone": "x"})
        )


class EngineTest(unittest.TestCase):
    """The real engine and VMC. After an engine or VMC change, a failure here means checking how the script reads the
    changed calls, not only regenerating the list."""

    @classmethod
    def setUpClass(cls):
        cls.options = reference.read_options()
        cls.engine = reference.read_engine({o.name for o in cls.options})

    def test_the_events_that_act_on_true_and_the_call_that_ignores_its_answer_are_found(self):
        self.assertEqual(self.engine.acts_on_true, {"CannotParadropFrom", "CanSaveUnit", "CanRazeOverride"})
        self.assertEqual(self.engine.unused, {"GoodyHutCanResearch": ["CvPlayer.cpp"]})

    def test_the_engine_s_own_test_calls_are_not_events(self):
        for name in ("TestEvent", "TestAccumulator"):
            self.assertNotIn(name, self.engine.kinds)

    def line(self, signature):
        return reference.option_event(signature, "EVENTS_TEST", self.engine)[0]

    def test_default_values_are_left_out_of_the_arguments(self):
        line = self.line("GameEvents.CustomMissionPossible.Add(function(iPlayer, iFlags=0, iTurn=-1) return false end)")
        self.assertIn("function(iPlayer, iFlags, iTurn)", line)

    def test_only_a_value_event_shows_what_vmc_s_example_handler_returns(self):
        self.assertIn(
            "VMC's example handler returns `0`.",
            self.line("GameEvents.QuestGetData.Add(function(iPlayer) return 0 end)"),
        )
        self.assertNotIn(
            "example handler", self.line("GameEvents.CityCanAirlift.Add(function(iPlayer) return false end)")
        )

    def test_marks_and_notes_show_on_every_listing_of_the_event(self):
        text, _ = reference.render(reference.read_version(), self.options, self.engine)
        for event, note in [
            ("CannotParadropFrom", reference.FALSE_BY_DEFAULT),
            ("CanSaveUnit", reference.FALSE_BY_DEFAULT),
            ("GoodyHutCanResearch", "The game ignores the answer at one of the places it asks it (CvPlayer.cpp)."),
        ]:
            lines = [line for line in text.splitlines() if "`%s" % event in line or ".%s." % event in line]
            self.assertTrue(lines and all(note in line for line in lines), event)

    def test_every_mark_the_list_can_show_is_explained_in_the_skill(self):
        with open(reference.__file__, encoding="utf-8") as f:
            labels = set(re.findall(r"\*\*([^*]+)\*\*", f.read()))
        with open(SKILL, encoding="utf-8") as f:
            skill = f.read()
        # "misnamed in VMC's notes, and never fired" combines two marks the skill explains one at a time.
        missing = [label for label in labels if not all("**%s**" % part in skill for part in label.split(", and "))]
        self.assertEqual(missing, [])


class CheckTest(unittest.TestCase):
    def run_main(self, *args):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["build_vmc_reference.py", *args]), contextlib.redirect_stderr(err):
            with contextlib.redirect_stdout(io.StringIO()):
                return reference.main(), err.getvalue()

    def test_the_list_in_the_skill_is_current(self):
        self.assertEqual(self.run_main("--check"), (0, ""))

    def test_a_changed_or_missing_file_is_reported_out_of_date(self):
        folder = Path(temp_folder(self))
        with mock.patch.object(reference, "REFERENCES", folder), mock.patch.object(reference, "REPO", folder):
            self.assertEqual(self.run_main()[0], 0)
            self.assertEqual(self.run_main("--check"), (0, ""))
            with open(folder / "vmc-events.md", "a", encoding="utf-8") as f:
                f.write("edited by hand\n")
            os.remove(folder / "vmc-options.txt")
            code, err = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("vmc-events.md is out of date", err)
        self.assertIn("vmc-options.txt is out of date", err)


if __name__ == "__main__":
    unittest.main()
