// Finding a file among the mods the game has switched on, as the game's own mod database lists them.
#include "harness.h"
#include "CivHostMods.h"

namespace
{
	CivActiveMod Mod(const char* id)
	{
		CivActiveMod mod;
		mod.id = id;
		mod.version = 1;
		mod.affectsSavedGames = true;
		return mod;
	}

	void Add(CivActiveMod* mod, const char* path, bool imported)
	{
		CivModFile file;
		file.path = path;
		file.imported = imported;
		mod->files.push_back(file);
	}
}

void TestActiveMods()
{
	CivActiveMod first = Mod("first");
	Add(&first, "C:\\MODS\\First (v 1)\\Plugin.dll", false);
	Add(&first, "C:\\MODS\\First (v 1)\\UI/Screen.lua", true);
	Add(&first, "C:\\MODS\\First (v 1)\\Older/same.lua", true);
	Add(&first, "C:\\MODS\\First (v 1)\\Newer/SAME.lua", true);
	Check(CivModFilePath(first, "plugin.DLL") == "C:\\MODS\\First (v 1)\\Plugin.dll", "a file is found by name in any case, imported or not");
	Check(CivModImportedFilePath(first, "Plugin.dll").empty(), "a file the game does not import is left out of the imported ones");
	Check(CivModImportedFilePath(first, "Screen.lua") == "C:\\MODS\\First (v 1)\\UI\\Screen.lua", "a path comes back with Windows slashes");
	Check(CivModFilePath(first, "Same.lua") == "C:\\MODS\\First (v 1)\\Newer\\SAME.lua", "of two files with one name, the last listed is found");
	Check(CivModFilePath(first, "Absent.dll").empty(), "a file the mod does not have is not found");

	CivActiveMod second = Mod("second");
	Add(&second, "C:\\MODS\\Second\\Plugin.dll", false);
	Add(&second, "C:\\MODS\\Second\\Own.dll", false);
	CivActiveMod unsaved = Mod("unsaved");
	unsaved.affectsSavedGames = false;
	Add(&unsaved, "C:\\MODS\\Unsaved\\Unsaved.dll", false);
	Add(&unsaved, "C:\\MODS\\Unsaved\\Shared.dll", false);
	CivActiveMod saved = Mod("saved");
	Add(&saved, "C:\\MODS\\Saved\\Shared.dll", false);
	std::vector<CivActiveMod> mods;
	mods.push_back(first);
	mods.push_back(second);
	mods.push_back(unsaved);
	mods.push_back(saved);
	std::vector<std::string> files;
	files.push_back("Own.dll");
	files.push_back("Gone.dll");
	files.push_back("Unsaved.dll");
	files.push_back("Plugin.dll");
	files.push_back("Shared.dll");
	std::vector<CivNotLoaded> notLoaded;
	const std::vector<CivPluginFile> found = CivPluginFiles(files, mods, &notLoaded);
	Check(found.size() == 3 && found[0].path == "C:\\MODS\\Second\\Own.dll" && found[0].modId == "second",
		"each plugin is found in the mod that has it, in the order given, with that mod's ID");
	Check(found.size() == 3 && found[1].path == "C:\\MODS\\First (v 1)\\Plugin.dll" && found[1].modId == "first",
		"a file two mods have is taken from the first");
	Check(found.size() == 3 && found[2].path == "C:\\MODS\\Saved\\Shared.dll" && found[2].modId == "saved",
		"a file two mods have is taken from the first that affects saved games, passing over one that does not");
	Check(notLoaded.size() == 2 && notLoaded[0].file == "Gone.dll" && notLoaded[0].reason == CIV_REPORT_FILE_NOT_FOUND,
		"a file no active mod has is not loaded, and says so");
	Check(notLoaded.size() == 2 && notLoaded[1].file == "Unsaved.dll" && notLoaded[1].reason == CIV_REPORT_NOT_IN_SAVES,
		"a plugin whose mod does not affect saved games is not loaded, since a game loaded from a save would lack it");

	std::vector<CivActiveMod> rows;
	CivAddModRow(&rows, "a", 1, "1", "C:\\MODS\\A\\One.dll", false);
	CivAddModRow(&rows, "a", 1, "1", "C:\\MODS\\A\\Two.lua", true);
	CivAddModRow(&rows, "a", 2, "true", "C:\\MODS\\A (v 2)\\One.dll", false);
	CivAddModRow(&rows, "b", 1, "", "", false);
	Check(rows.size() == 3 && rows[0].files.size() == 2 && rows[0].files[1].imported, "a mod's rows become one mod with all its files");
	Check(rows.size() == 3 && rows[1].version == 2, "another version of the same mod is a mod of its own");
	Check(rows.size() == 3 && rows[0].affectsSavedGames && !rows[1].affectsSavedGames && !rows[2].affectsSavedGames,
		"only the value 1 marks a mod as affecting saved games, as the game's own Mods screen reads it");
	Check(rows.size() == 3 && rows[2].files.empty(), "a row with no path adds no file");
}
