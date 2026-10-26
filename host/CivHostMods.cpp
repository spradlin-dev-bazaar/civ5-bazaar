#include "CivHostMods.h"
#include "CivHostPath.h"

namespace
{
	std::string WindowsPath(const std::string& path)
	{
		std::string out = path;
		for (size_t i = 0; i < out.size(); ++i)
			if (out[i] == '/')
				out[i] = '\\';
		return out;
	}

	std::string LastFilePath(const CivActiveMod& mod, const std::string& fileName, bool importedOnly)
	{
		std::string found;
		for (size_t i = 0; i < mod.files.size(); ++i)
			if ((mod.files[i].imported || !importedOnly) && CivSameText(CivFileName(mod.files[i].path), fileName))
				found = WindowsPath(mod.files[i].path);
		return found;
	}

	CivNotLoaded NotLoaded(const std::string& file, const char* reason)
	{
		CivNotLoaded notLoaded;
		notLoaded.file = file;
		notLoaded.reason = reason;
		return notLoaded;
	}
}

void CivAddModRow(std::vector<CivActiveMod>* mods, const std::string& id, int version, const std::string& affectsSavedGames,
	const std::string& path, bool imported)
{
	if (mods->empty() || mods->back().id != id || mods->back().version != version)
	{
		CivActiveMod mod;
		mod.id = id;
		mod.version = version;
		mod.affectsSavedGames = affectsSavedGames == "1";
		mods->push_back(mod);
	}
	if (path.empty())
		return;
	CivModFile file;
	file.path = path;
	file.imported = imported;
	mods->back().files.push_back(file);
}

std::string CivModFilePath(const CivActiveMod& mod, const std::string& fileName)
{
	return LastFilePath(mod, fileName, false);
}

std::string CivModImportedFilePath(const CivActiveMod& mod, const std::string& fileName)
{
	return LastFilePath(mod, fileName, true);
}

std::vector<std::string> CivPluginPaths(const std::vector<std::string>& files, const std::vector<CivActiveMod>& mods,
	std::vector<CivNotLoaded>* notLoaded)
{
	std::vector<std::string> paths;
	for (size_t f = 0; f < files.size(); ++f)
	{
		bool listed = false;
		std::string path;
		for (size_t m = 0; m < mods.size() && path.empty(); ++m)
		{
			const std::string found = CivModFilePath(mods[m], files[f]);
			listed = listed || !found.empty();
			if (mods[m].affectsSavedGames)
				path = found;
		}
		if (!path.empty())
			paths.push_back(path);
		else
			notLoaded->push_back(NotLoaded(files[f], listed ? CIV_REPORT_NOT_IN_SAVES : CIV_REPORT_FILE_NOT_FOUND));
	}
	return paths;
}
