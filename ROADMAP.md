# Roadmap

What's planned for Bazaar after 0.5. Nothing here has a date, and plans can change. Smaller fixes and ideas are in [GitHub's issues](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues).

## The goal

Nobody should have to build one huge DLL mod anymore. The game runs only one mod that replaces its DLL, so big DLL mods have grown to hold everything their authors wanted. Bazaar runs many, so a big mod can be split into small plugins that each do one thing. Players pick the plugins they want and combine them with plugins from other mods. Some plugins from different mods change the same thing and can't work together, and Bazaar tells the player so before the game starts.

The releases below add what it takes to split a big DLL mod into plugins. Ports of big mods come from repositories of their own, one for each mod.

## 0.5: out now

Bazaar 0.5.0 is the first public release. Every 0.x release after it only adds to what plugins can use, so plugins built for 0.5 keep working until 1.0.

## Next: a survey of big DLL mods

A tool will read the source code of large DLL mods for the game and compare it with the game's own code. It sorts every change by what Bazaar needs to turn it into a plugin, and lists the changes nothing planned here covers yet. Its results decide what goes into 0.7 and 0.8, and which of the two comes first.

## 0.6: what every port needs

- **Before-hooks that change arguments.** A hook that runs before one of the game's functions can look at the values the function was called with, or stop the call. It will also be able to change those values.
- **Plugin tables.** A plugin keeps its rules in tables of its own in the game's database, one row per building, unit, policy and so on, and Bazaar loads them when the game loads its database. Other mods add rows with XML or SQL, as they do for the game's own tables.
- **The private and protected parts of the game's classes** ([#85](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/85)). Code moved out of a big mod uses them everywhere.
- **Plugins that need each other.** Bazaar follows the dependencies a mod lists ([#65](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/65)), and a plugin can look for other plugins once every plugin has loaded ([#83](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/83)). A big mod split into plugins needs both.
- **Crash reports players can send:** a readable report for every crash ([#82](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/82)), with the whole call stack ([#56](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/56)).
- **Bazaar's calls placed by its build tools** ([#79](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/79)). Bazaar adds calls of its own into the game's code; its build tools will place them, as they place hooks today. 0.7's new hooks build on this, and it lets other DLL mods include Bazaar.
- **A replay check.** The game plays out the same way twice from the same start and seed. A test will play a game before and after a change to the game's code and compare the two, to prove the change alters nothing in play.
- **Declaring clashes.** The plugin guide will show how a mod lists the mods it can't work with, using the game's own "blocks" setting, so the Mods screen won't switch both on.

## 0.7: smaller pieces of the game's code

A plugin can replace a whole function of the game's code, or add to its start or end. Big mods often change a line or two in the middle of a long function, so two plugins that change different lines of the same function can't both run.

- **The longest functions split** into smaller ones, each of which a plugin can hook or replace on its own. What the game does doesn't change, and the replay check proves it.
- **Hooks in the middle of functions** where mods need them, placed by the build tools.
- **Functions in the game's header files.** These can't be hooked today. The ones mods change will be moved where they can be.
- **Speed, measured** with plugins that hook the game heavily.
- **A first port:** the bug fixes of a big DLL mod, as plugins, to show the tools work.

The survey decides which functions are split and where the new hooks go.

## 0.8: data and Lua

- **More kinds of values.** Values are a plugin's own saved data on players, cities, units and plots. They will also hold lists, and sit on teams and on the game as a whole.
- **Lua for plugins.** Plugins add Lua functions to players, cities, units, plots and teams, as the game's own are, and fire GameEvents. They're designed with multiplayer in mind, so they won't need to change when multiplayer comes.
- **Plugin settings** players can change ([#84](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/84)).

0.7 and 0.8 may swap places, depending on what the survey finds.

## 1.0: a clean core

Bazaar 1.0 will be the first release that breaks older plugins. It's the release where Bazaar becomes a clean base with no gameplay changes of its own. It keeps the game's own code and what mods made for VMC rely on, such as VMC's Lua events. VMC's gameplay changes and bug fixes, which are part of Bazaar today, move out into plugins, built with the tools from 0.6 to 0.8: one for each of whoward69's pick'n'mix mods and one for the bug fixes. They come from one repository of their own and are released together with each Bazaar release. Then you choose which of them you want.

- The first step is sorting every one of VMC's changes into what stays in Bazaar and what moves.
- The replay check proves the move: Bazaar 1.0 with all of VMC's plugins on plays the same as 0.x.
- Bazaar 1.0 comes on new Steam Workshop items, not as an update. Games saved with 0.x need the 0.x mod, so its items stay up, and plugins built for 0.x keep working there.
- Every plugin is rebuilt for 1.0.
- Bazaar marks whoward69's original pick'n'mix mods as incompatible, and its Workshop page links to the new plugins.
- Each feature that moves is checked in the game before 1.0 is released.

## After 1.0: multiplayer and hot seat

This is [#51](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/51). Until it's done, Bazaar and its plugins are single player only. It comes after 1.0 so it's built once, on the clean core.

1. Play a multiplayer game and a hot seat game with Bazaar and no plugins. If this fails in ways Bazaar can't fix, multiplayer stays out.
2. Make plugins work there: every player's computer loads the same plugins in the same order, a plugin crash on one computer doesn't put the game out of step, the crash pop-up isn't lost in hot seat when the turn passes, and the multiplayer and hot seat setup screens lead to the Plugins screen.
3. Mark Bazaar, and the templates new plugins and Lua mods start from, as working in multiplayer and hot seat.

After that: a list of plugins that players can share, which also tells them which mods they still need.

## Not planned

- **Running another mod's whole game DLL beside Bazaar.** Only one mod can replace the game's DLL. The way to combine big DLL mods is to split them into plugins, as above. A big mod could also build Bazaar into its own DLL, but that would be their own build of it.
- **More than one plugin replacing the same function.** When two plugins replace the same function, Bazaar holds one back and the Plugins screen says why. Hooks before and after a function, which any number of plugins can add, cover most needs, and 0.7's smaller functions cover more.
