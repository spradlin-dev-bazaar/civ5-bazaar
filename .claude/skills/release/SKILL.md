---
name: release
description: Make a release of Bazaar, the Civilization V multi-DLL mod loader, with tools/release.py, from choosing the number to the draft GitHub release, the in-game check and the Steam Workshop upload. Use when asked to make, prepare, build or publish a Bazaar release or pre-release, or to work out the next release number.
---

# Making a Bazaar release

`tools/release.py` does the repeatable work of a release. This skill adds the steps around it that need a person or judgment. The commands below are for PowerShell, run from the repository root with the project's Python, `.venv\Scripts\python.exe`. When something is not as the script expects, it stops with a message that says what to do: follow the message, and do not work around it.

Ask the developer before each step that publishes something or changes git: committing, pushing, opening the pull request, running `publish`, which pushes a tag, and running `workshop`, which updates Bazaar's item on the Steam Workshop. Show every text other people will read, word for word, and get it approved before using it: the release branch's commit message and pull request, and the release notes.

## 1. Choose the number

1. On the version's branch, up to date with GitHub and with nothing uncommitted, run `.\build-hooked.cmd`, then `.venv\Scripts\python.exe tools\release.py number`. A version of Bazaar is the first two numbers of a release, such as 0.5, and has its own git branch, named after the version with `.x`, such as `0.5.x`. `release.py` makes the releases of the version in `VERSION`, on that version's branch only.
2. Tell the developer the number it gives and why, in a few plain sentences: what was added, removed or changed since the last release. The first release has nothing to compare with and keeps the numbers in `VERSION`.
3. Ask whether that is the release they want. A release on a version's branch raises only the last number, such as 0.5.3 to 0.5.4. Removing or changing anything that plugins use requires the next version of Bazaar, made on its own branch. The first release of a new version is a breaking release, which `release.py` will learn to make later.
4. When the release changes only the SDK or the docs, it can keep the last release's Bazaar, so that players get no update with nothing in it. Ask whether the developer wants that. If so, run `number` again with `--same-bazaar`. It checks that Bazaar's code changed in nothing but comments since the release that made the current Bazaar, and that today's files would package that Bazaar the same way. If either fails, it names what changed, and the release needs a new Bazaar after all. If both pass, add `--same-bazaar` in the next step.

## 2. Prepare

1. Run `.venv\Scripts\python.exe tools\release.py prepare`, with `--same-bazaar` if chosen. Before it builds or changes anything, `prepare` checks that `.github/workflows/docs.yml` and `tools/docs/gather_site.py` on the version's branch are the same as on the default branch, and fails when they differ. When that check fails, copy both files from the default branch into the version's branch through a pull request, then run `prepare` again. It builds the host, raises the numbers, saves the lists and the docs' function history, and leaves the changes on a new branch, `release-<number>`. Then it runs the tests and the lint on that branch, so that they check the release at its own numbers. It takes a while. If a check fails, `prepare` stops and leaves the branch as it is: fix what failed there, run all the checks again, as its message says, and commit the fix with the release. If the fix changes Bazaar's own code, start again from the version's branch instead. A release that keeps Bazaar keeps its mod version and adds no row to `VERSIONS.md`.
2. Draft the commit message, titled "Prepare release <number>" with a few plain lines on what the release holds, and the pull request description. Once they are approved, commit, push the branch and open the pull request to the version's branch.
3. Wait for the developer to merge it. Then pull the version's branch and delete the local branch with `git branch -d release-<number>`: the next `prepare` refuses while it is there.

## 3. Build

1. On the version's branch, run `.venv\Scripts\python.exe tools\release.py build`. It builds everything again and writes the four release files into `dist\v<number>\`: Bazaar's mod and the VMC Bootstrap as `.civ5mod` packages, the SDK zip and the docs zip. The releases of 0.5 only fix things, so on the 0.5 branch `build` refuses a build that adds anything that plugins use. On every branch, `build` refuses a build that removes or changes anything that plugins use, which requires the next version of Bazaar, made on its own branch. `build` also stops if the VMC Bootstrap's files would differ from those of the release that made the last Bazaar: every version of Bazaar shares the one VMC Bootstrap, on its one Workshop item, so no release may change it. A release that keeps Bazaar gets only the SDK zip, and the docs zip only when the docs differ from the last release's. `build` checks again that Bazaar is the same.
2. If it stops because building changed some files, usually the docs' function history after a function moved within its file, those changes go to the version's branch through a pull request of their own. Then run `build` again.

## 4. Check in the game

Run `.venv\Scripts\python.exe tools\release.py check`. It runs automated tests in the game: it builds the template plugin from the release's SDK zip, puts the release's two packages and the template into MODS, and starts Civilization V through Steam. A release that keeps Bazaar uses the packages of the release that made it, from `dist` or downloaded from GitHub. It checks that Bazaar's description in the Mods menu names the release, except for a release that keeps Bazaar, and that the template loaded for the release's API, then plays the template's own `checks.toml`, the file plugin authors start from: a turn, the template's log line and its Lua function. It also checks that no plugin crashed and `Lua.log` has no Lua errors. Then it closes the game and puts back everything it changed in the developer's Civilization V folder, MODS included. It takes a few minutes and needs Civilization V closed, `EnableTuner = 1` and `LoggingEnabled = 1` in its `config.ini`, and DirectX 11 chosen the last time the game was started from Steam.

When it passes, it marks the build as checked, and `publish` refuses a build without the mark. A later check that fails takes the mark away. It stops at once if the SDK's copy of the checker differs from `tools\bazaar_check`. Skip it only for a release that changes nothing but the docs. `publish` then needs `--no-check`. A release that changes the SDK runs it, since the SDK holds the checker, which only this check runs in the game.

When Bazaar's own code changed since the last release, also run `.venv\Scripts\python.exe tests\ingame\run.py`, which checks the test plugins in the game in about ten minutes. It works on any branch. The release's files can be checked before step 2 too: `release.py build --trial`, then `release.py check --trial`.

If anything fails, stop. The fix goes to the version's branch through a pull request, and the release starts again at step 1, since the fix may change the number.

## 5. Release notes

Draft the notes in Markdown, in two parts:

- **For players:** what changed in the game, in plain words. Say "the AI", and never name code or tools.
- **For plugin authors:** what was added to what plugins use (hooks, exported functions, `CivPluginApi.h`) and what was removed or changed.

Work from what `number` listed, `git log v<last release>..HEAD`, and the pull requests and issues closed since the last release. Once the notes are approved, save them as `dist\notes-v<number>.md`: git ignores `dist\`, `publish` needs a clean tree, and `build` empties `dist\v<number>\` each time it runs.

For a release that keeps Bazaar, say at the top that Bazaar itself is unchanged, name the release whose Bazaar players keep, and point to it for Bazaar's packages and, when this release has no docs zip, for the docs. `publish` refuses notes that do not name that release.

## 6. Publish

1. With the developer's go-ahead, run `.venv\Scripts\python.exe tools\release.py publish --notes dist\notes-v<number>.md`. It tags the commit the files were built from, pushes the tag, and creates the GitHub release as a draft with the release's files attached, as a pre-release when its version of Bazaar is not on the Steam Workshop (0.6, 0.7, and 0.8 come out on GitHub only). GitHub shows one release as "Latest", which must be the newest release of the newest version of Bazaar on the Workshop. When GitHub's latest release is for a newer version of Bazaar than the release that `publish` just drafted, `publish` prints a warning to uncheck "Set as the latest release" when publishing the draft on GitHub. When `publish` can't ask GitHub, `publish` prints a note that it couldn't check, and the developer then checks by hand, when publishing the draft on GitHub, which release is "Latest". Before tagging, `publish` checks again that `.github/workflows/docs.yml` and `tools/docs/gather_site.py` on the version's branch are the same as on the default branch, because the default branch can change after `prepare`, and fails when they differ. When `publish` runs a second time after a first run that created the tag but failed later, the tag already exists on the built commit, and `publish` skips this check, because the `docs.yml` at that tag can't change anymore. When the check fails, copy both files from the default branch into the version's branch through a pull request. This adds a commit to the version's branch, so build the release files again with `release.py build`, check them in the game again with `release.py check` (unless the release only changes the docs and is published with `--no-check`), and run `publish` again. If `publish` fails part way through, follow its message. Running `publish` again is safe.
2. The developer checks the draft release on GitHub and publishes it. Publishing it starts two runs of the GitHub Action: the release's own run, which asks the default branch's copy of the Action to run, and then a run on the default branch, which builds the whole site with `gather_site.py` and publishes it on GitHub Pages. The developer checks that both runs succeeded and that the site opens. A release without a docs zip still starts both runs, and the site is built again from the same docs, since that version's docs come from an earlier release.

## 7. Steam Workshop

`workshop` updates Bazaar's item on the Steam Workshop, and refuses a version of Bazaar that is not on the Workshop, so only releases of a version of Bazaar that is on the Workshop (0.5.x now, 1.0.x later) update the item. A release that keeps Bazaar is not uploaded and gets no change note, since the Workshop page points to GitHub for the SDK and the docs. `workshop` refuses it too.

1. Add the release's notes to the top of `workshop\changes.txt` in BBCode, under a `[b]<number>[/b]` line and without the install paragraph or the file names, and get them approved. They go to the version's branch through a small pull request.
2. Once it has merged, pull the version's branch. With the developer's go-ahead, run `.venv\Scripts\python.exe tools\release.py workshop`. It needs Steam running and signed in to the account that owns the item, and the Sid Meier's Civilization V SDK installed from Steam. ModBuddy itself need not be open. It uploads Bazaar's package with the release's own section of `workshop\changes.txt` as the change note and `workshop\bazaar.txt` as the item's description, then checks that Steam shows the new file.

`BAZAAR_VERSIONS` in `tools\generator\common.py` lists every version of Bazaar with its mod ID, whether it goes on the Workshop, and its Workshop item. Before the first release of a version that goes on the Workshop, such as 1.0, the developer records in `BAZAAR_VERSIONS` that the version goes on the Workshop, so that `publish` doesn't make its first release a pre-release. After publishing that first release on GitHub, the developer publishes its mod as a new Workshop item with ModBuddy and adds the item's number to `BAZAAR_VERSIONS`. From then on, `workshop` updates that item. The old version's item stays up, since games saved with the old version depend on its mod.
