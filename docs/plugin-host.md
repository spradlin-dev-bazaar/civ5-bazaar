# Plugin host: one DLL, many plugin DLLs

Status: planned 2026-10-19, reworked 2026-10-21, not started. Nothing in this document has been built or verified unless a section says so.

## Goal

The game loads exactly one rules DLL. Today that DLL is the Local MCP Server mod, so every other change to the game's rules (city-state explorer fix, friendship rules, calmer AI) either goes into the MCP mod or does not exist. That mixes mods of different intent in one binary and makes it impossible for anyone else to add their own.

The goal is one **host DLL** that loads any number of **plugin DLLs**, each its own Workshop mod with its own intent:

- the MCP server is a plugin, not part of the host;
- rules fixes are their own plugins (or plain Lua mods on the host's hooks);
- other developers can write plugins against a documented SDK;
- an existing DLL mod can become a plugin: each engine function it edited becomes a replacement registered by the plugin, with no change to the host;
- a plugin built for an older host keeps running on a newer one.

The rule that outranks everything else: **the host never contains the MCP server, and the MCP plugin never contains rules changes.**

## Shape

```
Host DLL  (replacement CvGameCore_Expansion2.dll, one per game)
  = whoward69's DLL-VMC v97 fork + plugin loader + every engine class exported
    + a hook point on every engine function + a Plugins screen in the front end
  own GUID, own name, credits VMC, source on GitHub

Plugin DLLs  (ordinary mods: one folder each, with plugins/<Name>.dll inside)
  MCPServer.dll          the MCP server, its log window Lua, its tools
  <other>.dll            anything else that needs C++; Lua mods use VMC hooks instead
```

The host finds plugins through the game's own mod system: each plugin mod inserts one row into a `DllPlugins` table (file name, host API version it was built against). At the point where VMC reads its own `CustomModOptions` table, the host reads `DllPlugins`, finds each file under the MODS folder, loads it in the order the Plugins screen saved, and runs the handshake below.

## Why VMC as the host base

VMC already is a hook-provider DLL: about 60 groups of Lua `GameEvents`, Lua API extensions, switchable bug fixes, and the `CustomModOptions` convention that Workshop mods already use. Starting from it means rules changes that only need a hook can be plain Lua mods from day one.

Terms (whoward69's usage page): parts may be incorporated into a greater work that has its own original additions, with credit; no resale or financial gain; derivatives must use their own GUID. No formal licence exists and nothing requires telling him. A courtesy post in his CivFanatics thread at the first release is optional.

VMC is built from the same 1.0.3.276 SDK source as the MCP DLL, with a VS2015 solution wrapping a vs2010 project. This repository builds with VS2008 through its own build script, modelled on the MCP mod's `build-dll.cmd`, and adds VMC's extra files to the project.

## Host design

### 1. Everything exported, layouts frozen

A plugin needs real access to players, units, cities, plots, deals, diplomacy, notifications and the globals (`GC`, `gDLL`). The host exports every engine class with one macro on the class declaration (`CIV_HOST_API`). Plugins link against the host's import library.

The numbers allow it: 325 classes and roughly 10,900 out-of-line functions, against a limit of 65,535 exports per DLL. The build prints the count.

What makes it safe: both sides are built by the same compiler with the shared C runtime (`/MD`) and the same compile flags, so objects, strings and vectors cross the boundary unchanged. The flags must be byte-identical (the map-drawing crash of v40 came from one mismatched define); the SDK ships a property sheet that pins them.

What makes it last: plugins compile the engine's headers into themselves, so field offsets, class sizes and vtable slots are baked into every plugin binary. From version one on, **class layouts and vtables never change**. New host-side state goes in side tables keyed by the object, never in the classes. VMC's compile-time switches are chosen once, compiled in, and toggled at runtime through the database as VMC already does.

### 2. Additive builds and the handshake

Every host build carries a host API version. A plugin records the API version it was built against. The rule: a host loads any plugin built against its own version or an earlier one. The host keeps that promise by only adding: new functions, new hook points, new side tables. Nothing shipped is removed, renamed or changed in meaning. If a break is ever unavoidable, the major version changes and older plugins are refused.

At load the host calls the plugin's single exported entry point:

```
extern "C" bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* plugin);
```

The plugin fills in its name, version and the API version it was built against. A plugin built for a newer host, or for an older major, is not loaded. The refusal is logged, shown on the Plugins screen beside the plugin, and shown as an in-game notification naming the plugin and the two versions. Never a silent skip.

Data shared between host and plugin can grow without breaking older plugins: the host creates the handshake structures itself, so new fields go at the end and an older plugin leaves them at zero. Anything a plugin creates and hands to the host starts with its own size.

### 3. Hooks: every function is a hook point

A hook is a list the host owns. At a hook point the host calls every plugin that registered there, in load order. Plugins never see each other: one failing, forgetting something or being removed cannot stop the others. The host can do this because it knows each hook's signature and wrote the loop.

**Generated hooks.** The build generates a typed wrapper for every function the host defines in a source file. Each wrapper:

1. runs every plugin registered **before** the function, in load order; a before-hook may veto, which skips the function and the remaining before-hooks;
2. runs the function, or the one plugin registered to **replace** it;
3. runs every plugin registered **after** the function, in reverse load order, handing each the result and letting it change it.

Replace is exclusive: a second replace on a function that already has one is refused at load, logged with both plugin names, and shown on the Plugins screen. Before and after stack without limit.

The generator reads the headers and writes one wrapper per function with that function's real signature. It runs as part of every host build. Functions written in headers stay inline and are not hook points; the SDK lists them.

Raw detouring is not used on host functions. It remains only for the closed executable, where the seat playback code already patches by pattern; that stays in the MCP plugin.

**Hand-placed hooks.** A function boundary is not every interesting spot. The MCP server needs a few mid-function points, listed below. These are ordinary hooks with declared signatures and a declared combination rule (first answer wins, or any veto blocks). Adding one later is additive.

| Today's engine edit | Becomes |
|---|---|
| `CvGame.cpp` turn loop: a seat is activated like the local player | query `IsPluginControlledPlayer(player)` |
| `CvDllPlayer::IsHuman`, `CvDllPreGame::isHuman` | query `EngineSeesAsHuman(player, default)` |
| `CvPlayer::setAlive` → keep the dead slot open | query `KeepDeadSlotOpen(player)` |
| `CvUnit::UnitPathTo` six cancellation sites | notify `UnitOrdersCancelled(unit, reason)` |
| `CvNotifications::Add` | notify `NotificationAdded(player, message, summary)` |
| popup sites (wonder, great person, city captured, goody, golden age, natural wonder, tech, era, barbarian camp, city-state greeting) | notify `PopupRaised(player/team, type, data…)` |
| `CvDiplomacyRequests` request and deal interception | query `InterceptDiploRequest(...)`, `InterceptDealRequest(...)` |
| `CvDealClasses` deal resolved | notify `DealResolved(...)` |
| `CvUnitMission` skip for seats | query `IsPluginControlledPlayer` (same as above) |
| `CvGame::update` → `ClaudeBridge::Tick()` | notify `GameCoreUpdate()` (VMC has one already) |
| `CvDllContext` shutdown, `DllMain` crash-handler removal | plugin `Shutdown()` lifecycle call |
| `CvLuaGame.cpp`: a dozen `Game.*` methods for the log window | `RegisterLuaMethods(lua_State*, table)` called when the host registers its own |

Rules fixes currently inside the DLL that are **not** MCP:

| Fix | Where it goes |
|---|---|
| captured cities keep their seen-by flags (`CvPlayer::acquireCity`) | host, as a VMC-style switch (`MOD_BUGFIX_...`), default on |
| seat starting units re-dealt as a human's | MCP plugin (it is about seats) |

### 4. Failure containment

C++ exceptions are off in the host and in plugins; this uses Windows structured exception handling, which works without them. Every call from a wrapper or a hand-placed hook into a plugin is guarded. When a plugin faults (access violation, divide by zero, illegal instruction):

- the host logs the plugin, the function and the stack, as the crash handler does today;
- the plugin is quarantined for the rest of the session: none of its hooks run again;
- an in-game notification names the plugin, says it was disabled for this session, and points to Mods > Plugins;
- the game keeps running.

Known limit: a plugin that faulted halfway through a replace has left the original unrun and the state possibly half-changed. That turn may be odd; it is still better than a crash to desktop, and the quarantine stops it recurring.

### 5. The Plugins screen

When the player presses Next on the Mods browser, the game activates the enabled mods and then shows the Mods menu. Files a mod imports into the VFS replace the game's UI files once mods are active, so the host ships its own copy of that menu with a **Plugins** button. The flow becomes Mods > Plugins > Single Player > Start Game.

The Plugins screen is front-end Lua. It lists the installed plugins by reading the `DllPlugins` rows from the activated database, lets the player move each up or down and skip it, and saves the order and skip flags through the game's per-mod persistent store (`Modding.OpenUserData`). The host reads the same store when it loads plugins. The screen also shows, beside each plugin, last session's failures, handshake refusals and replace conflicts, so the player can see what to move or disable without reading a log.

Load order is the list on the screen, top first.

### 6. Save games

The host's DLL GUID is what saves record. Plugins keep no state in saves today (seat labels live in the game's player nicknames); if one ever needs it, add a `SaveData(stream)`/`LoadData(stream)` pair keyed by plugin name. Not needed for the MCP plugin.

### 7. A plugin mod without the host

A plugin mod is an ordinary mod: a folder with the plugin DLL and one `DllPlugins` row. Without the host, the game runs whatever DLL is active, which never reads that row and never loads that file, so the plugin does nothing and harms nothing. Three layers keep a player from getting there by accident:

1. the plugin's Workshop page lists the host under Required Items;
2. the plugin's mod description declares a dependency on the host's mod ID, so the Mods browser greys out Enable until the host is enabled, with the reason in the tooltip (the game's own mechanism, already used for the expansion dependency);
3. the plugin's SQL creates the `DllPlugins` table if it is missing, so a hand-installed plugin with the dependency removed leaves no error in the database log.

All three are per-plugin, and the SDK template ships with them filled in; the host's ID is a constant.

## Plugin SDK

A folder shipped with each host release (also the thing other developers download):

- `include/` the host's headers (the engine's, with the export macro resolving to import, and private members made visible to plugin code, since a replacement copied from the host needs the access the original had);
- `include/CivHooks.h` the generated hook registration for every function, with the before/after/replace signatures;
- `lib/CivHost.lib` import library;
- `CivPlugin.vsprops` the exact compiler and linker settings of the host build;
- `api-version.h` the host API version;
- `inlined-functions.md` the functions written in headers, which are not hook points;
- `docs/` the generated reference and the guide (the same as the documentation site);
- `plugin-template/` a minimal plugin that registers one before-hook and one hand-placed hook and logs a line;
- `plugin-template/` also carries the mod description with the host dependency declared and the SQL that creates the `DllPlugins` table if missing and inserts the plugin's row;
- `README.md` how to build, how the mod folder must look, how the `DllPlugins` row is written, how a refusal shows up, and the rule of thumb: use a hand-placed hook if one fits, a generated before/after hook otherwise, a replace only when you must, and ask for a hand-placed hook when you find yourself replacing a function other plugins would also want.

## Developer documentation

Plugin authors should not have to read the engine source to find where to hook. The documentation has two parts.

**Generated reference.** The hook generator already reads every function's signature, so it also writes a reference page for each function: its class and file, its signature, the before, after and replace hook signatures, and whether it is a hook point at all. Functions written in headers are marked as not hookable, with a pointer to their callers. Doxygen, run over the engine source as it stands, adds the list of functions that call each one (which tells a developer when a hook fires), search, cross-links, and any comments Firaxis left. Each page also lists the VMC Lua events fired inside that function, found by scanning function bodies for VMC's event calls, so a developer can see when a Lua mod would be enough.

**Written by hand.**

- a description of each hand-placed hook, written when the hook is added;
- a task-based guide as the front page: common goals ("change combat odds", "react to a city being captured"), each pointing to the hooks that serve it; it starts with the common needs and grows over time;
- a short summary of each main class (player, city, unit, plot, deals, diplomacy): what it owns and where to look.

Functions are not described in bulk; a function with no hand-written description shows only its generated facts. Because function meanings are frozen, hand-written descriptions never go out of date.

The documentation ships in the SDK and on a GitHub Pages site for each release.

## The MCP plugin

`Claude/` (37 files, ~11,800 lines), today part of the Local MCP Server mod in the civ5-mods repository, moves to a new repository of its own and becomes `MCPServer.dll`, a plugin mod. It never comes into this repository. Internally almost nothing changes: the HTTP server, tools, bridge, seat logic, map drawing, playback release and crash handler are already self-contained. The work is:

1. replace each engine edit with a hook registration from the table above;
2. move the `CvLuaGame.cpp` methods into the plugin and register them through `RegisterLuaMethods`;
3. keep the no-PCH drawing file's two defines in line with the SDK property sheet;
4. package: `MCPServer.dll` under `plugins/`, `LLMLog.lua/.xml`, the `DllPlugins` XML row, the log window's UI entry point, the mod description;
5. rename everything named Claude (the folder, files, classes, log names and on-screen text) to neutral names, since the plugin works with any AI model.

The seat/playback code pokes the game executable's memory by pattern scan; that stays in the plugin and needs nothing from the host.

## Versioning and releases

- Host releases on GitHub, tagged, each with its SDK zip and API version. A Workshop host is fine, because an updated host keeps loading older plugins; the Workshop page points to GitHub for the SDK.
- A plugin release names the API version it was built against. The handshake catches mismatches.
- Host builds only add. Layouts, vtables, hook signatures and function meanings are frozen; a major version change is the one exception and refuses older plugins.

## Phases

**P0 — proof of concept (days to two weeks).** In this repository, against the plain Firaxis source, before touching VMC. The first step imports the SDK source unchanged and adds a build script. P0's edits to engine files stay on a separate branch, so the main branch holds the Firaxis source unchanged until VMC is copied over it in P1; anything worth keeping, such as the generator and the build script, moves to the main branch. The rest:
- export every class with the macro; build; read the export count;
- write the generator and run it over the whole codebase; the exit is a clean build with every wrapper in place, which flushes out the awkward signatures (overloads, templates, default arguments, operators, the variadic random-number functions);
- time an AI turn on the plain build and on the wrapped build, with Visual C++ 2008 and with Clang against the same 2008 binary interface (the Community Patch builds that way), and record the four numbers;
- a toy plugin that reads a player's gold through the exports, registers a before-hook and an after-hook on one function, and replaces another; a second toy plugin that replaces the same function and is refused;
- a toy plugin that faults inside a hook: the game keeps running, the notification names it, the plugin is quarantined;
- a handshake with a deliberately newer API version to see the refusal path;
- confirm strings and vectors cross the boundary (allocate in one DLL, free in the other);
- replace the Mods menu through the VFS and confirm the Plugins button shows after activation;
- write an order from front-end Lua through the user data store and read it back from the DLL at load;
- enable the toy plugin mod with the host mod disabled and see the Mods browser refuse it; then remove the dependency, start a vanilla game with the plugin mod enabled, and see the plugin do nothing and the database log stay clean.
Exit: every item above seen working in a real game, and the timing numbers in this document.

**P1 — the host.** Copy VMC v97 over the Firaxis source in its own commit (own GUID, credits), add the loader, the generator to the build (writing the hook wrappers and the generated reference), the exports, the hand-placed hook set above, failure containment, the Plugins screen, and the acquireCity fix as a switch. Freeze the layouts. Exit: the host builds, loads a game, VMC's events fire, the Plugins screen orders two toy plugins, no MCP code inside.

**P2 — MCP as a plugin.** Move `Claude/` from civ5-mods into the plugin's own repository, wire hooks, Lua registration, packaging. Exit: every existing tool and the log window work exactly as in v47, verified by playing a few turns with a model and reloading a save.

**P3 — the rest.** Explorer fix, friendship/denounce rules and calmer AI as Lua mods on VMC hooks where one exists, native plugins where not; the calmer-AI fix is the natural first replace plugin, since it replaces one diplomacy function. A plugin-writing guide, the task-based guide, the class summaries, and the documentation site. First GitHub release of the host and SDK from this repository and of the MCP plugin from its own, and the Workshop pages.

## Risks

- **Speed.** Every wrapped function is a real call plus a listener check, and nothing wrapped can be inlined. The hot paths call small functions millions of times a turn. P0 measures it on both compilers before anything is committed; the fallback is the same generator on a chosen subset.
- **The generator's long tail.** A few hundred odd signatures could cost more than the rest together. P0 runs it over everything for that reason.
- **The layout freeze is a discipline, not a mechanism.** One added field breaks every plugin. The build compares the exported layouts against the version one record and fails on any change.
- **Header functions are not hook points.** Listed in the SDK; a plugin that needs one replaces the caller instead.
- **No isolation beyond containment.** A faulting plugin is caught and quarantined, but a plugin that corrupts state without faulting is not detectable.
- **Wrap order.** Two plugins hooking one function in an order that matters is not detectable. The Plugins screen makes order visible and the player's to set; that is the whole answer.
- **Export count.** Watch the 65,535 limit; print the count in the build.
- **Load timing.** Plugins must load after the database is ready and before the first turn; the point where VMC reads its options is the candidate. P0 tests the same moment in the plain Firaxis source, and P1 confirms it in VMC.
- **Lua registration.** The host registers Lua methods per context; the plugin's registration must run for each new context the same way. Verify in P2.
- **VMC behaviour changes.** VMC's bug fixes and features are switches; the host ships with the same defaults VMC does, and our own settings are a separate decision.

## Not in scope

- Stacking with other replacement DLLs (Community Patch etc.). Nothing can do that. If the Community Patch ever adopts the loader, that is their build of it.
- Multiplayer. Every machine in a multiplayer game must run identical code in the same order, which the host cannot guarantee for plugins: each player's plugin order and crash quarantine are local to their machine. The MCP server also controls seats from one machine. VMC itself is untested in multiplayer: its author does not play it, and known multiplayer bugs were left to community forks.
- A plugin registry or version-matching service. The API version and the handshake are enough.
