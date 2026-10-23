# Bazaar Multi-DLL Mod Loader

A DLL mod for Civilization V: Brave New World that lets you run more than one DLL mod at a time.

Civ5 loads only one game DLL, so normally you can use only one DLL mod at once. This mod replaces the game DLL with a "host" that loads other DLL mods as plugins. Each plugin is its own mod, installed from the Steam Workshop or by hand, and you choose which plugins run and in what order.

## Status

The proof of concept works: built from the plain Firaxis source, the host loads plugin DLLs, lets them hook any engine function, and survives a plugin that crashes. It has been tested in the game with small test plugins. Nothing is released yet, and there is no SDK or real plugin yet. The calls from the game into the host live on the `p0` branch until the next phase, so a host built from `main` does not load plugins yet. The full plan is in [docs/plugin-host.md](docs/plugin-host.md).

## How it will work

- The host is built on whoward69's DLL-VMC (v97), so it keeps VMC's Lua events and switchable bug fixes. A mod that only needs a Lua event can stay a plain Lua mod.
- A plugin is an ordinary mod with a DLL inside. It lists the host as a requirement, so the game won't let you turn it on without the host.
- A Plugins screen shows which plugins loaded and any that failed or were refused, and lets you reorder them or skip any of them. It opens in place of Advanced Setup (Mods > Single Player > Set Up Game > Advanced Setup), and its Continue button then opens the usual Advanced Setup, or another mod's version of it such as Really Advanced Setup's.
- If a plugin crashes, the host turns it off until you return to the main menu and tells you. The game keeps running.
- A plugin built for an older host keeps working on newer hosts.

## For plugin authors

Each host release will come with an SDK: the game headers, an import library, the exact compiler settings the host uses, and a template plugin to start from.

## Building and testing

You need Visual Studio 2008 (the free Express edition works) and Python 3.12.

1. Set up the Python tools once: `python -m venv .venv`, then `.venv\Scripts\pip install -r tools\generator\requirements.txt`.
2. `build-dll.cmd` builds the plain game DLL from the Firaxis source.
3. `build-hooked.cmd` generates the hook wrappers and builds the host DLL.
4. `tests\runtime\run.cmd` runs the automated tests, outside the game.
5. `tests\ingame\package.py` lays out the host and the test plugins as mod folders in `tests\ingame\out\MODS`, ready to copy into the game's MODS folder.

To measure how much the host slows down the computer players, build with the `bench` option (`build-dll.cmd bench`, `build-hooked.cmd bench`) and package with `package.py bench plain` or `package.py bench host`. Issue #3 has the results so far. Until P1 this works only on the `p0` branch, which has the engine's call into the timer.

## Limits

- It can't run alongside another mod that replaces the game DLL, such as the Community Patch.
- Single player only.

## Credits and licence

- Game source code: Firaxis Games and Take-Two Interactive, from the Civilization V SDK. All rights reserved by them.
- DLL-VMC: whoward69, used under his terms (credit given, never sold, its own mod ID).
- Everything this repository adds: MIT. See [NOTICE](NOTICE) for exactly what that covers.

The mod as a whole may not be sold.
