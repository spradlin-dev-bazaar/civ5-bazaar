# In-game checks

Some of Bazaar can only be checked in the game. `package.py` builds the test plugins below against the last `build-hooked.cmd` build, and lays out a mod for each, and for Bazaar itself, in `out\MODS`. Nothing is installed: copy the folders into `Documents\My Games\Sid Meier's Civilization 5\MODS`. In the game's Mods menu, turn on Bazaar - VMC Bootstrap (required), the Bazaar version from `out\MODS`, and the test mods you need. Your Workshop subscription to Bazaar comes back into MODS each time the game starts, so check you turned on the right version.

`Bazaar.log` and `Lua.log` are in `Documents\My Games\Sid Meier's Civilization 5\Logs`. FireTuner connects only with `EnableTuner = 1` in that folder's `config.ini`, and a command that uses `Game` must run in an in-game Lua state such as InGame.

`package.py bench plain` and `package.py bench host` lay out the benchmark mod instead.

## What each test mod should show

- **Toy Gold Plugin** hooks the human player's turn and replaces the score. Each turn, `Bazaar.log` has "turn starting for *civilization* with *n* gold" and "turn finished …". The human player's score is 4242, and Bazaar notes once that the replacement did not run the game's own function. With Toy Saves on too, each of those turns also logs "Toy Saves' TurnsPlayed says *n*", from a function Toy Saves publishes; without it, that line is missing and Toy Gold runs as before.
- **Toy Rival Plugin** replaces the score too. Below Toy Gold on the Plugins screen, it is turned away with "Toy Gold, higher in the list, already replaces CvPlayer::GetScore(…)". Above it, it wins, and the human player's score is 1.
- **Toy Crash Plugin** crashes at the end of the human player's first turn. A pop-up in the middle of the screen names it, it stays off until you go back to the main menu (loading a save during a game does not turn it back on), and `Bazaar.log` has the crash with its call stack. In FireTuner, `print(pcall(Game.ToyCrashLua))` crashes it in a Lua function instead: it prints false and "Toy Crash stopped working in a Lua function and was turned off", a notice appears, and the game keeps running. Run that before ending the first turn, or the turn's crash turns it off first.
- **Toy Newer Plugin** is built for a newer Bazaar. The Plugins screen shows it as not loaded, "Built for a newer Bazaar (API …)", and `Bazaar.log` never has its "this ran" line.
- **Toy Hand Plugin** uses the hand-placed hooks and adds two Lua functions. `Bazaar.log` has a line for each pop-up, each notification, each deal and each cancelled unit order. It also has one "asked whether a plugin plays player" line when a turn ends, and a line when the game asks about an eliminated player's slot.
- **Toy Hand Replace Plugin** replaces CvNotifications::Add, which runs a hook Toy Hand uses. With both on, the Plugins screen holds back whichever is lower in the list, with a note and a Use both anyway checkbox. Checked, both load: `Bazaar.log` has "replaced CvNotifications::Add and ran the original", and Toy Hand still logs every notification.
- **Toy VMC Check** writes to `Lua.log`: the DLL id, "EVENTS_PLAYER_TURN on: true", and "PlayerDoneTurn for player *n*" each turn. With Toy Hand on, it also writes "Game.ToyHandPing: Toy Hand added this to the Game table" and "Game.ToyHandRaise: … Toy Hand raised this Lua error on purpose". After that Lua error, going back to the main menu must not log "Plugins were not unloaded because one of them was still running".
- **Toy Saves Plugin** keeps data in saved games, and publishes a function, TurnsPlayed, that Toy Gold calls. Its mod ID is `b012c631-4178-4d68-99af-7c2fcf5d3701`. At the start of each of the human player's turns, `Bazaar.log` has a line for each of their units ("unit Warrior (ID 8192): 3 turns alive") and cities ("city Rome (ID 8192): founded by Rome"), and "turn *n* of this game for *civilization*; capital tile mark *x*, big 9007199254740993", where the mark grows by 1.5 each turn. Each save logs "saved: *n* turns", and each new game or load logs "loaded: *n* turns" or "no saved data: 0 turns". When the game replaces a unit or city, it logs "unit replaced: …" or "city replaced: …" with the value the new one carried over.

## Checking saved games

With Bazaar and Toy Saves on:

1. **Save and load.** Start a game, play a few turns, save, and play one more turn. Load the save during the game, and again from the main menu. Each time, `Bazaar.log` has "loaded: *n* turns", and the next turn's lines match the ones from before the load: the same unit counts and the same capital tile mark. The autosave as a game starts, which the game writes on a thread of its own, logs "saved: 0 turns".
2. **Carry-over and Lua.** Load a save from a few turns in, open FireTuner in the InGame Lua state, and paste this as one block. It upgrades one of your units and takes an AI capital for you:
   ```lua
   id = "b012c631-4178-4d68-99af-7c2fcf5d3701"; p = Game.GetActivePlayer(); me = Players[p]
   for u in me:Units() do old = u; break end
   print("old unit", old:GetName(), Game.GetPluginValue(id, "", "TurnsAlive", p, old:GetID()))
   nu = me:InitUnit(GameInfoTypes.UNIT_SPEARMAN, old:GetX(), old:GetY()); nu:Convert(old, true)
   print("new unit", nu:GetName(), Game.GetPluginValue(id, "", "TurnsAlive", p, nu:GetID()))
   for i = 0, GameDefines.MAX_MAJOR_CIVS - 1 do if i ~= p and Players[i]:IsAlive() and Players[i]:GetCapitalCity() then ai = i; break end end
   city = Players[ai]:GetCapitalCity(); print("their city", city:GetName(), Game.GetPluginValue(id, "", "Founder", ai, city:GetID())); me:AcquireCity(city, true, false)
   c = me:GetCapitalCity(); print(Game.GetPluginValue(id, "", "Mark", c:GetX(), c:GetY()), Game.GetPluginValue(id, "", "TurnsAlive", p, 0))
   ```
   The new unit prints the old one's count, and `Bazaar.log` has "unit replaced: …" with it. "city replaced: …" names the AI's civilization as the founder, as the block printed. The last line prints the capital tile mark and nil, since 0 is no unit's ID.
3. **Older saves.** A game saved with Bazaar 0.4 loads with no notice about Bazaar's part of the save. Toy Saves does not load with it, since the save was made without its mod.

Checked once on 2026-10-27 and covered by the runtime tests since: a unit that dies is gone after a save and load, a plugin unchecked on the Plugins screen for one save keeps its data, and a new game after a loaded one starts with "no saved data: 0 turns".

Not checked in the game: a civilian handed back through the pop-up, a unit a city-state gives you, and the notice for a save whose Bazaar part is damaged. The runtime tests cover reading a damaged part.
