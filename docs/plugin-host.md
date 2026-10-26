# Bazaar Multi-DLL Mod Loader: one DLL, many plugin DLLs

Status: planned 2026-10-19, reworked 2026-10-21. P0, the proof of concept, was finished on 2026-10-22: the generator, the hooked host, plugin loading and unloading and crash handling all work in the game with small test plugins. P1 is under way on the p1 branch: VMC is in, the engine calls are back, the Plugins screen lists, reorders and skips plugins, and the hand-placed hooks are in. The rest of P1 is not built yet. Anything else in this document is a plan unless a section says otherwise.

## Goal

The game loads exactly one rules DLL. Today that DLL is the Local MCP Server mod, so every other change to the game's rules (city-state explorer fix, friendship rules, calmer AI) either goes into the MCP mod or does not exist. That mixes mods of different intent in one binary and makes it impossible for anyone else to add their own.

The goal is one **host DLL** that loads any number of **plugin DLLs**, each its own Workshop mod with its own intent:

- the MCP server is a plugin, not part of the host;
- rules changes and bug fixes are their own plugins (or plain Lua mods on the host's hooks); the host adds none of its own beyond what VMC already carries, and adds to the engine only hand-placed hooks and read-only accessors for state a plugin cannot otherwise reach;
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

What makes it last: plugins compile the engine's headers into themselves, so field offsets, class sizes and vtable slots are baked into every plugin binary. From 1.0 on, **class layouts and vtables never change**. New host-side state goes in side tables keyed by the object, never in the classes. VMC's compile-time switches are chosen once, compiled in, and toggled at runtime through the database as VMC already does.

### 2. Additive builds and the handshake

Every host build carries a host API version. A plugin records the API version it was built against. The rule: a host loads any plugin built against its own version or an earlier one. The host keeps that promise by only adding: new functions, new hook points, new side tables. Nothing shipped is removed, renamed or changed in meaning. From 1.0 on, if a break is ever unavoidable, the major version changes and older plugins are refused. Before 1.0 a build may break the promise if it must; every plugin is then rebuilt against it.

Each plugin exports the API version it was built against as data, which the template declares in one line. Before loading a plugin, the host reads that version from the file without running any of the plugin's code. A plugin built for a newer host, or for an older major, is not loaded. The refusal is logged, shown on the Plugins screen beside the plugin, and shown as an in-game notification naming the plugin and the two versions. Never a silent skip. Because the host decides before any plugin code runs, a plugin never checks the version itself, and a plugin that uses functions an older host lacks gets the same refusal instead of a Windows load error.

Then the host loads the plugin and calls its single exported entry point:

```
extern "C" bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* plugin);
```

The plugin fills in its name and version and registers its hooks.

Data shared between host and plugin can grow without breaking older plugins: the host creates the handshake structures itself, so new fields go at the end and an older plugin leaves them at zero. Anything a plugin creates and hands to the host starts with its own size.

### 3. Hooks: every function is a hook point

A hook is a list the host owns. At a hook point the host calls every plugin that registered there, in load order. Plugins never see each other: one failing, forgetting something or being removed cannot stop the others. The host can do this because it knows each hook's signature and wrote the loop.

**Generated hooks.** The build generates a typed wrapper for every function the host defines in a source file. Each wrapper:

1. runs every plugin registered **before** the function, in load order; a before-hook may veto, which skips the function, its replacement and the remaining before-hooks. A function that returns a value then returns what the vetoing hook set, or 0, false or empty if it set nothing; a function that returns a reference runs anyway, since there is no empty reference;
2. runs the function, or the one plugin registered to **replace** it;
3. runs every plugin registered **after** the function, in reverse load order, handing each the result and letting it change it. This happens after a veto too.

Replace is exclusive: only one plugin can replace a function. When two plugins replace the same one, the plugin lower in the load order is not loaded at all, because its other hooks may depend on the replacement it lost. The log and the Plugins screen name both plugins, and moving the lower one above the other swaps which one runs. Before and after stack without limit. A replacement receives the original function as its first argument, so it can run the engine's own version and adjust around it, or ignore it and do the whole job itself.

Each hook has a number from a committed list, tools/generator/hook-ids.txt. A number always means the same function, and new functions only add numbers at the end, so a plugin built against an older host keeps working on a newer one. If a function's parameters, its return type or whether it is static change, it gets a new number, because a plugin written for the old function would break. A plugin's request for a number whose function has gone is refused, and the log says to rebuild the plugin. The SDK no longer names that number, so a rebuild stops where the plugin uses it.

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

- the host logs the plugin, the function, what memory the fault touched and the call stack;
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
- `plugin-template/` a minimal plugin with one before-hook, one hand-placed hook and one Lua method: its VS2008 project, its ModBuddy project declaring the dependency on the host, the SQL that creates the `DllPlugins` table if missing and adds its row, a `build.cmd` that builds the DLL, the mod folder and the Workshop package, and a `release.cmd` that makes its releases, with its `VERSION`, `CHANGES.txt` and Workshop description (see Releasing a plugin or Lua mod).

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

**Versions.** At each release, the docs step takes a fingerprint of every function's code, ignoring spaces and comments, and compares it with the list saved at the previous release in `tools/generator/function-history.txt`. The list also records which hand-placed hooks each function contains. A function not on the list is marked as added in this release. A function whose fingerprint changed is marked as changed in it; the mark names any hand-placed hook that was added and links to GitHub's line-by-line history of the function at that release. Then the step saves the new list, which keeps, for each function, the release it was added in and every release its code changed in. So a page keeps the marks of earlier releases, and building the same release again gives the same marks. Only a release updates the list, so unreleased work is never marked; the first release is the starting point and marks nothing. Bazaar adds no fixes, so an engine function rarely changes, and usually only because a hand-placed hook went into it. That is the change a developer most needs to see, because a replacement copied from an older release would stop the new hook.

**Written by hand.**

- a description of each hand-placed hook in sdk/hand-placed-hooks.md, written when the hook is added;
- a task-based guide as the front page: common goals ("change combat odds", "react to a city being captured"), each pointing to the hooks that serve it; it starts with the common needs and grows over time;
- a short summary of each main class (player, city, unit, plot, deals, diplomacy): what it owns and where to look;
- notes on single functions in docs/function-notes.md, shown on the function's page, where a developer needs something its generated facts do not say.

Functions are not described in bulk; a function with no hand-written description shows only its generated facts. Because function meanings are frozen, hand-written descriptions never go out of date.

**Where it is built and published.** The generator needs Visual C++ 2008's header files to read the engine, and GitHub's build machines do not have them. So the docs are built on the developer's machine when making a release, and attached to the GitHub release as a zip of their own, so a Lua modder can get them without the SDK. A GitHub Action then takes the site out of that zip and publishes it on the project's GitHub Pages site; no generated page is committed to the repository. The site shows the latest release, and each docs zip holds the docs for its own release. Because host builds only add, the latest docs also hold for plugins built against older releases. Every page shows Firaxis's copyright line and links to NOTICE, since it shows their code. The GitHub wiki is not used: it takes only Markdown, cannot run the site's own styles or search, and has no build step.

**A copy for coding models.** The docs step also writes every page as Markdown, in the same tree, and the docs zip holds both. The HTML pages wrap the code in markup for its colours and links, which a model has to read past; the Markdown is nearly all content. The whole reference is far too big for a model to read at once, so the copy is meant as a folder a coding agent searches: the engine's code with the callers, hooks and history already worked out. Both copies come from one outline of each page, written out once as HTML and once as Markdown, so they always say the same thing.

## The MCP plugin

`Claude/` (37 files, ~11,800 lines, counted 2026-10-21), today part of the Local MCP Server mod in the civ5-mods repository, moves to a new repository of its own and becomes `MCPServer.dll`, a plugin mod. It never comes into this repository. Internally almost nothing changes: the HTTP server, tools, bridge, seat logic, map drawing, playback release and crash handler are already self-contained. The work is:

1. replace each engine edit with a hook registration from the table above;
2. move the `CvLuaGame.cpp` methods into the plugin and add them to the `Game` table from an after-hook on `CvLuaGame::RegisterMembers`, as the template's `AfterRegisterGame` does;
3. keep the no-PCH drawing file on the SDK property sheet's `_SECURE_SCL=0` and `_HAS_ITERATOR_DEBUGGING=0`, which the sheet sets for every file; the file must not override them;
4. package: `MCPServer.dll` at the mod folder's top level, `LLMLog.lua/.xml`, the SQL that adds its `DllPlugins` row, the log window's UI entry point, the mod description;
5. rename everything named Claude (the folder, files, classes, log names and on-screen text) to neutral names, since the plugin works with any AI model.

The seat/playback code pokes the game executable's memory by pattern scan; that stays in the plugin and needs nothing from the host.

## Versioning and releases

- Releases use semantic versioning: three numbers, major.minor.patch, such as 1.2.0. The first two are the API version. The minor number goes up when a release adds to the API, the patch number when a release only fixes things, and the major number only for a break. Each release is tagged with its version, such as `v1.2.0`, and published on GitHub with its packages, SDK and docs, as described under Making a release. A Workshop host is fine, because an updated host keeps loading older plugins; the Workshop page points to GitHub for the SDK.
- 1.0 is the first public release. Builds before it are numbered 0.x and may break plugins if they must. We avoid that, and when it happens, every plugin we have is rebuilt against the new build.
- A plugin release names the API version it was built against. The handshake catches mismatches.
- From 1.0 on, host builds only add. Layouts, vtables, hook numbers and signatures, and function meanings are frozen; a major version change is the one exception and refuses older plugins.

### Making a release

A release is made on the developer's machine, because the host, the SDK and the docs all need Visual C++ 2008. A script, `tools/release.py`, does the repeatable work, so anyone can run it. A Claude Code skill in this repository, `.claude/skills/release`, walks through the steps around it that need judgment. The repository's .gitignore lets .claude/skills/ through, since .claude folders are often ignored.

1. **Choose the number.** The script compares the current build with the previous release: the hook list and the host's exported names, saved at that release, and `CivPluginApi.h` and the class layout record as they were at its tag. If anything was added, removed or changed, the middle number goes up; otherwise the last one does. Anything removed or changed is listed, since every plugin must then be rebuilt: before 1.0 that is allowed, and from 1.0 on the script stops unless it is run with --major, which starts a new major version. The first release has nothing to compare with and keeps the number already in `VERSION`.
2. **Prepare.** On a branch of its own, the release raises the version in `VERSION` at the top of the repository, which holds the release version and the version of Bazaar's mod, a whole number that goes up by one each release. The VMC Bootstrap keeps VMC's own version, 97, because Bazaar depends on exactly that version; so does VMC's save-format number in CustomMods.h, which only a VMC update changes. The API version in `CivPluginApi.h` and the Claude plugin's version in `plugin.json` follow it, and so does the Bazaar release the SDK's plugin template says it needs, in its `VERSION` and its Workshop description: the first release with this API version, such as 0.4.0 for 0.4.2. The script refuses to build when any of them disagree. The Lua mod template's Bazaar release is set by hand instead, since a Lua mod needs only the Bazaar features it uses. The docs step saves the new function history, and the script saves the new lists. The tests and the lint run, and the branch goes to main through a pull request.
3. **Build.** From main, with nothing uncommitted, the script builds the host, lays out and checks the SDK, builds the docs, and writes the release's files, each carrying LICENSE and NOTICE:
   - Bazaar's two mods as `.civ5mod` packages, Bazaar itself and its VMC Bootstrap;
   - the SDK zip;
   - the docs zip, with the site and its Markdown copy.

   Building the docs again for a release whose history is already saved gives the same pages, so this build marks the same changes as the preparation did. If a function moved within its file after the preparation, its code unchanged, this build moves its marks to the new lines and so changes the history file; the script then stops, and the moved lines reach main through another pull request before the release is tagged. `release.py build --trial` does the same on any branch, without the release marks in the docs, and writes to `dist/trial`; nothing is published from it.
4. **Check in the game.** The packages are installed from the release's files, not the build folders, and a game is loaded with the template plugin built from the SDK zip. The log has to show the plugin's hooks running.
5. **Publish.** The script tags main, such as `v0.4.0`, and creates the GitHub release as a draft, with the files attached and release notes the skill drafts: what changed for players, and what was added for plugin authors. The developer publishes it from the draft. Releases before 1.0 are marked as pre-releases.
6. **Docs site.** A GitHub Action runs when a release is published, pre-releases included. Once per repository, Pages must deploy from GitHub Actions, and the github-pages environment must let tags matching `v*` deploy. It takes the site out of that release's docs zip and publishes it on GitHub Pages, so the site always shows the newest release. The repository stays private until 1.0, when the Workshop items go public, and becomes public with them. Until then the project's GitHub Team plan publishes Pages from the private repository, and the site itself is public. The Action can also be run by hand on any release to publish its site again.
7. **Workshop.** Every release, pre-releases included, is uploaded to the Steam Workshop by hand in ModBuddy: Bazaar's package each time, with the release's section of `workshop/changes.txt` as the change note, and the VMC Bootstrap only when it has changed. Before 1.0 the Workshop items stay private; they go public with 1.0, when the repository does. The Workshop page points to the GitHub release for the SDK and docs.

One check before the second release, when Bazaar's mod version first goes up: whether a save made with the first release still loads after the player updates to the second, since Civ 5 records each mod's version in the save. If it does not, Bazaar's mod version cannot go up with every release, and step 2 changes.

### Releasing a plugin or Lua mod

Plugin and Lua mod authors get a release script of their own, `release.ps1`, in the plugin template in the SDK and in the Lua mod template in the Claude Code plugin; the two copies are the same file, and a check in this repository keeps them so. A `release.cmd` beside it starts it, since Windows does not run PowerShell scripts by default. It assumes no git, GitHub or other hosting, and leaves the Workshop upload to the author, in ModBuddy.

- `VERSION` holds the release number in the author's own scheme: either a whole number, which is also the mod's version, or semantic versioning, with a second line for the mod's version, which the script raises by one each release because the game takes only a whole number. Another line names the oldest Bazaar release the mod needs.
- Before building, the script writes the version from `VERSION` into the `.civ5proj` and, for a plugin, into a small header the DLL is built with, so the author changes it in one place. It checks that the mod's version is higher than every released one; that nothing of the template is left, such as its mod ID or its name; and, for a plugin, that the SDK is not newer than the Bazaar release `VERSION` names.
- It builds with the template's `build.cmd`, then checks the package: a mod that changes the game's database must affect saved games, and a plugin's DLL must be named in a `DllPlugins` row and declare the API version it was built for.
- It keeps each release's package in `Releases\<version>\` and never overwrites one.
- `CHANGES.txt` holds the change notes in BBCode, newest first, to paste into the Workshop update; the script warns when the new version has no section.
- Each template also has a Workshop description in BBCode, `workshop-description.txt`, to paste into ModBuddy. It says "Requires Bazaar X or newer.", and the script stops when that differs from the Bazaar release `VERSION` names.

The SDK guide's Publishing section and the two Claude Code skills say how to use it.

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

**P1 — the host.** Copy VMC v97 over the Firaxis source in its own commit (own GUID, credits), add the loader, the generator to the build (writing the hook wrappers), the exports, the hand-placed hook set above, failure containment, the Plugins screen, the version check before any plugin code runs, and a build check that fails when a class layout changes. Exit: the host builds, loads a game, VMC's events fire, the Plugins screen orders two toy plugins, no MCP code inside.

**P1.5 — developer documentation.** On its own branch, started from P1 while P1 finishes, and merged after P1: the docs step that writes the generated reference, the task-based guide, the class summaries and the documentation site, as described under Developer documentation. Exit: the docs step builds the whole site on this machine.

**P1.6 — releases.** After P1.5 merges: the Markdown copy of the docs, the release script, the skill and the Action that publishes the docs, as described under Making a release. Exit: the release script, the skill and the docs Action on main, and a trial build that makes all four files. The first pre-release, made from main with each file installed or opened from the release and checked, and its docs site published by the Action and opened there, follows once main holds the plugin API the game is played with.

**P2 — MCP as a plugin.** Move `Claude/` from civ5-mods into the plugin's own repository, wire hooks, Lua registration, packaging. Exit: every existing tool and the log window work exactly as in v47, verified by playing a few turns with a model and reloading a save.

**P2.5 — releases for plugin and Lua mod authors.** A release script for the plugin template and the Lua mod template, as described under Releasing a plugin or Lua mod. Exit: the script and its tests on main, and a plugin and a Lua mod made from the templates each released with it through the real build.

**P3 — the rest.** Explorer fix, captured-city seen-by fix, friendship/denounce rules and calmer AI as Lua mods on VMC hooks where one exists, native plugins where not; the calmer-AI fix is the natural first replace plugin, since it replaces one diplomacy function. The first public release, 1.0, of the host and SDK from this repository, the MCP plugin's first release from its own, and the Workshop pages. The layouts and the hook numbers freeze at that release.

## Risks

- **Speed.** Every wrapped function is a real call plus a listener check, and nothing wrapped can be inlined. The hot paths call small functions millions of times a turn. P0 measures it on both compilers before anything is committed; the fallback is the same generator on a chosen subset.
- **The generator's long tail.** A few hundred odd signatures could cost more than the rest together. P0 runs it over everything for that reason.
- **The layout freeze is a discipline, not a mechanism.** One added field breaks every plugin. The build compares the exported layouts against a saved record and fails on any change. Before 1.0, a change is accepted on purpose by saving the record again and rebuilding every plugin; from 1.0 on, it is not.
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
