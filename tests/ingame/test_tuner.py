"""Tests for the tuner port client, against a fake game on a local port."""

import os
import re
import socket
import struct
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))

from bazaar_check import tuner  # noqa: E402

START = re.compile(r"^print\('(__start_[0-9a-f]+__)'\)")
END = re.compile(r"print\('(__done_[0-9a-f]+__)'\)$")


def decode_lua_string(literal):
    body = literal[1:-1]
    out, i = "", 0
    while i < len(body):
        if body[i] != "\\":
            out += body[i]
            i += 1
        elif body[i + 1] == "n":
            out += "\n"
            i += 2
        elif body[i + 1].isdigit():
            out += chr(int(body[i + 1 : i + 4]))
            i += 4
        else:
            out += body[i + 1]
            i += 2
    return out


class FakeTunerServer(threading.Thread):
    """Answers the state list, and each command with respond(state, code) between the command's own markers. before
    is sent ahead of the start marker, as the game's other scripts and late answers would be."""

    def __init__(self, states, respond=None, with_l=True, before=(), noise_before_states=False):
        super().__init__(daemon=True)
        self.states = states
        self.respond = respond or (lambda state, code: [])
        self.with_l = with_l
        self.before = before
        self.noise_before_states = noise_before_states
        self.commands = []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.start()

    def stop(self):
        self.server.close()

    def run(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                try:
                    self.serve(conn)
                except OSError:
                    pass

    def send(self, conn, fields, listener=0):
        payload = b"".join(f.encode() + b"\0" for f in fields)
        conn.sendall(struct.pack("<II", len(payload), listener) + payload)

    def serve(self, conn):
        while True:
            head = conn.recv(8, socket.MSG_WAITALL)
            if len(head) < 8:
                return
            size, listener = struct.unpack("<II", head)
            text = conn.recv(size, socket.MSG_WAITALL).rstrip(b"\0").decode()
            if text == "LSQ:":
                if self.noise_before_states:
                    self.send(conn, ["O", "MainMenu: something else printed"])
                fields = ["L"] if self.with_l else []
                for sid, name in self.states:
                    fields += [str(sid), name]
                self.send(conn, fields, listener)
                continue
            _, sid, code = text.split(":", 2)
            self.commands.append((int(sid), code))
            start, end = START.search(code), END.search(code)
            if not end:
                continue
            name = dict(self.states)[int(sid)]
            replies = self.respond(name, code)
            if replies is None:
                continue
            for fields in self.before:
                self.send(conn, fields)
            self.send(conn, ["O", "%s: %s" % (name, start.group(1))])
            for fields in replies:
                self.send(conn, fields)
            self.send(conn, ["O", "%s: %s" % (name, end.group(1))])


class TunerTest(unittest.TestCase):
    def connect(self, fake):
        self.addCleanup(fake.stop)
        t = tuner.Tuner(port=fake.port)
        t.connect(5)
        self.addCleanup(t.close)
        return t

    def test_frame_is_length_listener_and_zero_ended_text(self):
        self.assertEqual(tuner.frame("LSQ:", 1), struct.pack("<II", 5, 1) + b"LSQ:\0")

    def test_state_list_with_or_without_its_l_field(self):
        self.assertEqual(
            tuner.parse_states(["L", "0", "Main State", "4", "InGame"]), [(0, "Main State"), (4, "InGame")]
        )
        self.assertEqual(tuner.parse_states(["0", "Main State"]), [(0, "Main State")])
        self.assertIsNone(tuner.parse_states(["O", "InGame: hello"]))

    def test_lua_strings_escape_and_split_within_the_byte_limit(self):
        text = 'say "hi"\\\n\tnow é ' * 40
        pieces = tuner.lua_strings(text, 50)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p.encode("utf-8")) <= 50 for p in pieces))
        self.assertEqual("".join(decode_lua_string(p) for p in pieces), text)

    def test_control_characters_never_reach_the_game_raw(self):
        (piece,) = tuner.lua_strings("a\rb\0c\x01d\te\nf", 100)
        self.assertFalse([c for c in piece if ord(c) < 32])
        self.assertEqual(piece, '"a\\013b\\000c\\001d\\009e\\nf"')

    def test_lua_text_quotes_and_escapes(self):
        self.assertEqual(tuner.lua_text('a"b\\c'), '"a\\"b\\\\c"')

    def test_run_returns_only_what_the_command_printed(self):
        def respond(state, code):
            return [["O", "MainMenu: from another state"], ["O", "%s: one\ntwo" % state], ["O", "%s: three" % state]]

        before = [["O", "InGame: printed by the game's own script"], ["O", "InGame: __done_0123abcd__"]]
        t = self.connect(FakeTunerServer([(3, "MainMenu"), (9, "InGame")], respond, before=before))
        self.assertEqual(t.run("InGame", "print(1)"), ["one", "two", "three"])

    def test_states_without_the_l_field_and_after_other_output(self):
        t = self.connect(FakeTunerServer([(3, "MainMenu")], with_l=False, noise_before_states=True))
        self.assertEqual(t.states(), [(3, "MainMenu")])

    def test_newest_state_of_a_name_is_used(self):
        fake = FakeTunerServer([(50, "LoadScreen"), (180, "LoadScreen")])
        t = self.connect(fake)
        t.run("LoadScreen", "x = 1")
        self.assertEqual(fake.commands[-1][0], 180)

    def test_a_lua_error_raises(self):
        t = self.connect(FakeTunerServer([(9, "InGame")], lambda s, c: [["O", "InGame: %s boom" % tuner.ERROR_TAG]]))
        with self.assertRaisesRegex(tuner.LuaError, "boom"):
            t.run("InGame", "error('boom')")

    def test_a_refused_command_raises(self):
        t = self.connect(FakeTunerServer([(9, "InGame")], lambda s, c: [["ERR:", "too long"]]))
        with self.assertRaisesRegex(tuner.LuaError, "refused"):
            t.run("InGame", "x = 1")

    def test_no_answer_raises_after_the_timeout(self):
        t = self.connect(FakeTunerServer([(9, "InGame")], lambda s, c: None))
        with self.assertRaisesRegex(tuner.TunerError, "LoggingEnabled"):
            t.run("InGame", "x = 1", timeout=0.5)

    def test_an_unknown_state_is_its_own_error(self):
        t = self.connect(FakeTunerServer([(9, "InGame")]))
        with self.assertRaisesRegex(tuner.NoSuchState, "no Lua state named Nowhere"):
            t.run("Nowhere", "x = 1")

    def test_long_code_goes_in_pieces_into_a_buffer(self):
        fake = FakeTunerServer([(9, "InGame")])
        t = self.connect(fake)
        code = "x = 1 " * 600
        t.run("InGame", code)
        pieces = [c for _, c in fake.commands if not END.search(c)]
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(c.encode("utf-8")) < 2000 for _, c in fake.commands))
        self.assertTrue(pieces[0].startswith(tuner.BUFFER + ' = "'))
        self.assertTrue(pieces[1].startswith("%s = %s .. " % (tuner.BUFFER, tuner.BUFFER)))
        joined = "".join(decode_lua_string(p.split(" = ", 1)[1].split(" .. ", 1)[-1]) for p in pieces)
        self.assertEqual(joined, code)
        self.assertIn("loadstring(%s)" % tuner.BUFFER, fake.commands[-1][1])

    def test_a_message_cut_by_a_timeout_is_kept_for_the_next_read(self):
        ours, theirs = socket.socketpair()
        self.addCleanup(ours.close)
        self.addCleanup(theirs.close)
        t = tuner.Tuner()
        t.sock = ours
        message = tuner.frame("O\0InGame: hello", 0)
        theirs.sendall(message[:6])
        self.assertIsNone(t._read(0.2))
        threading.Timer(0.1, lambda: theirs.sendall(message[6:])).start()
        self.assertEqual(t._read(2), (0, ["O", "InGame: hello"]))

    def test_connect_gives_up_when_nothing_answers(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        started = time.time()
        with self.assertRaisesRegex(tuner.TunerError, "EnableTuner"):
            tuner.Tuner(port=port).connect(0)
        self.assertLess(time.time() - started, 5)


if __name__ == "__main__":
    unittest.main()
