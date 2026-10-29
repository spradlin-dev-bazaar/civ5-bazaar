# In-game checks

Some of Bazaar can only be checked in the game. `run.py` checks it there with nobody at the keyboard:

```
.venv\Scripts\python.exe tests\ingame\run.py
```

It builds the test plugins below against the last `build-hooked.cmd` build with `package.py`, then plays each checks file in `checks\` in Civilization V, one game launch each, and prints PASS or FAIL for each check and a summary at the end. The whole run takes about ten minutes. `run.py crash_turn` plays one file. Afterwards it removes the test mods from MODS; the test build of Bazaar (mod version 900) and the VMC Bootstrap stay, and so do the saves its checks make in `ModdedSaves\single`, which the next run replaces. It needs what any check needs: Civilization V closed, `EnableTuner = 1` and `LoggingEnabled = 1` in its `config.ini`, and DirectX 11 chosen the last time it was started from Steam. `tools\bazaar_check\README.md` explains checks files and what a run puts back.

`package.py bench plain` and `package.py bench host` lay out the benchmark mod instead, which `run.py` does not use.

## The test plugins and what checks them

| Test plugin | What it does | Checked by |
|---|---|---|
| Toy Gold | Logs the start and end of the human player's turns, and replaces the score with 4242 without running the game's own function. | `plugins`, `rival_wins`, `saves` |
| Toy Rival | Replaces the score too: turned away below Toy Gold, the winner above it, with a score of 1. | `plugins`, `rival_wins` |
| Toy Newer | Built for a newer Bazaar, so it is not loaded. | `plugins` |
| Toy Hand | Uses the hand-placed hooks and adds two Lua functions, one of which raises a Lua error on purpose. | `plugins`, `use_both` |
| Toy Hand Replace | Replaces a function whose hook Toy Hand uses: held back below Toy Hand, loaded with Use both anyway. | `plugins`, `use_both` |
| Toy VMC Check | A Lua mod: switches on one of VMC's events and writes what it sees, and Toy Hand's Lua functions, to `Lua.log`. | `plugins` |
| Toy Crash | Crashes as the human player's first turn starts, or in a Lua function. | `crash_turn`, `crash_lua` |
| Toy Saves | Keeps data in saved games, publishes values that carry over when the game replaces a unit or city, and a function Toy Gold calls. | `saves` |

