---
name: new-lua-mod
description: Create or build a Lua mod for Civilization V that runs under Bazaar, the multi-DLL mod loader, using VMC's extra Lua events (GameEvents) or the base game's. Covers finding the event, switching on the VMC option it needs, starting from this skill's Lua mod template, and building the mod and its Workshop package. Use this whenever someone wants a Civ 5 Lua mod for Bazaar, wants to react to a game event in Lua, mentions GameEvents, CustomModOptions or a VMC event, or asks for something a Lua mod can do without C++, even if they do not say "Lua mod".
argument-hint: "<Display Name>" [what it should do]
---

# New Bazaar Lua mod

Bazaar is built on whoward69's Various Mod Components (VMC), so a Lua mod under Bazaar gets VMC's extra events as well as the base game's. Every VMC event starts switched off: a mod switches it on in its SQL, through VMC's `CustomModOptions` table, or the event never fires. This skill makes the mod from a template, so that the project file, the dependency on Bazaar and the build script come out right, then writes the Lua.

## 1. Find the event

Search `${CLAUDE_SKILL_DIR}/references/vmc-events.md` for what the mod should react to. It is generated from VMC's own notes and Bazaar's engine source, and lists:

- VMC's events, under the option that switches each one on, with their arguments and their kind (hook, test-all, test-any or value);
- VMC's events that its notes leave out, with the option that switches each one on, but only the types of their arguments;
- the base game's events, which are always on and need no option, with the expressions the engine passes as their arguments;
- VMC's other options, which change rules or add Lua functions. Those marked **on by default** need no SQL; those marked **number** hold a number, not on or off.

Believe its warnings:

- **never fired**: nothing calls the event, so a mod cannot rely on it.
- **misnamed in VMC's notes**: subscribe by the code's name, not the notes'.
- **Also needs**: the code checks a second option too. Switch both on, or the event never fires.
- **Always on**: the event fires even with its option off, but then with the base game's arguments. Switch the option on to get the arguments listed under it.
- **Argument count differs**: VMC's notes and code disagree. Use only the arguments both agree on.

If no event fits, or the mod has to change a rule that no event or option offers, a Lua mod cannot do it. Say so, and suggest a Bazaar DLL plugin instead (the `new-dll-plugin` skill).

## 2. Make the mod folder with the script

The folder has to come out exactly right, and copying and renaming by hand varies from run to run, so a script does it:

```
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "${CLAUDE_SKILL_DIR}/scripts/new-lua-mod.ps1" -DisplayName "Turn Logger" -Options "EVENTS_PLAYER_TURN" -Destination "<parent folder>" -Description "<one sentence>" -Author "<name>"
```

- **`-DisplayName`** is what players see in the Mods menu; it also names the `Build` folder and the package. Ask the user for it if they have not given one. The file name comes from it, so `Turn Logger` becomes `TurnLogger`; pass `-FileName` only when the user wants a different one.
- **`-Options`** lists the VMC options to switch on, comma-separated and spelled exactly as the reference names them, or `none` when the mod uses only base-game events. The script requires it. It refuses a name VMC does not have, because a misspelled option fails silently and the event just never fires. It also refuses an option that holds a number; set one of those with its own `UPDATE` line, as the reference shows.
- **`-Author`** names the mod's author. Ask the user for it if they have not given one; left out, the template's placeholder `Your name` stays in the `.civ5proj`.
- **`-Destination`** is the folder to make the mod folder in; it defaults to the current folder. Keep the path short: ModBuddy's build fails once a path inside the mod folder passes 260 characters.

The script copies the template, renames it, gives the mod a new ID on the `<Guid>` line (`<ProjectGuid>` stays), sets the teaser, description and authors, and writes the SQL. Do not redo or "fix" any of that by hand. If the script fails, read its message and fix the cause. If the mod turns out to need another option later, add an `UPDATE` line of the same form to the `.sql`, with the option's name exactly as the reference gives it.

The template's project file makes the mod depend on Bazaar, which also makes the game load it after VMC's database files, so the SQL finds `CustomModOptions`. It also marks the mod as affecting saved games. Keep that: the SQL is a database change, and a loaded save applies the database changes only of the mods it lists.

## 3. Write the Lua

- Replace the template's example in `mod\<FileName>.lua` with the mod's code. The file runs in the game as an `InGameUIAddin`, so the game's Lua API (`Players`, `Game`, `Map`, `GameInfo`) is there.
- Subscribe with `GameEvents.<Name>.Add(function(<arguments>) ... end)`, taking the arguments in the order the reference gives.
- What the handler returns depends on the event's kind:
  - **hook**: nothing;
  - **test-all**: `true` to allow, `false` to forbid. Any `false` forbids, so return `true` in every case the mod does not mean to block;
  - **test-any**: `true` only in the cases the mod means to say yes to;
  - **value**: the number the reference describes.
- `print(...)` writes to `Logs\Lua.log`, but only once the game's logging is on: `LoggingEnabled = 1` in `config.ini`, in `Documents\My Games\Sid Meier's Civilization 5`.

## 4. Build and report

- Run `build.cmd` by its full path. It needs the Civilization V SDK's ModBuddy build steps, not Visual C++. From PowerShell: `& '<full path of the mod folder>\build.cmd'`. From Git Bash: `cmd //c '<full path of the mod folder>\build.cmd'`; write `//c`, because Git Bash turns `/c` into a drive path, and give the full path, because `cmd` does not find `build.cmd` by its bare name there.
- If it stops early, it says why:

  | Message | What it means |
  |---|---|
  | `No mod name was found in mod\<FileName>.civ5proj.` | The `.civ5proj` has no `<Name>` line. The build names the mod folder after it. |
  | Civilization V was not found in the registry. | The script looked up where Steam installed Civilization V and found nothing. |
  | Your Documents folder was not found. | Windows did not report the Documents folder, so the build cannot find `My Games\Sid Meier's Civilization 5`. |
  | error MSB4019: The imported project "…\Firaxis\ModBuddy\Civ5Mod.targets" was not found. | ModBuddy's build steps are not installed yet. Start ModBuddy once from the Civilization V SDK, then build again. |
  | The "GenerateModInfo" task failed unexpectedly, with System.IO.PathTooLongException. | The mod folder's path is too long. Move the mod folder to a folder with a shorter path and build again. |

- Report the files it made (`Build\<Display Name>\`, holding the `.modinfo`, `.lua` and `.sql`, and `Packages\<Display Name> (v N).civ5mod`). Then tell the user how to test in the game: copy `Build\<Display Name>`, the built mod, into MODS (not the folder the script made, which holds the project files); enable Bazaar - VMC Bootstrap (required), the Bazaar Multi-DLL Mod Loader and the mod; and, if the mod prints, turn on logging and look in `Logs\Lua.log`.
- Do not copy anything into MODS or start the game unless the user asks: installing mods is theirs to do.

## Mods made for VMC itself

A mod written for whoward's own VMC references VMC's mod ID instead of depending on Bazaar. It works under Bazaar unchanged, because Bazaar's VMC Bootstrap carries VMC's mod ID, so there is nothing to port.
