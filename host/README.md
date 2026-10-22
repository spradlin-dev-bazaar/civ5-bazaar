The host's own code, compiled into the host DLL:

- `CivPluginApi.h`: the contract with plugin DLLs.
- `CivHostRuntime`: loading and unloading plugins, running their hooks, and catching their crashes.
- `CivHostEngine`: the link to the game: the plugin list from the database, the log file and in-game notices.
- `CivHostHooks.h`: what the generated hook wrappers need from the runtime.
- `CivTurnBench.h`: a turn timer used only in benchmark builds.
