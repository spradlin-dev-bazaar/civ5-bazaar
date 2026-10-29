---
name: release
description: Make a release of Bazaar, the Civilization V multi-DLL mod loader, with tools/release.py, from choosing the number to the draft GitHub release, the in-game check and the Steam Workshop upload. Use when asked to make, prepare, build or publish a Bazaar release or pre-release, or to work out the next release number.
---

# Making a Bazaar release

`tools/release.py` does the repeatable work of a release; this skill adds the steps around it that need a person or judgment. The commands below are for PowerShell, run from the repository root with the project's Python, `.venv\Scripts\python.exe`. When something is not as the script expects, it stops with a message that says what to do: follow the message, and do not work around it.

Ask the developer before each step that publishes something or changes git: committing, pushing, opening the pull request, running `publish`, which pushes a tag, and running `workshop`, which updates Bazaar's item on the Steam Workshop. Show every text other people will read, word for word, and get it approved before using it: the release branch's commit message and pull request, and the release notes.

## 1. Choose the number

1. On main, up to date with GitHub and with nothing uncommitted, run `.\build-hooked.cmd`, then `.venv\Scripts\python.exe tools\release.py number`.
2. Tell the developer the number it gives and why, in a few plain sentences: what was added, removed or changed since the last release. If it says every plugin must be rebuilt, say so. The first release has nothing to compare with and keeps the numbers in `VERSION`.
3. Ask whether that is the release they want. From 0.5 on, removing or changing anything plugins use needs a new major version; if the developer wants one, add `--major` in the next step.

## 2. Prepare

1. Run `.venv\Scripts\python.exe tools\release.py prepare`, with `--major` if chosen. It builds the host, runs the tests and the lint, raises the numbers, saves the lists and the docs' function history, and leaves the changes on a new branch, `release-<number>`. It takes a while.
2. Draft the commit message, titled "Prepare release <number>" with a few plain lines on what the release holds, and the pull request description. Once they are approved, commit, push the branch and open the pull request to main.
3. Wait for the developer to merge it. Then pull main and delete the local branch with `git branch -d release-<number>`: the next `prepare` refuses while it is there.

## 3. Build

1. On main, run `.venv\Scripts\python.exe tools\release.py build`. It builds everything again and writes the four release files into `dist\v<number>\`: Bazaar's mod and the VMC Bootstrap as `.civ5mod` packages, the SDK zip and the docs zip.
2. If it stops because building changed some files, usually the docs' function history after a function moved within its file, those changes go to main through a pull request of their own. Then run `build` again.

## 4. Check in the game

Run `.venv\Scripts\python.exe tools\release.py check`. With nobody at the keyboard, it builds the template plugin from the release's SDK zip, puts the release's two packages and the template into MODS, and starts Civilization V through Steam. It checks that Bazaar's description in the Mods menu names the release and that the template loaded for the release's API, then plays the template's own `checks.toml`, the file plugin authors start from: a turn, the template's log line and its Lua function. It also checks that no plugin crashed and `Lua.log` has no Lua errors. Then it closes the game and puts back the developer's Mods menu, plugin order, `config.ini` and autosaves; the release's two mods and the template stay in MODS. It takes a few minutes and needs Civilization V closed, `EnableTuner = 1` and `LoggingEnabled = 1` in its `config.ini`, and DirectX 11 chosen the last time the game was started from Steam.

When it passes, it marks the build as checked, and `publish` refuses a build without the mark; a later check that fails takes the mark away. It stops at once if the SDK's copy of the checker differs from `tools\bazaar_check`. Skip it when Bazaar's mod is the same as at the last release apart from its version number and the release its description names, as in a release that only updates the SDK or the docs; `publish` then needs `--no-check`.

When Bazaar's own code changed since the last release, also run `.venv\Scripts\python.exe tests\ingame\run.py`, which checks the test plugins in the game in about ten minutes; it works on any branch. The release's files can be checked before step 2 too: `release.py build --trial`, then `release.py check --trial`.

If anything fails, stop. The fix goes to main through a pull request, and the release starts again at step 1, since the fix may change the number.

## 5. Release notes

Draft the notes in Markdown, in two parts:

- **For players:** what changed in the game, in plain words. Say "the AI", and never name code or tools.
- **For plugin authors:** what was added to what plugins use (hooks, exported functions, `CivPluginApi.h`) and what was removed or changed. When anything was removed or changed, start with the fact that every plugin must be rebuilt for this release.

Work from what `number` listed, `git log v<last release>..HEAD`, and the pull requests and issues closed since the last release. Once the notes are approved, save them as `dist\notes-v<number>.md`: git ignores `dist\`, `publish` needs a clean tree, and `build` empties `dist\v<number>\` each time it runs.

## 6. Publish

1. With the developer's go-ahead, run `.venv\Scripts\python.exe tools\release.py publish --notes dist\notes-v<number>.md`. It tags the commit the files were built from, pushes the tag, and creates the GitHub release as a draft with the four files attached, marked as a pre-release when it is older than 0.5. If it stops part way, follow its message: running it again is safe.
2. The developer checks the draft on GitHub and publishes it. Publishing starts the GitHub Action that puts the docs site on GitHub Pages; check that the Action's run succeeded and that the site opens.

## 7. Steam Workshop

Every release that changes Bazaar's mod, pre-releases included, updates Bazaar's item on the Steam Workshop. A release that only updates the SDK or the docs is not uploaded and gets no change note, since the Workshop page points to GitHub for both.

1. Add the release's notes to the top of `workshop\changes.txt` in BBCode, under a `[b]<number>[/b]` line and without the install paragraph or the file names, and get them approved. They go to main through a small pull request.
2. Once it has merged, pull main. With the developer's go-ahead, run `.venv\Scripts\python.exe tools\release.py workshop`. It needs Steam running and signed in to the account that owns the item, and the Sid Meier's Civilization V SDK installed from Steam; ModBuddy itself need not be open. It uploads Bazaar's package with the release's own section of `workshop\changes.txt` as the change note and `workshop\bazaar.txt` as the item's description, then checks that Steam shows the new file.
3. If the VMC Bootstrap has changed, the developer uploads it with ModBuddy, by hand, pasting the description from `workshop\vmc-bootstrap.txt`.

A new major version goes up as new Workshop items, published with ModBuddy, not as an update: games saved with the old version need its mod, so the old items stay up. The new item's number then goes into `tools\workshop\upload.py`, so that `workshop` updates it.
