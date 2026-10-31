# In-game checks

Some of Bazaar can only be checked in the game. `run.py` checks it there with nobody at the keyboard:

```
.venv\Scripts\python.exe tests\ingame\run.py
```

It builds the test plugins below against the last `build-hooked.cmd` build with `package.py`, then plays each checks file in `checks\` in Civilization V, one game launch each, and prints PASS or FAIL for each check and a summary at the end. The whole run takes about ten minutes. `run.py crash_turn` plays one file. Afterwards everything it changed is back as it was, MODS and the saves its checks make included. `run.py --play crash_turn` builds the test plugins and starts the game with that file's mods switched on, for you to play by hand; closing the game puts everything back. It needs what any check needs: Civilization V closed, `EnableTuner = 1` and `LoggingEnabled = 1` in its `config.ini`, and DirectX 11 chosen the last time it was started from Steam. `tools\bazaar_check\README.md` explains checks files and what a run puts back.

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

## The test DLC pack

`dlc\dlc_setup\Bazaar Test Skin` is a DLC pack whose UI skin has its own Advanced Setup script, as some mods install themselves. `run.py` copies it into the game's own `Assets\DLC` folder, which it finds through Steam, for the `dlc_setup` run only, and takes it out again afterwards. If a run is stopped by force, the pack stays there, and Advanced Setup does nothing in any game until `run.py` next starts and takes it out, or until you delete `Bazaar Test Skin` from that folder by hand.

`dlc_setup` checks that the game still shows Bazaar's Plugins screen with the pack installed, and that Continue then opens the pack's script with the game's own layout. `plugins` checks that with no such pack, Continue opens the game's own Advanced Setup, in its base layout, so it fails on a computer that has a DLC pack with its own Advanced Setup installed.

