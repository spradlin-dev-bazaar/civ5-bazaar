The host's own code, compiled into the host DLL:

- `CivPluginApi.h`: the contract with plugin DLLs.
- `CivHostRuntime`: loading and unloading plugins, running their hooks, and catching their crashes.
- `CivHostOrder`: the plugin order the player sets on the Plugins screen: the text it is saved as, matching it to the listed plugins, and the screen's rows.
- `CivHostSetup`: finding the Advanced Setup screen that the Plugins screen replaced, so Continue can open it.
- `CivHostEngine`: the link to the game: the plugin list from the database, the saved order file, the Plugins screen's calls, the log file and in-game notices.
- `CivHostHooks.h`: what the generated hook wrappers need from the runtime.
- `CivTurnBench.h`: a turn timer used only in benchmark builds.
