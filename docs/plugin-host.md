# Bazaar Multi-DLL Mod Loader: one DLL, many plugin DLLs

Status: planned 2026-10-19, reworked 2026-10-21. P0, the proof of concept, was finished on 2026-10-22: the generator, the hooked host, plugin loading and unloading and crash handling all work in the game with small test plugins. P1 is under way on the p1 branch: VMC is in, the engine calls are back, the Plugins screen lists, reorders and skips plugins, and the hand-placed hooks are in. The rest of P1 is not built yet. Anything else in this document is a plan unless a section says otherwise.

## Goal

The game loads exactly one rules DLL. Today that DLL is the Local MCP Server mod, so every other change to the game's rules (city-state explorer fix, friendship rules, calmer AI) either goes into the MCP mod or does not exist. That mixes mods of different intent in one binary and makes it impossible for anyone else to add their own.

The goal is one **host DLL** that loads any number of **plugin DLLs**, each its own Workshop mod with its own intent:

- the MCP server is a plugin, not part of the host;
- rules changes and bug fixes are their own plugins (or plain Lua mods on the host's hooks); the host adds none of its own beyond what VMC already carries;
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

Bazaar - VMC Bootstrap (required)  (a mod of its own: whoward69's database, text, Lua and art files, no DLL)
  VMC's mod ID, so mods made for VMC load after it; the host depends on it

Plugin DLLs  (ordinary mods: one folder each, with <Name>.dll at its top level)
  MCPServer.dll          the MCP server, its log window Lua, its tools
  <other>.dll            anything else that needs C++; Lua mods use VMC hooks instead
```

The host finds plugins through the game's own mod system: each plugin mod inserts one row, its file name, into a `DllPlugins` table, which the host's own mod creates. At the point where VMC reads its own `CustomModOptions` table, the host reads `DllPlugins`, finds each file under the MODS folder, loads it in the order the Plugins screen saved, and runs the handshake below.

## Why VMC as the host base

VMC already is a hook-provider DLL: about 60 groups of Lua `GameEvents`, Lua API extensions, switchable bug fixes, and the `CustomModOptions` convention that Workshop mods already use. Starting from it means rules changes that only need a hook can be plain Lua mods from day one.

Terms: VMC is used under whoward69's terms: it is never sold or used to make money.

VMC is built from the same 1.0.3.276 SDK source as the MCP DLL, with a VS2015 solution wrapping a vs2010 project. This repository builds with VS2008 through its own build script, modelled on the MCP mod's `build-dll.cmd`, and adds VMC's extra files to the project.

Mods made for VMC list VMC's mod ID as a reference, so that the game switches them on after VMC's database files. The game switches on mods with no live reference or dependency first, in the order of their folder names, and only then the mods that have one; a reference to a mod that is not switched on counts for nothing. So VMC's files ship as a mod of their own, Bazaar - VMC Bootstrap (required), under VMC's mod ID, and the host depends on it: mods made for VMC then load after VMC's files, and a mod that requires VMC can be switched on. It holds no DLL; the host DLL is the one that runs. The Workshop allows one mod per item, so it is a second item, listed under Required Items on the host's page, and Steam offers it to anyone who subscribes to the host. It counts as affecting saved games, because loading a save applies the database changes of only the mods the save lists.

## Host design

### 1. Everything exported, layouts frozen

A plugin needs real access to players, units, cities, plots, deals, diplomacy, notifications and the globals (`GC`, `gDLL`). The host exports every engine function defined in a source file, except templates and functions private to one file, and every global or static member variable a header declares, such as `gGlobals` behind `GC` and `CvPlayerAI::m_aPlayers` behind `GET_PLAYER`. The build marks each one in its generated copy of the engine, so the committed engine files stay untouched; marking whole classes instead would make the compiler build member functions the game never uses, and some of those do not compile. Plugins link against the host's import library.

The numbers allow it: the host built from the Firaxis source exports about 14,500 functions (counted 2026-10-22), against a limit of 65,535 exports per DLL. The build prints the count.

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

1. runs every plugin registered **before** the function, in load order; a before-hook may veto, which skips the function, its replacement and the remaining before-hooks. A function that returns a value then returns what the vetoing hook set, or 0, false or empty if it set nothing; a function that returns a reference runs anyway, since there is no empty reference;
2. runs the function, or the one plugin registered to **replace** it;
3. runs every plugin registered **after** the function, in reverse load order, handing each the result and letting it change it. This happens after a veto too.

Replace is exclusive: only one plugin can replace a function. When two plugins replace the same one, the plugin lower in the load order is not loaded at all, because its other hooks may depend on the replacement it lost. The log and the Plugins screen name both plugins, and moving the lower one above the other swaps which one runs. Before and after stack without limit. A replacement receives the original function as its first argument, so it can run the engine's own version and adjust around it, or ignore it and do the whole job itself.

Each hook has a number from a committed list, tools/generator/hook-ids.txt. A number always means the same function, and new functions only add numbers at the end, so a plugin built against an older host keeps working on a newer one. If a function's parameters change, it gets a new number, because a plugin written for the old parameters would break.

The generator reads the headers and writes one wrapper per function with that function's real signature. It runs as part of every host build. Functions written in headers stay inline and are not hook points; the documentation lists them.

Raw detouring is not used on host functions. It remains only for the closed executable, where the seat playback code already patches by pattern; that stays in the MCP plugin.

**Hand-placed hooks.** A function boundary is not every interesting spot. Where the MCP server needs a spot inside a function, the engine source calls the host there, and plugins register for the spot by its number. Each has a fixed signature and one of two rules: a question stops at the first plugin that answers yes, and an announcement reaches every plugin that registered. Numbers only grow at the end, so adding one later is additive. Where the MCP server's change sits at the start or end of a function, a generated hook on that function does the job instead. sdk/hand-placed-hooks.md describes each one.

| Today's engine edit | Becomes |
|---|---|
| `CvGame.cpp` turn loop and `CvUnitMission` advisor warning: a seat is treated like the local player | question `IsPluginControlledPlayer(player)` |
| `CvDllPlayer::IsHuman`, `CvDllPreGame::isHuman` | generated after-hooks on both |
| `CvPlayer::setAlive` → keep the dead slot open | question `KeepDeadSlotOpen(player)` |
| `CvUnit::UnitPathTo` six cancellation sites and `CvUnit::setPromotionReady` | announcement `UnitOrdersCancelled(unit, reason)`, with a reason number in place of the MCP server's text |
| `CvNotifications::Add` | announcement `NotificationAdded(player, type, message, summary, x, y, data1, data2)` |
| popup sites (wonder, great person, city captured, goody, golden age, natural wonder, tech, era, barbarian camp, city-state greeting) | announcement `PopupRaised(player, type, data1, data2, data3, option1, option2, text)` |
| `CvDiplomacyRequests` request and deal interception | generated before-hooks on both versions of `SendRequest` and `SendDealRequest`, which can veto |
| deal resolved (`CvDealClasses` in the MCP server's DLL, `CvDllNetMessageHandler` in VMC) | announcement `DealResolved(from, to, actingPlayer, accepted, finalized)` |
| `CvGame::update` → `ClaudeBridge::Tick()` | generated before-hook on `CvGame::update` |
| `CvDllContext` shutdown, `DllMain` crash-handler removal | plugin `Shutdown()` lifecycle call |
| `CvLuaGame.cpp`: a dozen `Game.*` methods for the log window | generated after-hook on `CvLuaGame::RegisterMembers`, which can add methods to the `Game` table |

**Replacements and the hooks inside them.** A replacement that does not call the original skips everything the original would have done: the hand-placed hooks inside it, and the hooks on every function it would have called. Replacing stays allowed, because turning an existing DLL mod into a plugin and fixing a bug inside a function both need it, and a veto skips the original in the same way. Instead, the host makes the skipping visible:

- When one plugin replaces a function that contains a hand-placed hook another plugin uses, the host treats it as a possible conflict. The plugin that loads second is held back, and the log and the Plugins screen say why. The Plugins screen offers a Use both anyway checkbox for that plugin, for when the replacement is known to run the original, and saves the choice with the load order. The build finds which functions contain each hand-placed hook by reading the engine source. Vetoes are not checked: a before-hook decides to veto only while the game runs.
- The first time a replacement returns without calling the original, the host writes one line to its log naming the plugin and the function, so a developer looking for a hook that did not fire knows where to start.

Rules fixes currently inside the DLL that are **not** MCP:

| Fix | Where it goes |
|---|---|
| captured cities keep their seen-by flags (`CvPlayer::acquireCity`) | its own plugin |
| seat starting units re-dealt as a human's | MCP plugin (it is about seats) |

### 4. Failure containment

C++ exceptions are on, as in Firaxis's project, because the engine's own code uses them. Nothing here relies on them: crash protection uses Windows structured exception handling, and a C++ exception that escapes a plugin is caught like any other crash. Every call from a wrapper or a hand-placed hook into a plugin is guarded. When a plugin faults (access violation, divide by zero, illegal instruction):

- the host logs the plugin and the function; the call stack, as the MCP mod's crash handler logs it today, comes in P1;
- the plugin is quarantined until the player returns to the main menu: none of its hooks run again. There the host calls its shutdown function and unloads it like any other plugin, so a fixed version can be dropped in before a game is started or loaded;
- an in-game notification names the plugin, says it is off until the player returns to the main menu, warns that the game may now be unstable and that any save should go to a new slot, and says the details are in Logs\Bazaar.log. A pop-up in the middle of the screen is planned instead (issue #4);
- the game keeps running.

Before unloading any plugin, the host checks that none of its threads is still running inside its DLL. A plugin that left one running, or whose shutdown function crashed, stays in memory and is refused until Civilization V restarts, because unloading it could crash the game.

Known limit: a plugin that faulted halfway through a replace may already have changed some state, and the original then runs on top of it. That turn may be odd; it is still better than a crash to desktop, and the quarantine stops it recurring.

### 5. The Plugins screen

When the player presses Next on the Mods browser, the game switches on the enabled mods and the host loads the plugins. A mod cannot add the Plugins screen to the screens that follow: the game builds them at startup, before any mod is on, and files a mod imports only replace screens the game builds later, the first time they open. On the way to starting a game, Advanced Setup is the only such screen. So the Plugins screen takes its place: Mods > Single Player > Set Up Game > Advanced Setup opens the Plugins screen, and its Continue button opens the Advanced Setup screen it replaced.

When two mods import files with the same name, the one the game switches on later wins. The host mod lists Really Advanced Setup as a reference, which makes the game switch the host on after it, so the host's screen wins over that mod's. Another mod that replaces Advanced Setup and is switched on after the host would win instead, and its screen would show in place of the Plugins screen; such a mod gets added to the references once it is known. The plugins still load in the saved order either way. The game also finds screens by file name, so the screen the host replaced cannot be opened under its own name. Continue asks the host's DLL to copy it, from the last active mod that imports it or else from the game, into the host mod's folder under a name of its own, and opens the copy. Nothing in the other mod is changed.

The Plugins screen is front-end Lua. After loading the plugins, the host writes a `BazaarPlugins` table with one row per plugin (its file, name, version, a status, its problems, whether it failed or was skipped, the plugins it may conflict with, and the ones the player chose to use it with anyway), and the screen lists those rows. Handshake refusals, replace conflicts and crashes show beside the plugin, so the player can see what to move or skip without reading a log; possible conflicts with hand-placed hooks show there too, with a Use both anyway checkbox. Arrows move a plugin up or down, and a checkbox skips it without turning off its mod. Once anything has changed, a Reload Plugins button appears. Reload, Back and Continue all send the new order to the host, which saves it, with the Use both anyway choices, to `ModUserData\Bazaar plugin order.txt`, reloads the plugins and rewrites the table. The host reads that file whenever it loads plugins.

Front-end Lua cannot call the DLL's own Lua functions, because the game only gives those to Lua running in a game. The screen reaches the host through `UI.GetMapPreview`, a front-end call the game passes straight to the DLL: the host answers names that start with `bazaar:` itself and passes every other call to the game's own code.

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

A folder shipped with each host release (also the thing other developers download), laid out by `sdk/build_sdk.py`:

- `include/` the engine's headers as the host was built from them, with the export marker resolving to import, the Firaxis headers they include, `CivPluginApi.h` (the handshake, the API version and the hand-placed hooks) and `CivHooks.h` (every hook's number, with the function's signature as a comment; typed declarations are issue #10);
- `lib/` the host's import library, `CvGameCore_Expansion2.lib`, and the Firaxis libraries;
- `CivPlugin.vsprops` the compiler and linker settings of the host build, with paths through the `BAZAAR_SDK` environment variable;
- `README.md`, the plugin-writing guide (sdk/README.md), and `hand-placed-hooks.md`;
- `plugin-template/` a minimal plugin with one before-hook, one hand-placed hook and one Lua method: its VS2008 project, its ModBuddy project declaring the dependency on the host, the SQL that creates the `DllPlugins` table if missing and adds its row, and a `build.cmd` that builds the DLL, the mod folder and the Workshop package.

Not in it yet: plugins cannot reach private and protected members, because the compiler names private functions differently from public ones, so the host would need to export them under their public names too. The list of functions written in headers and the generated reference come with the documentation site.

## Developer documentation

Plugin authors should not have to read the engine source to find where to hook. The documentation is a site of plain web pages, built from the engine source and a few hand-written files. It has two parts.

**Generated reference.** A docs step of its own, run by hand or when making a release but not on every build, uses the generator's reading of the engine to write one page per function. Each page shows:

- the function's full code as Firaxis and VMC wrote it, so a developer sees what a replacement takes over. Pygments, a standard code-highlighting library, colours it when the pages are built, and parts that this build leaves out behind an `#if` are greyed out;
- its class and file, its signature, and the before, after and replace hook signatures, or why it is not a hook point;
- the functions it calls and the functions that call it, which tells a developer when a hook fires. Each call in the code links to the called function's page. A call to a virtual function links to the base version, whose page lists the classes that override it. Calls through function pointers, from Lua or from the game's own program cannot be seen;
- the VMC Lua events fired inside it, so a developer can see when a Lua mod would be enough;
- the hand-placed hooks inside it, with the lines where they fire marked, and a reminder that a replacement that does not run the original stops them;
- the release it was added in, and any releases its code changed in.

Functions written in headers are not hook points; each gets a page saying so, with its callers.

The pages form one tree: folder, file, class, function. Every class sits in one file, and a function outside any class sits directly under its file. Each page shows its place in the tree as a fixed trail of links, and each folder, file and class has a page listing what is in it. A search box reads a generated list of every name.

Each hand-placed hook gets a page too: its section of sdk/hand-placed-hooks.md, plus every place in the engine that calls it. One page lists them all.

**Versions.** At each release, the docs step takes a fingerprint of every function's code, ignoring spaces and comments, and compares it with the list saved at the previous release in `tools/generator/function-history.txt`. The list also records which hand-placed hooks each function contains. A function not on the list is marked as added in this release. A function whose fingerprint changed is marked as changed in it; the mark names any hand-placed hook that was added and links to GitHub's line-by-line history of the function at that release. Then the step saves the new list. Only a release updates the list, so unreleased work is never marked; the first release is the starting point and marks nothing. Bazaar adds no fixes, so an engine function rarely changes, and usually only because a hand-placed hook went into it. That is the change a developer most needs to see, because a replacement copied from an older release would stop the new hook.

**Written by hand.**

- a description of each hand-placed hook in sdk/hand-placed-hooks.md, written when the hook is added;
- a task-based guide as the front page: common goals ("change combat odds", "react to a city being captured"), each pointing to the hooks that serve it; it starts with the common needs and grows over time;
- a short summary of each main class (player, city, unit, plot, deals, diplomacy): what it owns and where to look.

Functions are not described in bulk; a function with no hand-written description shows only its generated facts. Because function meanings are frozen, hand-written descriptions never go out of date.

**Where it is built and published.** The generator needs Visual C++ 2008's header files to read the engine, and GitHub's build machines do not have them. So the docs are built on the developer's machine when making a release, and go into the SDK zip attached to the GitHub release. A GitHub Action then takes the docs out of that zip and publishes them on the project's GitHub Pages site; no generated page is committed to the repository. The site shows the latest release, and each SDK zip carries the docs for its own release. Because host builds only add, the latest docs also hold for plugins built against older releases. Every page shows Firaxis's copyright line and links to NOTICE, since it shows their code. The GitHub wiki is not used: it takes only Markdown, cannot run the site's own styles or search, and has no build step.

## The MCP plugin

`Claude/` (37 files, ~11,800 lines, counted 2026-10-21), today part of the Local MCP Server mod in the civ5-mods repository, moves to a new repository of its own and becomes `MCPServer.dll`, a plugin mod. It never comes into this repository. Internally almost nothing changes: the HTTP server, tools, bridge, seat logic, map drawing, playback release and crash handler are already self-contained. The work is:

1. replace each engine edit with a hook registration from the table above;
2. move the `CvLuaGame.cpp` methods into the plugin and add them to the `Game` table from an after-hook on `CvLuaGame::RegisterMembers`, as the template's `AfterRegisterGame` does;
3. keep the no-PCH drawing file on the SDK property sheet's `_SECURE_SCL=0` and `_HAS_ITERATOR_DEBUGGING=0`, which the sheet sets for every file; the file must not override them;
4. package: `MCPServer.dll` at the mod folder's top level, `LLMLog.lua/.xml`, the SQL that adds its `DllPlugins` row, the log window's UI entry point, the mod description;
5. rename everything named Claude (the folder, files, classes, log names and on-screen text) to neutral names, since the plugin works with any AI model.

The seat/playback code pokes the game executable's memory by pattern scan; that stays in the plugin and needs nothing from the host.

## Versioning and releases

- Host releases on GitHub, tagged, each with its SDK zip and API version. A Workshop host is fine, because an updated host keeps loading older plugins; the Workshop page points to GitHub for the SDK.
- A plugin release names the API version it was built against. The handshake catches mismatches.
- Host builds only add. Layouts, vtables, hook signatures and function meanings are frozen; a major version change is the one exception and refuses older plugins.

## Phases

**P0 — proof of concept (days to two weeks).** In this repository, against the plain Firaxis source, before touching VMC. The first step imports the SDK source unchanged and adds a build script. P0's edits to engine files stay on a separate branch, so the main branch holds the Firaxis source unchanged until VMC is copied over it in P1; anything worth keeping, such as the generator and the build script, moves to the main branch. The rest:
- export every engine function from the generated copy; build; read the export count;
- write the generator and run it over the whole codebase; the exit is a clean build with every wrapper in place, which flushes out the awkward signatures (overloads, templates, default arguments, operators, the variadic random-number functions);
- time an AI turn on the plain build and on the wrapped build, with Visual C++ 2008 and with Clang against the same 2008 binary interface (the Community Patch builds that way), and record the four numbers;
- a toy plugin that reads a player's gold through the exports, registers a before-hook and an after-hook on one function, and replaces another; a second toy plugin that replaces the same function and is refused;
- a toy plugin that faults inside a hook: the game keeps running, the notification names it, the plugin is quarantined;
- a handshake with a deliberately newer API version to see the refusal path;
- confirm strings and vectors cross the boundary (allocate in one DLL, free in the other);
- replace the Mods menu through the VFS and confirm the Plugins button shows after activation (not possible: the game builds the Mods menu before any mod is on; see section 5);
- write an order from front-end Lua through the user data store and read it back from the DLL at load (replaced in P1: the DLL saves the order itself; see section 5);
- enable the toy plugin mod with the host mod disabled and see the Mods browser refuse it; then remove the dependency, start a vanilla game with the plugin mod enabled, and see the plugin do nothing and the database log stay clean.
Exit: every item above seen working in a real game, and the timing numbers in this document.

**P1 — the host.** Copy VMC v97 over the Firaxis source in its own commit (own GUID, credits), add the loader, the generator to the build (writing the hook wrappers), the docs step (writing the generated reference), the exports, the hand-placed hook set above, failure containment and the Plugins screen. Freeze the layouts. Exit: the host builds, loads a game, VMC's events fire, the Plugins screen orders two toy plugins, no MCP code inside.

**P2 — MCP as a plugin.** Move `Claude/` from civ5-mods into the plugin's own repository, wire hooks, Lua registration, packaging. Exit: every existing tool and the log window work exactly as in v47, verified by playing a few turns with a model and reloading a save.

**P3 — the rest.** Explorer fix, captured-city seen-by fix, friendship/denounce rules and calmer AI as Lua mods on VMC hooks where one exists, native plugins where not; the calmer-AI fix is the natural first replace plugin, since it replaces one diplomacy function. The task-based guide, the class summaries, and the documentation site. First GitHub release of the host and SDK from this repository and of the MCP plugin from its own, and the Workshop pages.

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
