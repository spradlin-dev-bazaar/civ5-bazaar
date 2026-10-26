---
name: new-dll-plugin
description: Create, build or port a C++ DLL plugin for Bazaar, the multi-DLL mod loader for Civilization V. Covers starting from the Bazaar SDK's template, finding and writing hooks on the game's functions, adding Lua functions, building with the template's build script, and making releases for the Steam Workshop. Use this whenever someone wants to change how Civ 5 plays with C++ under Bazaar, write or fix a Bazaar plugin, hook a CvPlayer, CvCity or CvUnit function, or turn an existing Civ 5 DLL mod (a modified CvGameCore_Expansion2.dll) into a Bazaar plugin, even if they do not say "plugin".
argument-hint: "<Display Name>" [what it should do]
---

# New Bazaar DLL plugin

Bazaar replaces Civilization V's core DLL and loads plugin DLLs that hook the game's functions. The Bazaar SDK holds everything a plugin needs, and its `README.md` is the guide: the hook rules, the template, and how to build, test and publish. This skill is the procedure. The guide is the source of truth, because it changes with the SDK, so read it rather than relying on memory or on this file.

## 1. Find the SDK and read the guide

- The SDK is the folder named by the `BAZAAR_SDK` environment variable. If that is unset, ask the user where the Bazaar SDK is. In Bazaar's own repository it is `sdk\out\Bazaar SDK`, which running `sdk\build_sdk.py` after a host build lays out.
- Read `%BAZAAR_SDK%\README.md` in full before writing any code, and `%BAZAAR_SDK%\hand-placed-hooks.md` when choosing hooks. The parameter rules and vetoes are easy to get subtly wrong.
- Check the guide's "What you need" against the machine: `%VS90COMNTOOLS%` set (Visual C++ 2008), the Civilization V SDK, and ModBuddy's build steps in `C:\Program Files (x86)\MSBuild\Firaxis\ModBuddy\Civ5Mod.targets`. If something is missing, tell the user what to install, using the guide's links. Installing software is their call.

## 2. Make the plugin folder with the script

The folder has to come out exactly right, and copying and renaming by hand varies from run to run, so a script does it:

```
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "${CLAUDE_SKILL_DIR}/scripts/new-dll-plugin.ps1" -DisplayName "Score Doubler" -Destination "<parent folder>" -Description "<one sentence>" -Author "<name>"
```

- **`-DisplayName`** is what players see: the mod's name in the Mods menu, the `Build` folder's and the package's name, and the name the plugin reports to Bazaar. Ask the user for it if they have not given one.
- **The file name** (the DLL's and the project's name, with no spaces) comes from the display name, so `Score Doubler` becomes `ScoreDoubler`. Pass `-FileName` only when the user wants a different one. No other mod may ship a DLL with the same name, because Bazaar finds plugins by file name.
- **`-Destination`** is the folder to make the plugin folder in; it defaults to the current folder. The script refuses only a folder inside the SDK that Bazaar's own repository builds, since that build deletes and rebuilds it. Keep the path short: Visual C++ 2008 fails once a path inside the plugin folder passes 260 characters, with PRJ0020 at the link step. If that happens, make the plugin in a folder with a shorter path, rather than shortening the plugin's name.
- **`-Author`** names the mod's author. Ask the user for it if they have not given one; left out, the template's placeholder `Your name` stays in the `.civ5proj`, and `release.cmd` refuses to make a release until it is changed.
- **`-Sdk`** is needed only when `BAZAAR_SDK` is not set.

The script copies the template without its build output, renames the files, puts the names into the text files, writes a new mod ID in the `<Guid>` (`<ProjectGuid>` stays), and sets the teaser, description and authors; the description also replaces the template's sentence in `workshop-description.txt`. Do not redo or "fix" any of that by hand. If the script fails, read its message and fix the cause.

Then delete the template's example hooks that the plugin does not need, as the guide's Step 2 describes.

## 3. Write the hooks

- Choose the kind of hook as the guide's "Which kind of hook to use" says. If one of VMC's Lua events already does the job, tell the user a plain Lua mod is enough before writing C++.
- Find the function in `%BAZAAR_SDK%\include\CivHooks.h` by searching for `Class::Method(`, not for a single word.
- Build the hook's parameter list from that function's block, with the guide's table: `self` and whether it is const, every parameter in order, `result` as a reference, and a reference to a pointer for functions that return a reference. Register it with `CivRegisterBefore`, `CivRegisterAfter` or `CivRegisterReplace`, so the compiler checks the list against the block's types. A block with no types needs `host->RegisterHook`, which checks nothing: there a wrong list is caught only when the game crashes or reads garbage, so check it twice.
- When the behaviour matters, read the function's code, not just its name. For example, `CvCity::CreateBuilding` also runs when a building is bought. The SDK has headers only. The closest code is Bazaar's own source, which is based on VMC; the Civilization V SDK's `CvGameCoreSource` has Firaxis's original.
- Register each hook in `CivPluginEntry` with the template's `Check(...)`, so a failed registration shows in `Bazaar.log`.

## 4. Build and report

- Run `build.cmd` by its full path, with `BAZAAR_SDK` set for that session only. From PowerShell: `$env:BAZAAR_SDK = '<SDK folder>'; & '<full path of the plugin folder>\build.cmd'`. From Git Bash: `BAZAAR_SDK='<SDK folder>' cmd //c '<full path of the plugin folder>\build.cmd'`; write `//c`, because Git Bash turns `/c` into a drive path, and give the full path, because `cmd` does not find `build.cmd` by its bare name there. Set it permanently only if the user asks, since that changes their Windows settings. Fix what the build reports; the guide's Step 1 table explains its messages.
- Report the files it made (`Build\<Display Name>\` and `Packages\<Display Name> (v N).civ5mod`). Then tell the user how to test in the game: copy `Build\<Display Name>`, the built mod, into MODS (not the folder the script made, which holds the source); enable Bazaar - VMC Bootstrap (required), the Bazaar Multi-DLL Mod Loader and the plugin; look for `Plugin <name> <version> loaded` in `Bazaar.log`.
- Do not copy anything into MODS or start the game unless the user asks: installing mods is theirs to do.

## 5. Releases

When the user wants to publish, follow the guide's Publishing section: set the release in `VERSION`, add its notes to the top of `CHANGES.txt` in BBCode, and run `release.cmd` by its full path, as with `build.cmd`. It sets the version, builds, checks the package and keeps it in `Releases\<release>\`. If it refuses, read its message and fix the cause. Never delete or rename anything in `Releases\` to get past a check: it is the record of what was released. Uploading to the Steam Workshop is the user's step, in ModBuddy. If the plugin folder has no `release.cmd`, it was made from an older Bazaar SDK: tell the user that releases need the newest one, and follow that SDK's guide.

## Porting an existing DLL mod

When the user is turning a modified core DLL into a plugin:

1. List every edit the mod made to the game's code, by comparing it with the code it was built from (Firaxis's, or VMC v97's).
2. Map each edit to a hook:
   - code at the start or end of a function becomes a before-hook or an after-hook;
   - code in the middle becomes a hand-placed hook if one exists, and otherwise a request for one or, as a last resort, a replacement;
   - `Game.*` Lua methods added in `CvLuaGame.cpp` become an after-hook on `CvLuaGame::RegisterMembers`, which pushes each one with `host->PushLuaFunction` so that it runs inside Bazaar's crash protection.
3. Flag code that reads or writes private or protected members: a plugin cannot reach them yet, so it needs another route.
4. Show the user the list of edits and the hook each one becomes before writing code. That list is the port's design.
