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
	std::vector<CivActiveMod> mods;
	mods.push_back(first);
	mods.push_back(second);
	std::vector<std::string> files;
	files.push_back("Own.dll");
	files.push_back("Gone.dll");
	files.push_back("Plugin.dll");
	std::vector<std::string> missing;
	const std::vector<std::string> paths = CivPluginPaths(files, mods, &missing);
	Check(paths.size() == 2 && paths[0] == "C:\\MODS\\Second\\Own.dll", "each plugin is found in the mod that has it, in the order given");
	Check(paths.size() == 2 && paths[1] == "C:\\MODS\\First (v 1)\\Plugin.dll", "a file two mods have is taken from the first");
	Check(missing.size() == 1 && missing[0] == "Gone.dll", "a file no active mod has is named as missing");

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
