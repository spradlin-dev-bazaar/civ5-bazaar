# Bazaar Multi-DLL Mod Loader

A mod for Civilization V: Brave New World that lets you run more than one DLL mod at a time.

Civilization V loads only one game DLL, so normally only one DLL mod can run at a time. Bazaar replaces the game DLL with one that loads other DLL mods as plugins, so several can run in the same game. A plugin is a DLL mod made for Bazaar. A DLL mod made for the plain game, such as the Community Patch, does not run with Bazaar until it is remade as a plugin.

Bazaar also includes whoward69's Various Mod Components (VMC, version 97), so mods that need VMC work with Bazaar too.

## Status

Bazaar 0.5.0 is the first public release. Plugins made for it will keep working with every later 0.x release, because until 1.0, new releases only add things for plugins to use and never change or remove what is already there. The first plugins are out: [MCP Server for Bazaar](https://steamcommunity.com/sharedfiles/filedetails/?id=3827230313), which lets AI models play the game with you, against you or for you ([source](https://github.com/spradlin-dev-bazaar/civ5-mcp-plugin)), and [Reduced Aggression (Bazaar)](https://steamcommunity.com/sharedfiles/filedetails/?id=3827446901), which adds two rules against sudden wars ([source](https://github.com/spradlin-dev-bazaar/civ5-reduced-agression)). The full plan is in [docs/plugin-host.md](docs/plugin-host.md).

## Installing

You need Brave New World, on Windows.

1. On the Steam Workshop, subscribe to [Bazaar Multi-DLL Mod Loader](https://steamcommunity.com/sharedfiles/filedetails/?id=3825428828) and [Bazaar - VMC Bootstrap (required)](https://steamcommunity.com/sharedfiles/filedetails/?id=3825428468). The second one holds VMC's database files, and Bazaar needs it.
2. Subscribe to the plugins you want.
3. In the game's Mods menu, turn on Bazaar Multi-DLL Mod Loader, Bazaar - VMC Bootstrap (required) and your plugins.

To install by hand instead, download both packages from the newest release on the [Releases page](https://github.com/spradlin-dev-bazaar/civ5-bazaar/releases) and put them in your MODS folder, `Documents\My Games\Sid Meier's Civilization 5\MODS`.

## What it does

- **More than one DLL mod at a time.** Each plugin is an ordinary mod with a DLL inside, from the Steam Workshop or installed by hand. It lists Bazaar as a requirement, so the game won't let you turn it on without Bazaar.
- **A Plugins screen.** It shows which plugins loaded and any that failed or were refused, and lets you reorder them or skip any of them. It opens in place of Advanced Setup (Mods > Single Player > Set Up Game > Advanced Setup), and its Continue button then opens the usual Advanced Setup, or another mod's version of it such as Really Advanced Setup's.
- **A crashing plugin doesn't crash the game.** Bazaar catches the crash, names the plugin, and sends you back to the main menu without saving, since the game may be damaged. Load your last save or autosave to play on.
- **VMC included.** VMC's extra Lua events and options are there for the mods that use them. VMC also changes a few of the game's rules, as it does on its own: for example, the AI's anger at warmongering builds up much faster.

## Saved games

- Bazaar keeps each plugin's data in your saved games, so when you load a game, its plugins carry on where they left off.
- A save made with a plugin's mod turned on loads only with that mod, as with any mod that affects saved games.
- If you turn a plugin off for a while, Bazaar keeps its data in your saves, and the plugin gets it back when you turn it on again.
- If Bazaar cannot read its part of a save, it tells you when the save loads, so you can keep a copy before saving over it.

## Limits

- Windows only. Single player only.
- It doesn't work with any other mod that replaces the game DLL, such as the Community Patch or whoward69's own VMC mod. Bazaar already includes VMC, so turn VMC's own mod off.
- Another mod that replaces Advanced Setup, if installed after Bazaar, shows its own screen instead of the Plugins screen ([#55](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/55)).

## Getting help

Ask on [Bazaar's Discord](https://discord.gg/zuRynuzNxr), or report a bug in [GitHub's issues](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues).

## For mod makers

If VMC's Lua events, or the game's own, do what you need, make a plain Lua mod: it works with Bazaar just as it would with VMC on its own. Write a plugin when you need C++. A plugin can run its own code before, after or instead of almost any function in the game's DLL, or at a few extra spots placed by hand inside some of them. It can add Lua functions of its own, and keep data in saved games: values on players, cities, units and plots, which it can let other plugins and Lua mods read, and data of its own.

- **The SDK** comes with each release on the Releases page, as `Bazaar-SDK-<version>.zip`: the game's headers, the libraries to link against, Bazaar's compiler settings and a template plugin to start from. Its guide, [sdk/README.md](sdk/README.md), goes from what to install to publishing on the Steam Workshop.
- **The developer docs** have a page for each game function plugins can hook. The newest release's docs are at https://spradlin-dev-bazaar.github.io/civ5-bazaar/, and each release has them as `Bazaar-docs-<version>.zip`.
- **With Claude Code**, add this repository's skills with `/plugin marketplace add spradlin-dev-bazaar/civ5-bazaar`, then `/plugin install civ5-bazaar@civ5-bazaar`. One skill makes DLL plugins, including from an existing DLL mod; the other makes Lua mods from its own template.

A plugin runs only on Bazaar releases with the same major version as the one it was built for (the first number, such as the 1 in 1.2), from that release on: a plugin built for 1.2 runs on 1.5, but not on 1.1 or 2.0. Releases before 0.5 could also change what plugins use, so Bazaar 0.5 and later refuse a plugin built for one of them until it is rebuilt with a newer SDK.

## Building and testing

You need Visual Studio 2008 (the free Express edition works) and Python 3.12.

1. Set up the Python tools once: `python -m venv .venv`, then `.venv\Scripts\pip install -r tools\generator\requirements.txt`.
2. `build-hooked.cmd` makes the hook wrappers, checks that the game classes plugins rely on still have the same layout in memory, and builds Bazaar's DLL.
3. `tests\runtime\run.cmd` runs the automated tests, outside the game. `.venv\Scripts\python.exe -m ruff check .` and `.venv\Scripts\python.exe -m ruff format --check .` check the Python code.
4. `tests\ingame\package.py` lays out Bazaar, the VMC Bootstrap and the test plugins as mod folders in `tests\ingame\out\MODS`, to copy into the game's MODS folder. [tests/ingame/README.md](tests/ingame/README.md) says what each test plugin should show in the game.

Other jobs:

- `sdk\build_sdk.py` lays out the plugin SDK in `sdk\out\Bazaar SDK`, then checks it by making a plugin from its template and releasing it, using only that folder. That check builds a plugin, so it also needs what a plugin author needs (see [What you need](sdk/README.md#what-you-need)).
- `build-docs.cmd` writes the developer docs into `CvGameCoreSource\BuildTemp\docs`; open its `index.html` in a browser. `tests\docs\check_docs.py` checks the docs build against a small test engine. [tools/docs/README.md](tools/docs/README.md) explains how to write the docs' own pages.
- `tests\ingame\pack.py` packs one folder from `tests\ingame\out\MODS` into a package, for a test upload to the Steam Workshop.
- To measure how much Bazaar slows down the computer players, build with the `bench` option (`build-dll.cmd bench`, `build-hooked.cmd bench`) and lay out with `package.py bench plain` or `package.py bench host`. `build-dll.cmd` builds the game DLL without Bazaar (Firaxis's source with VMC's changes); only this measurement needs it. [Issue #3](https://github.com/spradlin-dev-bazaar/civ5-bazaar/issues/3) has the results.

## Making a release

A release is made on the developer's machine with `tools\release.py`, in four steps: `number`, `prepare`, `build` and `publish`. In Claude Code, the release skill in `.claude\skills\release` walks through them, together with what a person does in between: checking the release in the game, approving the release notes, and uploading to the Steam Workshop with the descriptions in `workshop\`. The plan explains each step under [Making a release](docs/plugin-host.md#making-a-release).

## Credits and licence

- Game source code: Firaxis Games and Take-Two Interactive, from the Civilization V SDK. All rights reserved by them.
- DLL-VMC: whoward69, used under his terms (never sold or used to make money).
- Everything this repository adds: MIT. See [NOTICE](NOTICE) for exactly what that covers.

The mod as a whole may not be sold.
