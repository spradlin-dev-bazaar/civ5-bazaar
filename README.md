# Civ5 Plugin Host

A DLL mod for Civilization V: Brave New World that lets you run more than one DLL mod at a time.

Civ5 loads only one game DLL, so normally you can use only one DLL mod at once. This mod replaces the game DLL with a "host" that loads other DLL mods as plugins. Each plugin is its own mod, installed from the Steam Workshop or by hand, and you choose which plugins run and in what order.

## Status

Planned, not built yet. Nothing described here works yet. The full plan is in [docs/plugin-host.md](docs/plugin-host.md).

## How it will work

- The host is built on whoward69's DLL-VMC (v97), so it keeps VMC's Lua events and switchable bug fixes. A mod that only needs a Lua event can stay a plain Lua mod.
- A plugin is an ordinary mod with a DLL inside. It lists the host as a requirement, so the game won't let you turn it on without the host.
- A Plugins screen (Mods > Plugins) lets you reorder plugins or turn them off. It also shows any plugin that failed or was refused.
- If a plugin crashes, the host turns it off for the rest of the session and tells you. The game keeps running.
- A plugin built for an older host keeps working on newer hosts.

## For plugin authors

Each host release will come with an SDK: the game headers, an import library, the exact compiler settings the host uses, and a template plugin to start from.

## Limits

- It can't run alongside another mod that replaces the game DLL, such as the Community Patch.
- Single player only.

## Credits and licence

- Game source code: Firaxis Games and Take-Two Interactive, from the Civilization V SDK. All rights reserved by them.
- DLL-VMC: whoward69, used under his terms (credit given, never sold, its own mod ID).
- Everything this repository adds: MIT. See [NOTICE](NOTICE) for exactly what that covers.

The mod as a whole may not be sold.
