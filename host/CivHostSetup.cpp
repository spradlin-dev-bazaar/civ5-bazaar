#include "CivHostSetup.h"
#include "CivHostPath.h"

#include <windows.h>
#include <stdio.h>

namespace
{
	const char* const kXml = "AdvancedSetup.xml";
	const char* const kLua = "AdvancedSetup.lua";
	const char* const kCopyName = "BazaarNextSetup";

	bool Inside(const std::string& path, const std::string& folder)
	{
		const std::string prefix = folder + "\\";
		return path.size() > prefix.size() && CivSameText(path.substr(0, prefix.size()), prefix);
	}

	std::string ImportedByActiveMod(const std::vector<CivActiveMod>& mods, const std::string& ownFolder, const std::string& fileName)
	{
		const std::string own = CivFullPath(ownFolder);
		std::string source;
		for (size_t m = 0; m < mods.size(); ++m)
		{
			const std::string file = CivModImportedFilePath(mods[m], fileName);
			if (!file.empty() && !Inside(CivFullPath(file), own))
				source = file;
		}
		return source;
	}
}

CivReplacedSetup CivCopyReplacedSetup(const std::string& gameFolder, const std::string& ownFolder, const std::vector<CivActiveMod>& mods,
	bool expansion1)
{
	CivReplacedSetup result;
	result.xmlSource = ImportedByActiveMod(mods, ownFolder, kXml);
	result.luaSource = ImportedByActiveMod(mods, ownFolder, kLua);
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
