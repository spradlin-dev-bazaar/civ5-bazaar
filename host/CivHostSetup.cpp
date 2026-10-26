#include "CivHostSetup.h"
#include "CivHostPath.h"

#include <windows.h>
#include <stdio.h>

namespace
{
	const char* const kXml = "AdvancedSetup.xml";
	const char* const kLua = "AdvancedSetup.lua";
	const char* const kCopyName = "BazaarNextSetup";

	// The last active mod, other than the one in ownFolder, importing fileName; empty when none does.
	std::string ImportedByActiveMod(const std::vector<CivInstalledMod>& installed, const std::string& ownFolder,
		const std::vector<CivActiveMod>& active, const std::string& fileName)
	{
		const std::string own = CivFullPath(ownFolder);
		std::string source;
		for (size_t a = 0; a < active.size(); ++a)
		{
			for (size_t i = 0; i < installed.size(); ++i)
			{
				const CivInstalledMod& mod = installed[i];
				if (!CivSameText(mod.info.id, active[a].id) || mod.info.version != active[a].version || CivSameText(CivFullPath(mod.folder), own))
					continue;
				const std::string file = CivModImportedFilePath(mod.info, fileName);
				if (!file.empty())
					source = mod.folder + "\\" + file;
			}
		}
		return source;
	}
}

CivReplacedSetup CivCopyReplacedSetup(const std::string& modsFolder, const std::string& gameFolder, const std::string& ownFolder,
	const std::vector<CivActiveMod>& active, bool expansion1)
{
	CivReplacedSetup result;
	const std::vector<CivInstalledMod> installed = CivInstalledMods(modsFolder, &result.unreadable);
	result.xmlSource = ImportedByActiveMod(installed, ownFolder, active, kXml);
	result.luaSource = ImportedByActiveMod(installed, ownFolder, active, kLua);
	const std::string gameSetup = gameFolder + "\\Assets\\UI\\FrontEnd\\GameSetup\\";
	const std::string expansionSetup = gameFolder + "\\Assets\\DLC\\Expansion\\UI\\FrontEnd\\GameSetup\\";
	if (result.xmlSource.empty())
		result.xmlSource = expansion1 && CivExists(expansionSetup + kXml) ? expansionSetup + kXml : gameSetup + kXml;
	if (result.luaSource.empty())
		result.luaSource = gameSetup + kLua;

	const std::string copy = ownFolder + "\\" + kCopyName;
	const std::string sources[] = {result.xmlSource, result.luaSource};
	const std::string targets[] = {copy + ".xml", copy + ".lua"};
	for (int i = 0; i < 2; ++i)
	{
		// CopyFile keeps the source's attributes, and it cannot write over a read-only copy left by an earlier visit.
		SetFileAttributesW(CivWide(targets[i]).c_str(), FILE_ATTRIBUTE_NORMAL);
		if (!CopyFileW(CivWide(sources[i]).c_str(), CivWide(targets[i]).c_str(), FALSE))
		{
			char reason[64];
			_snprintf_s(reason, sizeof(reason), _TRUNCATE, " (Windows error %lu)", GetLastError());
			result.problem = "Could not copy " + sources[i] + " to " + targets[i] + reason + ".";
			return result;
		}
	}
	result.copy = copy;
	return result;
}
