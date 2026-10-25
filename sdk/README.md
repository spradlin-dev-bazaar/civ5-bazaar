# Writing a Bazaar plugin

This guide shows you how to write a plugin for Bazaar: building the example plugin, turning it into your own, changing how the game plays, and publishing the result on the Steam Workshop.

It assumes you can program, but not that you know C++. The first time a piece of C++ notation appears, the guide says what it means, and the [notation table](#c-notation-used-in-this-guide) at the end lists all of it. The [Advanced](#advanced) part can wait until you need it.

## The big picture

Civilization V's rules live in its core DLL, `CvGameCore_Expansion2.dll`, written in C++. This guide calls it **the game's code**. Its classes are named after what they handle, such as `CvPlayer`, `CvCity` and `CvUnit`. `CvPlayer::GetScore` (the `GetScore` method of the `CvPlayer` class) works out a player's score.

A mod can replace the core DLL, but the game uses only one, so normally two DLL mods cannot be combined. **Bazaar** (the Bazaar Multi-DLL Mod Loader, in the Mods menu) is a replacement core DLL that also loads other DLLs, called **plugins**, so several of them can change the game at once.

A **plugin** is a DLL you write in C++. It ships inside an ordinary mod: a folder holding your DLL, an SQL file, and a `.modinfo` file that describes the mod. The build makes that folder from the template's `.civ5proj` project file. The player turns your mod on in the Mods menu, and Bazaar loads the DLL inside it.

```
Civilization V
  └─ Bazaar, in place of the game's core DLL
       ├─ your plugin's DLL      (inside your mod)
       ├─ another plugin's DLL   (inside its mod)
       └─ ...
```

- A plugin can **hook** one of the game's functions: have Bazaar call a function of yours, a **hook**, before it, after it, or instead of it.
- A plugin can be called at certain moments through Bazaar's **hand-placed hooks**: fixed spots inside the game's code, such as the one where a notification is added.
- A plugin can add functions that Lua code can call.
- A plugin can call the game's own functions, and read and change its public data.

For example, to make every player's score count double, you add an after-hook to `CvPlayer::GetScore` that doubles the score it returns. The [full example](#example-double-every-players-score) is further down.

## What you need

- **Civilization V with Brave New World**, and the **Bazaar** mod with its companion mod, **Bazaar - VMC Bootstrap (required)**. Steam offers the Bootstrap when you subscribe to Bazaar.
- **Visual C++ 2008 Express Edition with SP1.** A plugin must be built with the same compiler and settings as Bazaar: the two pass game objects, strings and lists back and forth, and a DLL built any other way may lay them out differently, read them wrongly and crash the game. Microsoft no longer offers it, but the Internet Archive keeps the [Visual Studio 2008 Express Editions with SP1 disc image](https://archive.org/details/vs-2008-express-w-sp-1). Open the ISO in File Explorer (Windows mounts it as a drive), start its setup, and choose **Visual C++ 2008 Express Edition**; none of the optional extras it offers are needed. It installs the Windows SDK headers and libraries the build uses along with it.
- **The Sid Meier's Civilization V SDK**, from Steam, for ModBuddy, which packages mods and uploads them to the Steam Workshop. The template's build script uses ModBuddy's build steps to make the mod; you open ModBuddy yourself only to upload.
- **The Microsoft Visual Studio 2010 Shell (Isolated) Redistributable**, which ModBuddy runs in. The Civilization V SDK's launcher will not start ModBuddy without it. Microsoft no longer offers it either, but the Internet Archive kept [Microsoft's original installer, `VSIsoShell.exe`](https://web.archive.org/web/20201112013416/http://download.microsoft.com/download/1/9/3/1939AD78-F8E8-4336-83F3-E2470F422C62/VSIsoShell.exe); its digital signature is Microsoft's.
- **ModBuddy started once**, from the Civilization V SDK, before your first build. Its updater copies the build steps `build.cmd` uses into `C:\Program Files (x86)\MSBuild\Firaxis\ModBuddy`.
- **The Bazaar SDK**, the folder that holds this guide.

### What is in the Bazaar SDK

| In the SDK | What it is |
|---|---|
| `plugin-template\` | A small working plugin to start from, with the script that makes its releases. |
| `include\CivHooks.h` | Every game function you can hook, with its hook ID. |
| `include\CivPluginApi.h` | The interface between Bazaar and a plugin: the structs, function types and constants both sides use. |
| the rest of `include\` | The game's headers, in the versions Bazaar was built from. |
| `lib\` | The libraries your plugin links against. |
| `CivPlugin.vsprops` | Bazaar's compiler and linker settings, which your plugin's project inherits. Do not change them: a changed setting can make your plugin and Bazaar lay out the objects they share differently, and crash the game. Add settings of your own in your project instead. |
| `hand-placed-hooks.md` | What each hand-placed hook does. |

## Step 1: build and try the template

1. Run `build.cmd` in the `plugin-template` folder, from a Command Prompt. It builds `TemplatePlugin.dll`, then the mod folder `Build\Template Plugin` with the DLL inside, and a package for the Steam Workshop in `Packages\`. If it stops early, it says why:

   | Message | What it means |
   |---|---|
   | Set BAZAAR_SDK to the Bazaar SDK folder. | There is no `CivPlugin.vsprops` in the folder the `BAZAAR_SDK` environment variable names or, when that is not set, in the folder directly above the template. See [Step 2](#step-2-make-it-your-own). |
   | Visual C++ 2008 was not found. | Visual C++ 2008 is not installed; see [What you need](#what-you-need). |
   | No mod name was found in mod\TemplatePlugin.civ5proj. | The `.civ5proj` has no `<Name>` line. The build names the mod folder after it. |
   | Civilization V was not found in the registry. | The script looked up where Steam installed Civilization V and found nothing. |
   | Your Documents folder was not found. | Windows did not report your Documents folder, so the build cannot find `My Games\Sid Meier's Civilization 5`. |
   | error MSB4019: The imported project "…\Firaxis\ModBuddy\Civ5Mod.targets" was not found. | ModBuddy's build steps are not installed yet. Start ModBuddy once from the Civilization V SDK, then build again. |
   | error PRJ0020 : Tool 'Linker', Property 'Manifest File' contains invalid file name '…', or project file '…' was not found or not a valid project file. | The plugin folder's path is too long: Visual C++ 2008 fails once a path inside it, such as `src\out\obj\<file name>.dll.intermediate.manifest`, passes 260 characters. Move the plugin folder to a folder with a shorter path and build again. |

2. Copy `Build\Template Plugin` into your MODS folder, `Documents\My Games\Sid Meier's Civilization 5\MODS`.
3. In the game's Mods menu, enable Bazaar - VMC Bootstrap (required), the Bazaar Multi-DLL Mod Loader and Template Plugin, then start a game.
4. In `Documents\My Games\Sid Meier's Civilization 5\Logs\Bazaar.log`, look for a line that starts with `Plugin Template Plugin 1 loaded`. From then on, the template logs a line at the start of each of your turns and one for each notification you receive. It also adds `Game.TemplateHello()` to Lua, which returns a greeting.

## Step 2: make it your own

1. Copy `plugin-template` to a folder of your own. If you built it in Step 1, leave out `Build\`, `Packages\`, `src\out\` and `mod\TemplatePlugin.dll`: those are the template's build output.
2. Unless that folder sits directly inside the Bazaar SDK folder, set the environment variable `BAZAAR_SDK` to the SDK folder: without it, the build looks for the SDK in the folder above yours. Open a new Command Prompt afterwards, so that it sees the variable, or set it for one Command Prompt with `set BAZAAR_SDK=<the SDK folder>` before running `build.cmd`.
3. Choose a file name without spaces, such as `ScoreDoubler`, and a display name, such as `Score Doubler`. Rename the four files with `TemplatePlugin` in their names (`src\TemplatePlugin.cpp`, `src\TemplatePlugin.vcproj`, `mod\TemplatePlugin.sql` and `mod\TemplatePlugin.civ5proj`). Then, in every text file in the folder (the `.cpp`, `.vcproj`, `.sql`, `.civ5proj`, `build.cmd` and `workshop-description.txt`), replace `TemplatePlugin` with the file name and `Template Plugin` with the display name.

   No other mod may ship a DLL with the same name as yours: Bazaar finds each plugin by searching the MODS folder for its file name.
4. Give your mod its own ID: replace the GUID on the `.civ5proj`'s `<Guid>` line with a new one (PowerShell's `New-Guid` makes one). It becomes the mod's ID in the `.modinfo`. Leave the `<ProjectGuid>` line above it alone: that one is ModBuddy's ID for the project. Every mod needs its own ID, so the game can tell yours apart from the template.
5. In the `.civ5proj`, set the teaser, description and authors. In `workshop-description.txt`, replace the template's sentence with a description of your plugin for its Steam Workshop page. Leave the version alone: `release.cmd` sets it for each release (see [Publishing](#publishing)).
6. Delete the template's examples you do not want, with their `Check(...)` lines in `CivPluginEntry`:
   - `BeforeDoTurn` logs the start of each of your turns;
   - `NotificationAdded` logs each notification;
   - `Hello` and `AfterRegisterGame` add `Game.TemplateHello()` to Lua.
7. Run `build.cmd` again. The `Build` folder now holds a folder with your display name.

Your code goes in the `.cpp` file. Its first `#include`, `CvGameCoreDLLPCH.h`, brings in most of the game's headers; the next two are Bazaar's, and the last, `PluginVersion.h`, holds your plugin's version. A new `.cpp` file needs the first three, and an entry in the `.vcproj`'s file list (copy the existing `<File>` entry).

## How Bazaar loads your plugin

### Your mod tells Bazaar about the DLL

Your mod's SQL adds your DLL's file name to the `DllPlugins` table:

```sql
CREATE TABLE IF NOT EXISTS DllPlugins (File TEXT NOT NULL);
INSERT INTO DllPlugins (File) VALUES ('TemplatePlugin.dll');
```

Bazaar's own mod creates that table. The first line only keeps the game's database log free of errors if your mod is ever enabled without Bazaar. The template's `.civ5proj` runs this SQL and declares a dependency on Bazaar, so the game will not enable your mod without Bazaar, and enables Bazaar first.

### Load order and the Plugins screen

When the game enables mods, Bazaar loads every plugin listed in `DllPlugins`, one after another, in the order shown on the **Plugins screen**. Bazaar puts that screen in place of the game's Advanced Setup (Mods > Single Player > Set Up Game > Advanced Setup). The order of its list, top first, is the **load order**, and it matters when two plugins hook the same function. On the screen, the player can move a plugin up or down, uncheck it to skip it without turning off its mod, and reload the plugins.

### The entry function: CivPluginEntry

When Bazaar loads your plugin, it calls the function your DLL exports as `CivPluginEntry`, once. In it, your plugin fills in its name and version and registers its hooks. Here is the template's:

```cpp
PLUGIN_EXPORT bool CivPluginEntry(const CivHostInfo* host, CivPluginInfo* plugin)
{
	s_host = host;
	plugin->name = "Template Plugin";
	plugin->version = PLUGIN_VERSION;
	Check(host->RegisterHook(host->pluginIndex, CivHooks::CvPlayer_doTurn::ID, CIV_HOOK_BEFORE, (void*)&BeforeDoTurn), "before CvPlayer::doTurn");
	Check(host->RegisterHandHook(host->pluginIndex, CIV_HAND_NOTIFICATION_ADDED, (void*)&NotificationAdded), "NotificationAdded");
	Check(host->RegisterHook(host->pluginIndex, CivHooks::CvLuaGame_RegisterMembers::ID, CIV_HOOK_AFTER, (void*)&AfterRegisterGame),
		"after CvLuaGame::RegisterMembers");
	return true;
}
```

- **`PLUGIN_EXPORT`** is defined at the top of the template as `extern "C" __declspec(dllexport)`. It exports the function from your DLL under its plain name, `CivPluginEntry`, which is the name Bazaar looks up.
- **`host`** (`const CivHostInfo* host`, a pointer to a read-only struct) is what Bazaar gives you: your plugin's index, `host->pluginIndex`, and function pointers for calling Bazaar: `host->RegisterHook`, `host->RegisterHandHook` and `host->Log`. (`host->Log` is the `Log` member of the struct that `host` points to.) The template saves `host` in `s_host` for its other functions.
- **`plugin`** (`CivPluginInfo* plugin`, a pointer to a struct) is yours to fill in: the plugin's name and version. Bazaar copies them when `CivPluginEntry` returns, so point both at text that still exists then, such as a string in quotes, not a local buffer. The template's version is `PLUGIN_VERSION`, which `src\PluginVersion.h` defines and `release.cmd` sets for each release.
- **The version of Bazaar's plugin API** that the plugin was built against is not set here. The template's line `CIV_PLUGIN_EXPORT_API_VERSION;`, near the top of the file, exports it, and Bazaar reads it from the DLL file before running any of the plugin's code. See [Bazaar versions](#bazaar-versions).
- **The `Check(...)` lines** register the hooks. `Check` is a helper in the template that logs a failed registration, and `(void*)&BeforeDoTurn` passes the hook function's address; [Registering a hook](#registering-a-hook) explains each argument. Hooks can only be registered from `CivPluginEntry`.
- **Returning `true`** loads the plugin. Returning `false` tells Bazaar not to load it, and the Plugins screen shows it as Not loaded: "Declined to load."

### Writing to the log

`host->Log(host->pluginIndex, text)` writes `text` as one line to `Bazaar.log`, headed with your plugin's name. The template's `Log` wraps it and takes a printf-style format. This line is from the template's `BeforeDoTurn` hook, which names its `self` parameter `player` (parameter names are up to you):

```cpp
Log("%s starts turn %d with %d gold", player->getCivilizationShortDescription(), GC.getGame().getGameTurn(), player->GetTreasury()->GetGold());
```

## Hooking the game's functions

### Finding a function to hook

`CivHooks.h` lists every function you can hook, one per line. Search it for the class and method together, such as `CvPlayer::GetScore(`; a single word such as `Score` matches far more lines, because many other functions use it too:

```cpp
namespace CvPlayer_GetScore { enum { ID = 6887 }; } // int CvPlayer::GetScore(bool, bool) const
```

- **`CvPlayer_GetScore`** is the hook's name in code. The line declares a namespace of that name holding an enum with one constant, `ID`, so `CivHooks::CvPlayer_GetScore::ID` is the hook's ID (`::` reaches a name inside a namespace or class), and you never type the number.
- **The comment** is the function's signature: `GetScore`, a method of `CvPlayer`, takes two `bool` parameters and returns an `int`. The `const` at the end means it does not modify the player.

When you search:

- Class names say what a function belongs to: `CvPlayer` a player, `CvCity` a city, `CvUnit` a unit, `CvPlot` a tile of the map, `CvTeam` a team.
- Classes whose names start with `CvLua` hold the functions Lua calls, and many of them only pass the call on to a game function. Hook that game function instead. Lua's `GetScore`, for example, calls `CvPlayer::GetScore`, so a hook on `CvPlayer::GetScore` also changes the score Lua sees.
- A function can run in more than one situation. `CvCity::CreateBuilding` runs when a city finishes a building, and also when the player buys one, so a hook on it runs in both cases.
- When a function is overloaded (several functions share a name but take different parameters), the first keeps the plain name and the others add their parameter types to it, such as `CvCity_getProductionNeeded_with_BuildingTypes_const`.
- Nearly every function written in one of the game's `.cpp` files is in the list. Functions defined in headers are not: they are inline, compiled into each place that calls them, so there is no single place where Bazaar could hook them. Constructors, destructors, templates and a few unusual functions are left out too.

### The three kinds of hook

| Kind | Runs | What it can do | Plugins per function |
|---|---|---|---|
| **Before-hook** | before the game's function | look at the parameters, and veto the call | any number |
| **After-hook** | after the game's function | read and change the return value | any number |
| **Replacement** | instead of the game's function | do the work itself, calling the game's own version if it wants | one |

When the game calls a function that plugins A, B and C have hooked, with A highest in the list, the hooks run in this order:

```
the game calls the function
   A's before-hook
   B's before-hook
   C's before-hook
   the replacement, if a plugin has one; otherwise the game's function
   C's after-hook
   B's after-hook
   A's after-hook
the game gets the result
```

- **Before-hooks** run in load order. Returning `true` **vetoes** the call: the game's function does not run, and neither do the replacement or the before-hooks after this one. The caller still gets a return value: whatever the hook stored in `result` (see [Writing a hook](#writing-a-hook)), or, if it stored nothing, a default: zero, `false`, or an empty string or object. Functions that return a reference work differently; see [Functions that return a reference](#functions-that-return-a-reference). Returning `false` lets the call go ahead. The after-hooks run either way.
- **A replacement** runs instead of the game's function. It gets the game's own version as its first parameter, `original`, and calling `original` runs it. Only one plugin can replace a function. If two try, the one lower in the list is not loaded at all, and the Plugins screen names both and says to move it higher to use it instead.
- **After-hooks** run in reverse load order, so the plugin highest in the list has the last word. They run after the game's function or the replacement, and also after a veto. Each can read the return value and change it.

### What a replacement skips

A replacement that never calls `original` skips everything the game's own version would have done: the functions it would have called, the hooks other plugins have on those functions, and the hand-placed hooks inside it. Bazaar makes this visible in two ways:

- The first time a replacement returns without calling `original`, Bazaar writes a line to its log naming the plugin and the function.
- If one plugin replaces a function that contains a hand-placed hook another plugin uses, Bazaar holds back whichever of the two is lower in the list, and the Plugins screen says why. A player who knows the replacement calls the game's own version can check **Use both anyway**.

### Writing a hook

A hook's parameters must match the game's function exactly. Build them from the function's line in `CivHooks.h`, in this order:

| Parameter | When it is there | For `int CvPlayer::GetScore(bool, bool) const` |
|---|---|---|
| `original` | replacements only | `int (*original)(const CvPlayer*, bool, bool)`: a function pointer to the game's own `GetScore` |
| `self` | methods that are not static | `const CvPlayer* self`: a pointer to the player, read-only (a pointer to a const `CvPlayer`) because `GetScore` is const |
| the function's own parameters | always: same types, same order | `bool bFinal, bool bVictory` |
| `result` | before-hooks and after-hooks, when the function returns a value | `int& result`: a reference to the return value |

- **`original`** is a function pointer: `original(self, bFinal, bVictory)` runs the game's own version.
- **`self`** is the object the method was called on (what C++ calls `this`). For a const method it is a pointer to const: the hook can read the object but not change it. Static methods and functions outside any class have no `self`.
- **`result`** is a reference to the value the caller will get, so assigning to it changes what the game gets back. In a before-hook the game's function has not run yet, so `result` holds a default (zero, `false` or empty), not the game's answer. Functions that return `void` have no `result`.

A before-hook returns a `bool` (`true` vetoes the call), an after-hook returns `void`, and a replacement returns the same type as the game's function. So for `GetScore`, the three kinds are declared like this (each still needs its `{ ... }` body when you write it):

```cpp
static bool BeforeScore(const CvPlayer* self, bool bFinal, bool bVictory, int& result);
static void AfterScore(const CvPlayer* self, bool bFinal, bool bVictory, int& result);
static int ReplaceScore(int (*original)(const CvPlayer*, bool, bool), const CvPlayer* self, bool bFinal, bool bVictory);
```

`static` here only keeps each hook private to your `.cpp` file, as in the template. C++ needs a function declared before it is used, so write your hooks above `CivPluginEntry`.

> **Get the parameters exactly right.** Registration accepts any function, so neither the compiler nor Bazaar can check them. If they do not match, your hook may crash, or it may quietly read the wrong values. Bazaar catches a crash and turns your plugin off, and the game keeps going, though it may not be stable afterwards. Copy the types from the function's line in `CivHooks.h`.

### Registering a hook

In `CivPluginEntry`, ask Bazaar to call your hook:

```cpp
Check(host->RegisterHook(host->pluginIndex, CivHooks::CvPlayer_GetScore::ID, CIV_HOOK_AFTER, (void*)&AfterScore), "after CvPlayer::GetScore");
```

`RegisterHook` takes:

1. `host->pluginIndex`, your plugin's index;
2. the hook ID, `CivHooks::` + the name from `CivHooks.h` + `::ID`;
3. the kind of hook: `CIV_HOOK_BEFORE`, `CIV_HOOK_AFTER` or `CIV_HOOK_REPLACE`;
4. your hook, as `(void*)&AfterScore`: `&AfterScore` is the function's address, and `(void*)` casts it to an untyped pointer. That cast is why nothing can check your hook's parameters.

It returns one of these codes, the `CivHookRegisterResult` values in `CivPluginApi.h`, and `Check` logs any code other than 0:

| Code | Name in `CivPluginApi.h` | Meaning |
|---|---|---|
| 0 | `CIV_HOOK_OK` | The hook is registered. |
| 1 | `CIV_HOOK_BAD_ID` | No game function has that ID, or no hook was given. |
| 2 | `CIV_HOOK_BAD_KIND` | The kind is not one of the three. |
| 3 | `CIV_HOOK_REPLACE_TAKEN` | The function is already replaced, by another plugin or by yours. |
| 4 | `CIV_HOOK_NOT_ALLOWED` | The hook was registered outside `CivPluginEntry`, or with an index that is not your `host->pluginIndex`. |

### Example: double every player's score

1. **Find the function.** Searching `CivHooks.h` for `CvPlayer::GetScore(` finds `int CvPlayer::GetScore(bool, bool) const`.
2. **Pick the kind of hook.** You want to change the value the game worked out, so use an after-hook, which can change `result`.
3. **Write the hook** above `CivPluginEntry`. Its parameters, from the table above, are `self`, the two `bool`s, then `result`:

   ```cpp
   static void AfterScore(const CvPlayer* self, bool bFinal, bool bVictory, int& result)
   {
   	result = result * 2;
   }
   ```

4. **Register it** in `CivPluginEntry`:

   ```cpp
   Check(host->RegisterHook(host->pluginIndex, CivHooks::CvPlayer_GetScore::ID, CIV_HOOK_AFTER, (void*)&AfterScore), "after CvPlayer::GetScore");
   ```

5. **Build and test it**, as in [Testing a new build](#testing-a-new-build). Every score the game works out is now doubled, including the scores Lua sees. To watch it work, add `Log("score %d", result);` after the doubling line for one test run, then take it out again: the game works out scores often.

A replacement could do the same with `return original(self, bFinal, bVictory) * 2;`, but it would take `GetScore` for your plugin alone. See [Which kind of hook to use](#which-kind-of-hook-to-use).

## Hand-placed hooks

Some moments are not the start or end of any one function: a notification, for example, can be added from many places in the game's code. And sometimes the game needs to ask plugins a question, such as "does a plugin play this player?". For these, Bazaar calls plugins from fixed spots inside the game's code: the hand-placed hooks. Each has a `CIV_HAND_...` constant in `CivPluginApi.h`, and `hand-placed-hooks.md` describes each one.

They come in two kinds:

- a **question**: Bazaar asks the plugins one by one, in load order, and stops at the first that answers yes. The hook returns a `bool`, `true` for yes;
- an **announcement**: every plugin that registered for it is told, in load order. The hook returns nothing.

Register for one in `CivPluginEntry` with `RegisterHandHook`. It returns codes from the same table as `RegisterHook`: 0 when it worked, 1 for an unknown hand-placed hook or no function, and 4 when called outside `CivPluginEntry`. The template uses it to log every notification:

```cpp
static void NotificationAdded(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2)
{
	Log("notification %d for %s: %s", notificationType, GET_PLAYER((PlayerTypes)player).getCivilizationShortDescription(), message);
}

// in CivPluginEntry:
Check(host->RegisterHandHook(host->pluginIndex, CIV_HAND_NOTIFICATION_ADDED, (void*)&NotificationAdded), "NotificationAdded");
```

`(PlayerTypes)player` casts the `int` player ID to the `PlayerTypes` enum that `GET_PLAYER` takes; see [Using the game's code](#using-the-games-code).

The hook's parameters must match the function type named in the comment above the `CIV_HAND_...` constant. For `CIV_HAND_NOTIFICATION_ADDED` that is `CivNotificationAddedFn`, which `CivPluginApi.h` defines further down with a typedef, as a function pointer type:

```cpp
typedef void (*CivNotificationAddedFn)(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2);
```

Take every parameter, even the ones you do not use. (`const char*` is a C string.)

## Which kind of hook to use

If one of [VMC's Lua events](#using-vmcs-events-and-options) already does what you need, a plain Lua mod is enough.

Pick in this order:

1. a hand-placed hook, if one in `hand-placed-hooks.md` fits;
2. otherwise, a before-hook or an after-hook on a game function;
3. a replacement only when you must, and have it call `original` whenever you can;
4. if you find yourself replacing a function other plugins would also want, ask for a new hand-placed hook in Bazaar's GitHub issues.

Any number of plugins can share the first two kinds. A replacement takes the function for one plugin, and if it does not call `original`, everything inside the game's own version stops happening too (see [What a replacement skips](#what-a-replacement-skips)).

## Adding a Lua function

A plugin can add functions to Lua's `Game` table, the one Lua code uses as `Game.Something()`. The game fills that table in `CvLuaGame::RegisterMembers`, so you add yours in an after-hook on that function. These are the template's pieces:

```cpp
// The function Lua calls as Game.TemplateHello().
static int Hello(lua_State* L)
{
	lua_pushstring(L, "Hello from the template plugin");
	return 1;
}

static void AfterRegisterGame(lua_State* L)
{
	lua_pushcclosure(L, &Hello, 0);
	lua_setfield(L, -2, "TemplateHello");
}

// in CivPluginEntry:
Check(host->RegisterHook(host->pluginIndex, CivHooks::CvLuaGame_RegisterMembers::ID, CIV_HOOK_AFTER, (void*)&AfterRegisterGame),
	"after CvLuaGame::RegisterMembers");
```

Lua and C++ exchange values on the Lua stack. `L` (`lua_State* L`, a pointer to the Lua state) is passed to every `lua_...` call. While `AfterRegisterGame` runs, the `Game` table is on top of the stack. `lua_pushcclosure(L, &Hello, 0)` pushes `Hello` as a Lua function, so the table is now second from the top. `lua_setfield(L, -2, "TemplateHello")` pops the function and stores it in the table at index `-2` (second from the top) as `TemplateHello`. Use the same two lines for each function you add.

`AfterRegisterGame` has no `self` and no `result`, because `RegisterMembers` is static and returns `void`.

A Lua function gets its arguments on the stack, starting at index 1: `lua_tointeger(L, 1)` reads the first one as an integer. It pushes its return values and returns how many it pushed, so `Hello` pushes one string and returns 1. This one returns the number of cities the active player (the player at this computer) has, or 0 when there is no active player:

```cpp
static int CountMyCities(lua_State* L)
{
	PlayerTypes active = GC.getGame().getActivePlayer();
	lua_pushinteger(L, active == NO_PLAYER ? 0 : GET_PLAYER(active).getNumCities());
	return 1;
}
```

Add it in `AfterRegisterGame` the same way, and Lua code can call `Game.CountMyCities()`.

Bazaar's crash protection covers your hooks, not your Lua functions. A crash in a Lua function crashes the game, and a plugin Bazaar has turned off after a crash in a hook keeps its Lua functions, which Lua can still call. Keep them short, and don't let them rely on state a crashed hook may have left half-changed.

## Using VMC's events and options

Bazaar includes whoward69's Various Mod Components (VMC), another mod that brings its own version of the game's code. The game can use only one such version, so VMC could not be on alongside Bazaar. Built in, its extra Lua events, Lua functions and options keep working, and so do mods made for VMC. It also means that a change that only needs one of VMC's events can be a plain Lua mod, with no plugin at all.

The code is inside Bazaar's DLL, so it is there whenever Bazaar is on. VMC's database files, which hold the options, are a separate mod, "Bazaar - VMC Bootstrap (required)", which the game turns on before Bazaar. It is separate, and uses VMC's own mod ID, so that mods made for VMC load after it, as they would with VMC itself.

Every VMC event starts switched off. To use one, switch it on in your mod's SQL, for example:

```sql
UPDATE CustomModOptions SET Value = 1 WHERE Name = 'EVENTS_PLAYER_TURN';
```

The Bootstrap's `CustomModOptions.xml` lists every option by name. This line only works if it runs after the Bootstrap has added the options. The template's dependency on Bazaar takes care of that: Bazaar needs the Bootstrap, so the game turns the Bootstrap on first, and your mod, which needs Bazaar, after both. (Mods made for VMC itself reference VMC's mod ID instead, which works too.)

## Using the game's code

Your plugin can call any function the game's headers declare, use the game's global variables and static member variables, and read and change public members, as the game's own code does. `GC` and `gDLL` (the game's two global objects) and `GET_PLAYER` and `GET_TEAM` (which return a player or a team by ID) work in a plugin just as they do in the game's code; the template uses `GC` and `GET_PLAYER`. Private and protected members cannot be reached from a plugin yet. Some useful calls:

| Code | What it gives you |
|---|---|
| `GC.getGame()` | the game in progress |
| `GC.getGame().getActivePlayer()` | the active player's ID, a `PlayerTypes` value |
| `GC.getGame().getGameTurn()` | the current turn number |
| `GET_PLAYER(id)` | a reference to the player with that ID |
| `GET_PLAYER(id).getNumCities()` | that player's number of cities |
| `GET_TEAM(id)` | a reference to the team with that ID (a `TeamTypes` value) |
| `GC.getBuildingInfo(building)` | a pointer to a building's details, or null for an invalid `BuildingTypes` value; `->GetDescription()` on it gives the building's name, already translated into the game's language |
| `self->getName().c_str()` | in a hook on a `CvCity` method, the city's name as a C string, for a log line |

`GET_PLAYER` and `GET_TEAM` return references, so their members are reached with `.`; pointers such as `self` use `->`.

## Testing a new build

Windows does not let you replace a DLL while the game has it loaded, and Bazaar unloads plugins at the main menu. So each time you try a new build:

1. in the game, go back to the main menu;
2. run `build.cmd` in your plugin's folder;
3. copy the new mod folder from `Build` into MODS, over the old one;
4. start a game.

## When something goes wrong

- **`Bazaar.log`**, in `Documents\My Games\Sid Meier's Civilization 5\Logs`, lists each plugin Bazaar loaded or did not load, with the reason, and every crash. The template's `Check` also logs there any hook that could not be registered.
- **The Plugins screen** shows each plugin's status:
  - Loaded;
  - Not loaded, with the reason: for example "Declined to load.", a newer Bazaar is needed, the DLL was not found in the MODS folder, or a clash with another plugin;
  - Turned off after a crash;
  - Skipped: the player unchecked it.
- **If your plugin crashes inside a hook,** the game carries on. Bazaar turns your plugin off until the player goes back to the main menu, and shows a "Plugin disabled" notice. A common cause is a hook whose parameters do not match the game's function. `Bazaar.log` then says where it crashed: what memory it touched, and the call stack, innermost first. Each line gives the DLL and an offset into it, such as `MyPlugin.dll+0x00001A2B`. On the machine you built the plugin on, while the `.pdb` file the build wrote is still where the build put it, the line also names the function and the source line, such as `(BeforeDoTurn, MyPlugin.cpp line 42)`. Without the `.pdb`, as on a player's machine, the call stack may skip some calls, but its first line is always where the crash happened.

## Publishing

Make each release with `release.cmd`, in your plugin's folder. It needs nothing beyond what building does: no git and no website.

1. In `VERSION`, set the release. Its `release` line is a whole number, such as `2`, or a semantic version, such as `1.2.0`. A whole number is also the mod's version, which the game and the package's name use (`(v 2)`), so raise it for each release. With a semantic version, the script keeps a `mod` line for the mod's version and raises it itself. The `bazaar` line names the oldest Bazaar release your plugin needs; the template already names the oldest one that can run a plugin built with this SDK. `workshop-description.txt` must say the same, in its "Requires Bazaar … or newer." sentence.
2. Add a section for the release to the top of `CHANGES.txt`, starting with the line `[b]<release>[/b]` and saying what changed. It is written in the Steam Workshop's BBCode, ready to paste. Without one, the script warns.
3. Run `release.cmd` from a Command Prompt. It writes the version into the `.civ5proj` and `src\PluginVersion.h`, builds the plugin, checks the package and copies it into `Releases\<release>\`. If something is wrong, it stops before releasing anything and says what to fix. Keep `Releases\`: it is how the script knows which mod versions are already out, so that none is used twice.
4. In ModBuddy, choose **Tools > Upload to Steam Workshop > Upload new Mod...**, and accept the terms. Click **[...]** and select the package in `Releases\<release>\`, such as `Releases\1\Score Doubler (v 1).civ5mod`. Paste `workshop-description.txt` as the description, and your `CHANGES.txt` section as the change note. For a later release, update your existing Workshop item with the new package instead of uploading a new mod.
5. On your plugin's Steam Workshop page, list Bazaar under Required Items: Steam then offers Bazaar to anyone who subscribes to your plugin.

The template marks the mod as affecting saved games (`<AffectsSavedGames>` in the `.civ5proj`). Keep it that way. A save lists the mods marked this way, and when someone loads it, the game applies the database changes of those mods only. Your plugin's SQL is a database change, so without the mark, a loaded save would have no `DllPlugins` row for your DLL and Bazaar would not load your plugin. Mods that change nothing in the database, such as ones that only add keyboard shortcuts, are not affected and can be added or removed freely. `release.cmd` refuses a release without it.

Bazaar itself does not keep anything in saved games for plugins.

## Advanced

Most plugins can leave this part until one of these comes up.

### Bazaar versions

Bazaar's plugin API has a version in two parts, major and minor: `CIV_HOST_API_MAJOR` and `CIV_HOST_API_MINOR` in `CivPluginApi.h`. The template's line `CIV_PLUGIN_EXPORT_API_VERSION;` exports the version your plugin was built against. Every plugin needs it, written once, outside any function, in one of its `.cpp` files.

Bazaar runs a plugin built for its own version or an older one. It refuses a plugin built for a newer version, or for a different major version, and says so in its log, on the Plugins screen and in a notice in the game. Before 1.0, a new Bazaar may also change the API in a way that needs your plugin rebuilt with the new SDK.

Bazaar reads the version from your DLL file before running any of your plugin's code, so a plugin it refuses never runs. That includes a plugin that uses functions an older Bazaar lacks, which Windows could not load: Bazaar refuses it with a message naming both versions instead. A DLL without the line is refused as built for an older Bazaar.

### Cleaning up: CivPluginShutdown

Most plugins do not need this. If your plugin starts threads, opens files or opens sockets, export a second function, `CivPluginShutdown`, and close them there. The template's only writes to the log:

```cpp
PLUGIN_EXPORT void CivPluginShutdown()
{
	Log("shutting down");
}
```

Bazaar calls it before it unloads your plugin: when the player goes back to the main menu, or reloads the plugins from the Plugins screen. Bazaar removes your hooks itself.

Bazaar also calls it when your plugin crashed or was refused after `CivPluginEntry` ran, so it must work even if `CivPluginEntry` stopped partway.

If one of your threads is still running when it returns, Bazaar leaves your DLL in memory, because unloading it would crash that thread, and your plugin stays off until Civilization V restarts. The same happens if `CivPluginShutdown` itself crashes.

### Functions that return a reference

A few functions return a reference to an object the game already holds, rather than a value. In `CivHooks.h`, their return type ends in `&`, which marks a reference:

```cpp
namespace CvPlayer_getHandicapInfo { enum { ID = 7473 }; } // CvHandicapInfo& CvPlayer::getHandicapInfo() const
```

This one returns a reference to a `CvHandicapInfo`, the player's difficulty settings. A reference cannot be null and cannot be pointed at another object later, so `result` cannot be one. Instead, for these functions `result` is a pointer to the object, passed by reference so that your hook can change it. C++ writes that as `CvHandicapInfo*& result`, a reference to a pointer to a `CvHandicapInfo`:

```cpp
static void AfterHandicap(const CvPlayer* self, CvHandicapInfo*& result);
```

- In an after-hook, `result` points at the object the function returned. To make the caller get a different object, point `result` at it: `result = &otherObject;` (`&` before a name takes its address).
- In a before-hook, `result` starts as null. To veto the call, the hook must also point `result` at an object to return, because a reference has to refer to something. If `result` is still null after a veto, Bazaar runs the function anyway.

## Word list

- **After-hook**: a hook that runs after the game's function, and can read and change its return value.
- **Before-hook**: a hook that runs before the game's function, and can veto the call.
- **The game's code**: the game's core DLL, `CvGameCore_Expansion2.dll`. Bazaar replaces it.
- **Hand-placed hook**: a fixed spot inside the game's code where Bazaar calls plugins. Each is either a question or an announcement.
- **Hook**: a function of yours that Bazaar calls before, after or instead of one of the game's functions.
- **Load order**: the order of the plugins on the Plugins screen, top first.
- **`original`**: a replacement's first parameter, a function pointer to the game's own version of the function.
- **Plugins screen**: the screen Bazaar puts in place of Advanced Setup, where the player orders, skips and reloads plugins.
- **Register**: tell Bazaar, in `CivPluginEntry`, which of your functions to call and when.
- **Replacement**: a hook that runs instead of the game's function. Only one plugin can replace a given function.
- **`result`**: a reference to the game's function's return value, passed last to before-hooks and after-hooks.
- **`self`**: the object a method was called on (C++'s `this`), passed first to a hook, or after `original` in a replacement.
- **Veto**: what a before-hook does by returning `true`: the game's function does not run.
- **VMC**: whoward69's Various Mod Components, which Bazaar includes: extra Lua events, Lua functions and options.

## C++ notation used in this guide

| Notation | Meaning |
|---|---|
| `T*` | a pointer to a `T` |
| `const T*` | a pointer to a `T` that cannot be changed through it |
| `T&` | a reference to a `T` |
| `T*&` | a reference to a pointer to a `T`: whoever has it can change where the pointer points |
| `&name` | the address of `name` |
| `p->m` | the member `m` of the object that the pointer `p` points to |
| `r.m` | the member `m` of an object, or of the object a reference refers to |
| `A::b` | the name `b` inside the class or namespace `A` |
| `(T)x` | `x` cast to the type `T`: `(void*)x` is `x` as an untyped pointer, `(PlayerTypes)x` is `x` as a `PlayerTypes` enum value |
| `R (*f)(A, B)` | `f` is a pointer to a function that takes an `A` and a `B` and returns an `R` |
| `typedef R (*Name)(A, B)` | names the function pointer type "pointer to a function that takes an `A` and a `B` and returns an `R`" `Name` |
| `namespace N { enum { ID = 5 }; }` | a namespace `N` holding an enum with one constant, `ID`, whose value is 5 |
| a signature ending in `;` | a declaration: it names the function and its parameters but has no body. The function still needs its `{ ... }` body |
| `const` after a method | the method does not modify its object |
| `static` on a method | the method belongs to the class, not to an object, so it has no `self` |
| `static` on a function in your file | the function is private to that `.cpp` file |
| `void` | no return value |
| `const char*` | a C string |
| `extern "C" __declspec(dllexport)` | export the function from the DLL under its plain name |
| `#define NAME text` | makes `NAME` stand for `text` wherever the code uses it |
