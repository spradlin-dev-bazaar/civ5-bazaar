# In-game checks

Some of Bazaar can only be checked in the game. `package.py` builds the test plugins below against the last `build-hooked.cmd` build, and lays out a mod for each, and for Bazaar itself, in `out\MODS`. Nothing is installed: copy the folders into `Documents\My Games\Sid Meier's Civilization 5\MODS`. In the game's Mods menu, turn on Bazaar - VMC Bootstrap (required), the Bazaar version from `out\MODS`, and the test mods you need. Your Workshop subscription to Bazaar comes back into MODS each time the game starts, so check you turned on the right version.

`Bazaar.log` and `Lua.log` are in `Documents\My Games\Sid Meier's Civilization 5\Logs`. FireTuner connects only with `EnableTuner = 1` in that folder's `config.ini`, and a command that uses `Game` must run in an in-game Lua state such as InGame.

`package.py bench plain` and `package.py bench host` lay out the benchmark mod instead.

## What each test mod should show

- **Toy Gold Plugin** hooks the human player's turn and replaces the score. Each turn, `Bazaar.log` has "turn starting for *civilization* with *n* gold" and "turn finished …". The human player's score is 4242, and Bazaar notes once that the replacement did not run the game's own function.
- **Toy Rival Plugin** replaces the score too. Below Toy Gold on the Plugins screen, it is turned away with "Toy Gold, higher in the list, already replaces CvPlayer::GetScore(…)". Above it, it wins, and the human player's score is 1.
- **Toy Crash Plugin** crashes at the end of the human player's first turn. A pop-up in the middle of the screen names it, it stays off until the game's core reloads (back at the main menu, or when a save loads), and `Bazaar.log` has the crash with its call stack. In FireTuner, `print(pcall(Game.ToyCrashLua))` crashes it in a Lua function instead: it prints false and "Toy Crash stopped working in a Lua function and was turned off", a notice appears, and the game keeps running. Run that before ending the first turn, or the turn's crash turns it off first.
- **Toy Newer Plugin** is built for a newer Bazaar. The Plugins screen shows it as not loaded, "Built for a newer Bazaar (API …)", and `Bazaar.log` never has its "this ran" line.
- **Toy Hand Plugin** uses the hand-placed hooks and adds two Lua functions. `Bazaar.log` has a line for each pop-up, each notification, each deal and each cancelled unit order. It also has one "asked whether a plugin plays player" line when a turn ends, and a line when the game asks about an eliminated player's slot.
- **Toy Hand Replace Plugin** replaces CvNotifications::Add, which runs a hook Toy Hand uses. With both on, the Plugins screen holds back whichever is lower in the list, with a note and a Use both anyway checkbox. Checked, both load: `Bazaar.log` has "replaced CvNotifications::Add and ran the original", and Toy Hand still logs every notification.
- **Toy VMC Check** writes to `Lua.log`: the DLL id, "EVENTS_PLAYER_TURN on: true", and "PlayerDoneTurn for player *n*" each turn. With Toy Hand on, it also writes "Game.ToyHandPing: Toy Hand added this to the Game table" and "Game.ToyHandRaise: … Toy Hand raised this Lua error on purpose". After that Lua error, going back to the main menu must not log "Plugins were not unloaded because one of them was still running".
