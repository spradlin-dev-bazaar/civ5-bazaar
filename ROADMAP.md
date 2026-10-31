# Roadmap

What's planned for Bazaar after 0.5. Nothing here has a date, and plans can change. Smaller fixes and ideas are in [GitHub's issues](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues).

## The goal

Nobody should have to build one huge DLL mod anymore. The game runs only one mod that replaces its DLL, so big DLL mods have grown to hold everything their authors wanted. Bazaar runs many, so a big mod can be split into plugins, one for each part of the game it changes, such as combat or religion. Players pick the plugins they want and combine them with plugins from other mods. Some plugins from different mods change the same thing and can't work together, and Bazaar tells the player which ones and why.

A ported mod is a handful of plugins: a core plugin, and one plugin for each part of the game the mod changes, which all need the core. The mod's options become settings of those plugins. A mod that comes in a small and a full edition becomes one set of plugins, with the full edition as a set of settings.

The releases below add what it takes to split a big DLL mod into plugins. Ports of big mods come from repositories of their own, one for each mod.

## 0.5: out now

Bazaar 0.5.0 is the first public release. Every 0.x release after it only adds to what plugins can use, so plugins built for 0.5 keep working until 1.0.

## The survey: done

A survey ([#97](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/97)) compared the source code of seven big DLL mods, VMC among them, with the code each was built from, function by function. Then people read the changes behind the numbers. What it found shaped the plan below:

- Mods change lines in the middle of the game's functions far more often than at the start or end, which is all today's hooks can reach. But in each of the functions mods change most, most mods change the same few places. So 0.7, which splits functions and adds hooks in the middle of them, comes before 0.8.
- Most of the mods change the game's functions for loading the database, for Lua and for saving only to read their new database columns, add Lua functions, and save and reset their new fields. Plugin tables, Lua for plugins and values take that work away.
- One plugin for each option would mean over a hundred plugins for some mods, too many to install and manage. So a port is a few plugins with settings, and settings come in 0.6.

## 0.6: what every port needs

- **Before-hooks that change arguments** ([#116](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/116)). A hook that runs before one of the game's functions can look at the values the function was called with, or stop the call. It will also be able to change those values.
- **After-hooks that know what happened** ([#117](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/117)). When one plugin's before-hook stops a call, the before-hooks after it don't run, but every plugin's after-hook still does. A plugin can have several before- and after-hooks on one function, and only its author knows which of them belong together. So each after-hook will be able to tell whether a given before-hook of its plugin ran, and whether the call was stopped. The SDK will also offer a way to hand data from a before-hook to an after-hook that still works when the function runs again before it returns, as when moving a unit moves the units it carries.
- **Plugin tables** ([#119](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/119)). A plugin keeps its rules in tables of its own in the game's database, one row per building, unit, policy and so on. Plugins can already read the database. The SDK will add a helper that reads such a table into lookups by the game's own numbers, a rule for naming tables so two plugins' tables don't get the same name, and a section of the plugin guide. Other mods add rows to a plugin's tables with XML or SQL, as they do to the game's own tables, and load after the plugin's mod.
- **Plugin settings** ([#84](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/84)). A plugin can have settings, such as one for each feature it can switch on. Players choose them on the Plugins screen when they set up a game, and each saved game keeps its own, as it does with the game's own options. Content mods set their defaults with XML or SQL, so a set of settings can be a small mod of its own. A plugin switches on only the hooks its settings need, so a feature that's switched off never holds back another plugin ([#121](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/121)).
- **Each plugin lists what it needs, what it clashes with and which names it owns** ([#120](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/120)). A plugin lists:
  - the plugins it can't work with
  - the plugins it needs ([#65](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/65)), and the plugins whose changes its hooks must see, so Bazaar loads it after them
  - the names it owns: its events, and the option names it implements, such as VMC's, so Bazaar holds back the lower of two plugins that own the same name.

  Any of these can depend on a setting. When a plugin is held back, the plugins that need it are held back too, and a plugin can look for other plugins once every plugin has loaded ([#83](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/83)). Because a port's plugins all need its core, another plugin can clash with the whole port by naming the core, or with one of its plugins by naming that one.
- **Plugins that sit out one game.** Each saved game keeps its own settings, so a plugin can sit out one game, because of a clash its settings cause there, and run in the next ([#121](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/121)). The Plugins screen shows this while the player sets up a game. When a saved game loads and plugins sit out, one message says how many and opens a Plugins screen inside the game. That screen also opens from the game's "Additional Information" menu at the top right. It shows each plugin, whether it runs in this game and why not, and its settings for this game. It can't change anything ([#122](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/122)).
- **The private and protected parts of the game's classes** ([#85](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/85)). Code moved out of a big mod uses them everywhere.
- **Crash reports players can send:** a readable report for every crash ([#82](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/82)), with the whole call stack ([#56](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/56)).
- **Bazaar's calls placed by its build tools** ([#79](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/79)). Bazaar adds calls of its own into the game's code; its build tools will place them, as they place hooks today. 0.7's new hooks build on this, and it lets other DLL mods include Bazaar.
- **A replay check** ([#111](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/111)). The game plays out the same way twice from the same start and seed. A test will play a game before and after a change to the game's code and compare the two, to prove the change alters nothing in play. The plugins that are on, and their versions, count as part of the start.
- **A moment for when a game is ready** ([#123](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/123)). Plugins need a place to run code once a new game is set up or a saved game has loaded, when the map and every player exist. The game's own `CvGame::DoGameStarted` probably runs then, and it already has a hook. If it doesn't run after a saved game loads, Bazaar adds a hook that does. Some of the game's setup functions may run more than once, so a total a plugin adds to there could double. A plugin can rebuild such totals at that moment instead.
- **VMC code that changes play while its option is off.** Some of VMC's options are off by default but still change play:
  - ranged units and cities can't fire at a submarine under ice ([#108](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/108))
  - a random number is drawn for every unit created, which changes every random result after it ([#112](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/112))
  - a new Great Admiral can stay in a city whose only water is a lake, or on a city tile that's already full, where the game without VMC moves it to another city on the sea, or onto the sea ([#113](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/113))
  - only enemy ships blockade a city's worked water tiles, where the game without VMC lets embarked land units blockade them too ([#114](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/114)).

  Each of those will check its option, so that while it's off it changes nothing in play, before the replay check records the games 1.0 is compared against. The blockade option will also do what its description says when it's on. The bugs the survey found in VMC's code ([#104](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/104) to [#109](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/109)) are fixed too.

## 0.7: smaller pieces of the game's code

A plugin can replace a whole function of the game's code, or add to its start or end. Big mods often change a line or two in the middle of a long function, so two plugins that change different lines of the same function can't both run.

- **The longest functions split** ([#125](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/125)) into smaller ones, each of which a plugin can hook or replace on its own. What the game does doesn't change, and the replay check proves it. The survey lists the splits for the 60 functions mods change most, such as the reward from a goody hut, the steps of a battle and a city's turn.
- **Hooks in the middle of functions** ([#126](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/126)) where mods need them, placed by the build tools. One example: the AI picks the test for each of its strategies by the strategy's name, from a fixed list, so a strategy a mod adds to the database is never tested. A hook before that list lets a plugin test its own strategies. Where a port needs to know each time the game changes a value, the value gets a function that sets it.
- **Functions in the game's header files** ([#127](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/127)). These can't be hooked today. The ones mods change will be moved where they can be, starting with the one that gives how many units fit on a tile.
- **Numbers that explain themselves** ([#128](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/128)). Tooltips work out their numbers again with copies of the game's calculations, so a mod that changes a calculation has to change each copy too. When a function that works out a number is split, it will also write the lines that explain the number, so a plugin that changes the number changes its line in the same hook.
- **Speed, measured** ([#129](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/129)) with plugins that hook the game heavily. Speed fixes from other mods go into Bazaar's own code only where measuring shows they're faster and the replay check shows they change nothing.
- **A first port** ([#130](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/130)): fixes for bugs in the game's code that big DLL mods made, such as the game's function for the direction between two tiles, which never answers north-west. They come as a few plugins, built and released together. VMC's fixes aren't among them, since Bazaar already has those until 1.0.

## 0.8: data and Lua

- **More kinds of values** ([#132](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/132), [#133](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/133)). Values are a plugin's own saved data on players, cities, units and plots. They will also sit on teams, on the game as a whole and on spies, and hold lists. For ports that add thousands of fields, a plugin will be able to keep a struct of its own on each object. Once Bazaar saves lists and structs, the way it stores them in a save stays the same until the next major version.
- **Lua for plugins** ([#134](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/134)). Plugins add Lua functions to players, cities, units, plots and teams, as the game's own are, and fire GameEvents. Each event name belongs to one plugin. An event costs almost nothing when no Lua mod listens to it, and a plugin can let other plugins hook its events, as they hook the game's functions. When two plugins add Lua functions of the same name, the Plugins screen says so. Lua for plugins is designed with multiplayer in mind, so it won't need to change when multiplayer comes.
- **New entries in the game's built-in lists** ([#135](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/135)). The game numbers some kinds of things in lists built into its code, such as city tasks, trade items and quest types, and a plugin can't add to them today. Each list will become a database table, with the game's own entries first, so they keep their numbers. A plugin adds an entry as a row, and where the game's code handles the list one entry at a time, an entry it doesn't know goes to the plugin that added it. The game's trade screen names its trade items by hand, so Bazaar will ship a trade screen, as a mod of its own, that shows plugins' trade items too ([#136](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/136)).

## Tools for porters

- **Bazaar's debug file in the SDK** (0.6, [#124](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/124)). With Bazaar's `.pdb` file, a plugin author's debugger and crash call stacks name the game's and Bazaar's functions, not only the plugin's.
- **One build and one release for several plugins** (0.7, [#131](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/131)). The SDK's template builds and releases one plugin; a port has to build and release all its plugins together, as one mod.
- **Later:** a check that a port plays the same as the mod it came from ([#137](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/137)).

## 1.0: a clean core

Bazaar 1.0 will be the first release that breaks older plugins. It's the release where Bazaar becomes a clean base with no gameplay changes of its own. It keeps the game's own code and what mods made for VMC rely on: VMC's Lua events, its options table, and the functions VMC added for numbers the game had fixed, such as a unit's maximum health, a city's working radius and how many units fit on a tile. Plugins hook those functions to change the numbers.

VMC's gameplay changes ([#138](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/138)), which are part of Bazaar today, move out into plugins built with the tools from 0.6 to 0.8: about ten of them, one for each part of the game, such as units, city-states and religion. Each of whoward69's pick'n'mix features becomes a setting of one of them. VMC's bug fixes that don't change play, such as crash fixes, stay in Bazaar. Those that change play go into a plugin, each with a setting of its own. The plugins come from one repository of their own and are released together with each Bazaar release.

- The first step is sorting every one of VMC's changes into what stays in Bazaar and what moves. The survey has sorted most of them.
- VMC's option names become the names of the settings, so a mod that switches on a VMC option today still switches on the same feature. whoward69's original pick'n'mix mods switch on VMC's options and add their own content, so they may keep working.
- The replay check proves the move: Bazaar 1.0 with VMC's plugins plays the same as 0.x with the same options.
- Changes to the layout of the game's classes, which only a major release can make ([#139](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/139)): the number of yields comes from the database, so a plugin can add a yield; culture and faith are kept in hundredths, while the game's Lua methods still give whole numbers; and whether to allow more than 22 major civilizations is decided after measuring what each way costs.
- Bazaar 1.0 comes on new Steam Workshop items, not as an update. Games saved with 0.x need the 0.x mod, so its items stay up, and plugins built for 0.x keep working there.
- Every plugin is rebuilt for 1.0.
- The parts of the plugin API kept only so that plugins built for 0.5 keep working are replaced ([#118](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/118)): the two kinds of before-hook become one, and every after-hook gets an object describing the call.
- Bazaar's Workshop page links to the new plugins.
- Each feature that moves is checked in the game before 1.0 is released.

## After 1.0: multiplayer and hot seat

This is [#51](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/51). Until it's done, Bazaar and its plugins are single player only. It comes after 1.0 so it's built once, on the clean core, but its first step comes during 0.x, to find out early whether it can work.

1. Play a multiplayer game and a hot seat game with Bazaar and no plugins ([#115](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/115)). If this fails in ways Bazaar can't fix, multiplayer stays out.
2. Make plugins work there: players get a way into multiplayer games with mods, since the game hides its own button for them; every player's computer loads the same plugins in the same order, with the same settings; a plugin crash on one computer doesn't put the game out of step; the crash pop-up isn't lost in hot seat when the turn passes; and the multiplayer and hot seat setup screens lead to the Plugins screen.
3. Plugins send commands of their own to every player's computer through one channel Bazaar owns. Mods today hide such commands inside the game's own messages, such as the one for renaming a city, and two mods that do this clash without any warning.
4. Mark Bazaar, and the templates new plugins and Lua mods start from, as working in multiplayer and hot seat.

After that: a list of plugins that players can share, which also tells them which mods they still need.

## Not planned

- **Running another mod's whole game DLL beside Bazaar.** Only one mod can replace the game's DLL. The way to combine big DLL mods is to split them into plugins, as above. A big mod could also build Bazaar into its own DLL, but that would be their own build of it.
- **More than one plugin replacing the same function.** When two plugins replace the same function, Bazaar holds one back and the Plugins screen says why. Hooks before and after a function, which any number of plugins can add, cover most needs, and 0.7's smaller functions cover more. In every case the survey found of two mods replacing the same function, neither replacement runs the game's original function, so letting both run would still lose one of them.
- **A newer Visual Studio.** The game was built with Visual Studio 2008 and passes text to Bazaar in the form that version uses, so Bazaar and its plugins stay on 2008. A newer compiler with 2008's files may be tried later, but never in the same release as VMC's move to plugins.
- **Bazaar's own copies of the game's screens,** such as the combat preview or the tooltips, for plugins to add lines to. Bazaar would then clash with every UI mod that replaces the same screens. Instead, 0.7's split functions write their explaining lines, and Lua for plugins in 0.8 hands them to any screen that asks. The one exception is the trade screen ([#136](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/136)), which can't show a plugin's new trade item any other way. Bazaar's copy changes only what new trade items need, and comes as a mod of its own that only plugins adding trade items need.
