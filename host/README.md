The host's own code, compiled into the host DLL. Every `.cpp` file here is built into it, and the runtime tests build all of them but `CivHostEngine.cpp`.

- `CivPluginApi.h`: the contract with plugin DLLs.
- `CivHostRuntime`: loading and unloading plugins, running their hooks and their save and load functions, and catching their crashes.
- `CivHostSaves`: Bazaar's part of a saved game: each plugin's data under its mod's ID and plugin ID, and the data of plugins that are off, kept for the next save.
- `CivHostValues`: the values plugins keep on players, cities, units and plots: reading and setting them, carrying them over to a new unit or city, and their place in Bazaar's part of a save.
- `CivHostCrash`: what Bazaar.log says about a plugin's crash: where it happened, what memory it touched, and its call stack, with function names from the plugin's `.pdb` when it has one.
- `CivHostHand`: the hand-placed hooks: the engine's calls from inside its functions, and how each one reaches the plugins.
- `CivHostOrder`: the plugin order the player sets on the Plugins screen: the text it is saved as, matching it to the listed plugins, and the screen's rows and notes.
- `CivHostNotices`: the notices waiting for a game to show them, and naming a lasting problem only once a game.
- `CivHostMods`: the mods the game has switched on, as its own mod database lists them: finding a plugin's DLL or a screen's file among their files, and refusing a plugin whose mod does not affect saved games.
- `CivHostSetup`: finding the Advanced Setup screen that the Plugins screen replaced, so Continue can open it.
- `CivHostPath`: file names and paths. Bazaar keeps them in UTF-8 and gives them to Windows as wide characters, so names in any language work.
- `CivHostEngine`: the link to the game: the plugin list and the switched-on mods from its databases, the saved order file, the Plugins screen's calls, the log file, Bazaar's part of the game's saves, telling which player, city, unit or plot a value is on, Lua's `Game.GetPluginValue`, and showing notices in the game.
- `CivHostHooks.h`: what the generated hook wrappers need from the runtime.
- `CivHostPart.h`: writing and reading the numbers and texts Bazaar's part of a save is made of.
- `CivHostLock.h`: a lock for what the game's save thread shares with the rest of Bazaar, since the game writes one save from a thread of its own.
- `CivTurnBench.h`: a turn timer used only in benchmark builds.
