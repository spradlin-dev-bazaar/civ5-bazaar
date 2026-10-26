The host's own code, compiled into the host DLL. Every `.cpp` file here is built into it, and the runtime tests build all of them but `CivHostEngine.cpp`.

- `CivPluginApi.h`: the contract with plugin DLLs.
- `CivHostRuntime`: loading and unloading plugins, running their hooks, and catching their crashes.
- `CivHostCrash`: what Bazaar.log says about a plugin's crash: where it happened, what memory it touched, and its call stack, with function names from the plugin's `.pdb` when it has one.
- `CivHostHand`: the hand-placed hooks: the engine's calls from inside its functions, and how each one reaches the plugins.
- `CivHostOrder`: the plugin order the player sets on the Plugins screen: the text it is saved as, matching it to the listed plugins, and the screen's rows.
- `CivHostSetup`: finding the Advanced Setup screen that the Plugins screen replaced, so Continue can open it.
- `CivHostEngine`: the link to the game: the plugin list from the database, the saved order file, the Plugins screen's calls, the log file and in-game notices.
- `CivHostHooks.h`: what the generated hook wrappers need from the runtime.
- `CivTurnBench.h`: a turn timer used only in benchmark builds.
