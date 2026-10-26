#include "CivHostSetup.h"
#include "CivHostPath.h"

#include <windows.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

namespace
{
	const char* const kXml = "AdvancedSetup.xml";
	const char* const kLua = "AdvancedSetup.lua";
	const char* const kCopyName = "BazaarNextSetup";

	std::string Decode(const std::string& text)
	{
		static const char* const entities[][2] = {{"&amp;", "&"}, {"&lt;", "<"}, {"&gt;", ">"}, {"&quot;", "\""}, {"&apos;", "'"}};
		std::string out;
		for (size_t i = 0; i < text.size();)
		{
			bool replaced = false;
			for (size_t e = 0; e < sizeof(entities) / sizeof(entities[0]) && !replaced; ++e)
			{
				const size_t n = strlen(entities[e][0]);
				if (text.compare(i, n, entities[e][0]) == 0)
				{
					out += entities[e][1];
					i += n;
					replaced = true;
				}
			}
			if (!replaced)
				out += text[i++];
		}
		return out;
	}

	// The value of name="..." or name='...' among a start tag's attributes, or empty.
	std::string Attribute(const std::string& attributes, const char* name)
	{
		const std::string key = std::string(name) + "=";
		for (size_t at = attributes.find(key); at != std::string::npos; at = attributes.find(key, at + 1))
		{
			if (at > 0 && !isspace((unsigned char)attributes[at - 1]))
				continue;
			const size_t open = at + key.size();
			if (open >= attributes.size() || (attributes[open] != '"' && attributes[open] != '\''))
				continue;
			const size_t close = attributes.find(attributes[open], open + 1);
			if (close != std::string::npos)
				return Decode(attributes.substr(open + 1, close - open - 1));
		}
		return std::string();
	}

	// Calls found(attributes, text) for each <tag ...>text</tag>, with the text still encoded, until found returns false.
	// Longer tag names that start the same way are skipped.
	template<class Found> void EachElement(const std::string& xml, const std::string& tag, Found found)
	{
		const std::string open = "<" + tag;
		const std::string close = "</" + tag + ">";
		for (size_t at = xml.find(open); at != std::string::npos; at = xml.find(open, at + 1))
		{
			const size_t after = at + open.size();
			if (after >= xml.size() || (xml[after] != '>' && xml[after] != '/' && !isspace((unsigned char)xml[after])))
				continue;
			const size_t endOfTag = xml.find('>', after);
			if (endOfTag == std::string::npos)
				return;
			const std::string attributes = xml.substr(after, endOfTag - after);
			std::string text;
			if (xml[endOfTag - 1] != '/')
			{
				const size_t end = xml.find(close, endOfTag + 1);
				if (end == std::string::npos)
					return;
				text = xml.substr(endOfTag + 1, end - endOfTag - 1);
			}
			if (!found(attributes, text))
				return;
		}
	}

	struct FindIdentity
	{
		std::string* id;
		int* version;
		bool* ok;
		bool operator()(const std::string& attributes, const std::string&) const
		{
			*id = Attribute(attributes, "id");
			const std::string versionText = Attribute(attributes, "version");
			*version = atoi(versionText.c_str());
			*ok = !id->empty() && !versionText.empty();
			return false;
		}
	};

	struct FindImported
	{
		const std::string* fileName;
		std::string* found;
		bool operator()(const std::string& attributes, const std::string& encoded) const
		{
			const std::string path = Decode(encoded);
			const size_t slash = path.find_last_of("\\/");
			const std::string name = slash == std::string::npos ? path : path.substr(slash + 1);
			if (Attribute(attributes, "import") == "1" && CivSameText(name, *fileName))
				*found = path;
			return true;
		}
	};

	std::string WindowsPath(const std::string& path)
	{
		std::string out = path;
		for (size_t i = 0; i < out.size(); ++i)
			if (out[i] == '/')
				out[i] = '\\';
		return out;
	}

	struct InstalledMod
	{
		std::string folder;
		std::string id;
		int version;
		std::string modinfo;
	};

	// Every mod description directly inside a folder of the MODS folder. The game also finds descriptions in subfolders,
	// which this does not look in.
	std::vector<InstalledMod> InstalledMods(const std::string& modsFolder)
	{
		std::vector<InstalledMod> mods;
		const std::vector<CivFolderEntry> folders = CivFolderEntries(modsFolder, "*");
		for (size_t f = 0; f < folders.size(); ++f)
		{
			if (!folders[f].folder)
				continue;
			const std::string path = modsFolder + "\\" + folders[f].name;
			const std::vector<CivFolderEntry> files = CivFolderEntries(path, "*.modinfo");
			for (size_t i = 0; i < files.size(); ++i)
			{
				InstalledMod mod;
				mod.folder = path;
				if (CivReadFile(path + "\\" + files[i].name, &mod.modinfo) && CivModIdentity(mod.modinfo, &mod.id, &mod.version))
					mods.push_back(mod);
			}
		}
		return mods;
	}

	// The last active mod, other than the one in ownFolder, importing fileName; empty when none does.
	std::string ImportedByActiveMod(const std::vector<InstalledMod>& installed, const std::string& ownFolder,
		const std::vector<CivActiveMod>& active, const std::string& fileName)
	{
		const std::string own = CivFullPath(ownFolder);
		std::string source;
		for (size_t a = 0; a < active.size(); ++a)
		{
			for (size_t i = 0; i < installed.size(); ++i)
			{
				const InstalledMod& mod = installed[i];
				if (!CivSameText(mod.id, active[a].id) || mod.version != active[a].version || CivSameText(CivFullPath(mod.folder), own))
					continue;
				const std::string file = CivImportedFile(mod.modinfo, fileName);
				if (!file.empty())
					source = mod.folder + "\\" + WindowsPath(file);
			}
		}
		return source;
	}
}

bool CivModIdentity(const std::string& modinfo, std::string* id, int* version)
{
	bool ok = false;
	FindIdentity find = {id, version, &ok};
	EachElement(modinfo, "Mod", find);
	return ok;
}

std::string CivImportedFile(const std::string& modinfo, const std::string& fileName)
{
	std::string found;
	FindImported find = {&fileName, &found};
	EachElement(modinfo, "File", find);
	return found;
}

CivReplacedSetup CivCopyReplacedSetup(const std::string& modsFolder, const std::string& gameFolder, const std::string& ownFolder,
	const std::vector<CivActiveMod>& active, bool expansion1)
{
	const std::vector<InstalledMod> installed = InstalledMods(modsFolder);
	CivReplacedSetup result;
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
