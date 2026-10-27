---
name: release
description: Make a release of Bazaar, the Civilization V multi-DLL mod loader, with tools/release.py, from choosing the number to the draft GitHub release, the in-game check and the Steam Workshop upload. Use when asked to make, prepare, build or publish a Bazaar release or pre-release, or to work out the next release number.
---

# Making a Bazaar release

`tools/release.py` does the repeatable work of a release; this skill adds the steps around it that need a person or judgment. The section "Making a release" in `docs/plugin-host.md` says why each step exists. The commands below are for PowerShell, run from the repository root with the project's Python, `.venv\Scripts\python.exe`. When something is not as the script expects, it stops with a message that says what to do: follow the message, and do not work around it.

Ask the developer before each step that publishes something or changes git: committing, pushing, opening the pull request, and `publish`, which pushes a tag. Show every text other people will read, word for word, and get it approved before using it: the release branch's commit message and pull request, and the release notes.

## 1. Choose the number

1. On main, up to date with GitHub and with nothing uncommitted, run `.\build-hooked.cmd`, then `.venv\Scripts\python.exe tools\release.py number`.
2. Tell the developer the number it gives and why, in a few plain sentences: what was added, removed or changed since the last release. If it says every plugin must be rebuilt, say so. The first release has nothing to compare with and keeps the numbers in `VERSION`.
3. Ask whether that is the release they want. From 0.5 on, removing or changing anything plugins use needs a new major version; if the developer wants one, add `--major` in the next step.
4. Before the second release, when Bazaar's mod version first goes up, check with the developer that the save check at the end of the plan's "Making a release" has been done: a save made with the first release must still load after the player updates to the second. If it has not, do it as part of this release's in-game check, before publishing.

## 2. Prepare

1. Run `.venv\Scripts\python.exe tools\release.py prepare`, with `--major` if chosen. It builds the host, runs the tests and the lint, raises the numbers, saves the lists and the docs' function history, and leaves the changes on a new branch, `release-<number>`. It takes a while.
2. Draft the commit message, titled "Prepare release <number>" with a few plain lines on what the release holds, and the pull request description. Once they are approved, commit, push the branch and open the pull request to main.
3. Wait for the developer to merge it. Then pull main and delete the local branch with `git branch -d release-<number>`: the next `prepare` refuses while it is there.

## 3. Build

1. On main, run `.venv\Scripts\python.exe tools\release.py build`. It builds everything again and writes the four release files into `dist\v<number>\`: Bazaar's mod and the VMC Bootstrap as `.civ5mod` packages, the SDK zip and the docs zip.
2. If it stops because building changed some files, usually the docs' function history after a function moved within its file, those changes go to main through a pull request of their own. Then run `build` again.

## 4. Check in the game

This step is the developer's: explain it, then wait for the result. Skip it when Bazaar's mod is the same as at the last release apart from its version number, as in a release that only updates the SDK or the docs.

1. Move any other Bazaar folders, such as test builds, out of `Documents\My Games\Sid Meier's Civilization 5\MODS`.
2. Copy the two `.civ5mod` files from `dist\v<number>\` into MODS. The game unpacks them when it starts.
3. Unzip the SDK zip into a folder outside the repository, run `Bazaar SDK\plugin-template\build.cmd` there, and copy the folder it makes, `Build\Template Plugin`, into MODS.
4. In the game's Mods menu, turn on Bazaar - VMC Bootstrap (required), Bazaar Multi-DLL Mod Loader and Template Plugin, and start a game.
5. `Documents\My Games\Sid Meier's Civilization 5\Logs\Bazaar.log` must show `Plugin Template Plugin 1 loaded`, and a line from the template at the start of each turn.

If anything fails, stop. The fix goes to main through a pull request, and the release starts again at step 1, since the fix may change the number.

## 5. Release notes

Draft the notes in Markdown, in two parts:

- **For players:** what changed in the game, in plain words. Say "the AI", and never name code or tools.
- **For plugin authors:** what was added to what plugins use (hooks, exported functions, `CivPluginApi.h`) and what was removed or changed. When anything was removed or changed, start with the fact that every plugin must be rebuilt for this release.

Work from what `number` listed, `git log v<last release>..HEAD`, and the pull requests and issues closed since the last release. Once the notes are approved, save them as `dist\notes-v<number>.md`: git ignores `dist\`, `publish` needs a clean tree, and `build` empties `dist\v<number>\` each time it runs.

## 6. Publish

1. With the developer's go-ahead, run `.venv\Scripts\python.exe tools\release.py publish --notes dist\notes-v<number>.md`. It tags the commit the files were built from, pushes the tag, and creates the GitHub release as a draft with the four files attached, marked as a pre-release when it is older than 0.5. If it stops part way, follow its message: running it again is safe.
2. The developer checks the draft on GitHub and publishes it. Publishing starts the GitHub Action that puts the docs site on GitHub Pages; check that the Action's run succeeded and that the site opens.
3. After 0.5.0, the first public release, rewrite the README's Status section, which still calls Bazaar a pre-release.

## 7. Steam Workshop

The developer uploads every release that changes Bazaar's mod, pre-releases included, with ModBuddy, by hand: Bazaar's package each time, pasting the description from `workshop\bazaar.txt`, and the VMC Bootstrap, with `workshop\vmc-bootstrap.txt`, only when it has changed. A release that only updates the SDK or the docs is not uploaded and gets no change note, since the Workshop page points to GitHub for both. Before the upload, add the release's notes to the top of `workshop\changes.txt` in BBCode, without the install paragraph or the file names, and get them approved; the developer pastes that section as the update's change note, and it goes to main through a small pull request. Before 0.5 the Workshop items stay private. Making them public is the first public release, 0.5.0, and the repository on GitHub goes public with it: remind the developer.
