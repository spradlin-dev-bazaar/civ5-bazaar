# Bazaar lens

Applies to every run in this repository.

Bazaar is a replacement game core for Civilization V, Firaxis's engine with whoward69's VMC, that loads plugin DLLs which other people build against a released SDK. Most of the rules below exist because a plugin built months ago must keep working with today's Bazaar. docs/plugin-host.md holds the reasons; this lens holds the checks. Pitfalls in writing a plugin belong to the bazaar-plugin lens.

## Binary compatibility with built plugins

A plugin compiled against the SDK's headers and linked to Bazaar's exports breaks, usually by crashing, when any of these changes under it:
- the members, base classes or virtual functions of an engine class, or the values of an enum: inserting one moves everything after it;
- a structure in `host/CivPluginApi.h`, other than by adding at its end; `CivApiVersion` and its export name never change;
- the function or signature behind a hook number in `tools/generator/hook-ids.txt`;
- the name of anything Bazaar exported in a release.

Additions are fine. Before 1.0 a change is allowed when there is no other way, and the finding says every plugin must be rebuilt; from 1.0 on it needs a new major version.

## Build settings shared with plugins

Plugins build with the SDK's `CivPlugin.vsprops`, written by `sdk/build_sdk.py`, and the test plugins with the flags in `tests/ingame/package.py`; both take their defines from `tools/generator/common.py`, whose `ENGINE_DEFINES` is a hand copy of the engine project's. Flag a change to Bazaar's compiler settings, defines or libraries that doesn't reach all of them. The dangerous ones change memory layout on one side only:
- `_SECURE_SCL` and `_HAS_ITERATOR_DEBUGGING`, which change the size of `std::string` and `std::vector`; a file built without the precompiled header must repeat them;
- the character set: multi-byte, never Unicode;
- struct packing;
- the C runtime: both sides use the DLL runtime (`/MD`), or memory freed on the other side corrupts the heap.

## Calls into plugin code

Every call from Bazaar into a plugin goes through `GuardedCall` in `host/CivHostRuntime.cpp`, so a crash quarantines the plugin instead of ending the game. Flag:
- a new call into plugin code that bypasses it: a hook, an entry or shutdown function, anything a plugin registered;
- Bazaar state set before a guarded call and restored after it, which a crash leaves half-updated;
- any way a quarantined plugin's hooks run again before it is unloaded.

## Engine source

`CvGameCoreSource/` is Firaxis's code with VMC's changes, and Bazaar adds no fixes to it: an edit there is a call into Bazaar's own code (such as Bazaar's part of a save, with the save version that marks it), a hand-placed hook, a read-only accessor for state a plugin cannot otherwise reach, or nothing. Flag any other edit (a fix, a clean-up, a reformat): it changes the game for every mod and marks the function as changed in the developer docs.
- A new hand-placed hook needs its declaration in `host/CivPluginApi.h`, its section in `sdk/hand-placed-hooks.md` and a test in `tests/runtime/test_hand_hooks.cpp`.
- Hook wrappers are generated: change `tools/generator/`, never the generated copy.
- `CvGameCoreSource/`, `mod/vmc/` and `frontend/` keep Windows line endings. A diff that rewrites every line of a file means its line endings changed.
- The DLL's GUID (`MOD_DLL_GUID` in `CustomMods.h`) is what saves record, so it changes only by decision.

## Civilization V mod rules

These fail without any error the player sees, so only reading catches them:
- A failing SQL statement skips the rest of its file but keeps the statements before it; the only trace is a line in `Database.log`.
- The game decides the order mods run their SQL: mods with no reference to an enabled mod first, by folder name, then the rest in reference order. A mod that changes a table another mod creates must reference or depend on that mod; `CustomModOptions` exists only after Bazaar's VMC Bootstrap has run.
- A table that any of several mods may create first, like `DllPlugins`, is created with `CREATE TABLE IF NOT EXISTS` and the same columns everywhere.
- `AffectsSavedGames` must be 1 for a mod that changes the game's rules or database, or saves don't record it. The VMC Bootstrap keeps VMC's own values.

## Code that runs on other people's machines

Everything under `sdk/` and `claude-plugin/` ships to plugin authors. Flag:
- a path from this machine (`sdk/build_sdk.py` refuses one in the SDK; nothing checks `claude-plugin/`);
- an assumption that the game is in Steam's default folder, or that the Documents folder isn't redirected (OneDrive);
- a script that breaks in a folder whose path has spaces or parentheses (`Program Files (x86)`);
- a tool only this machine has.

## Where tests go

What a plugin can observe of Bazaar (loading, refusals, hook order, vetoes, crashes) is tested in `tests/runtime` against a fake engine; a change to it needs a test there. What only the game shows (the Plugins screen, mod load order, SQL, notifications) can't be tested there: the finding names the in-game check the change needs.
