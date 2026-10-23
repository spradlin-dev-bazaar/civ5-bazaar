#include "CivHostSetup.h"

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

	bool SameText(const std::string& a, const std::string& b)
	{
		return _stricmp(a.c_str(), b.c_str()) == 0;
	}

	std::string FullPath(const std::string& path)
	{
		char full[MAX_PATH];
		const DWORD length = GetFullPathNameA(path.c_str(), MAX_PATH, full, 0);
		return (length > 0 && length < MAX_PATH) ? std::string(full) : path;
	}

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
			if (Attribute(attributes, "import") == "1" && SameText(name, *fileName))
				*found = path;
			return true;
		}
	};

	bool ReadText(const std::string& path, std::string* text)
	{
		FILE* f = 0;
		if (fopen_s(&f, path.c_str(), "rb") != 0 || !f)
			return false;
		char buffer[4096];
		for (size_t n; (n = fread(buffer, 1, sizeof(buffer), f)) > 0;)
			text->append(buffer, n);
		fclose(f);
		return true;
	}

	bool Exists(const std::string& path)
	{
		return GetFileAttributesA(path.c_str()) != INVALID_FILE_ATTRIBUTES;
	}

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

	// Every mod description directly inside a folder of the MODS folder, where the game itself looks for them.
	std::vector<InstalledMod> InstalledMods(const std::string& modsFolder)
	{
		std::vector<InstalledMod> mods;
		WIN32_FIND_DATAA folder;
		HANDLE folders = FindFirstFileA((modsFolder + "\\*").c_str(), &folder);
		if (folders == INVALID_HANDLE_VALUE)
			return mods;
		do
		{
			const std::string name = folder.cFileName;
			if (!(folder.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) || name == "." || name == "..")
				continue;
			const std::string path = modsFolder + "\\" + name;
			WIN32_FIND_DATAA file;
			HANDLE files = FindFirstFileA((path + "\\*.modinfo").c_str(), &file);
			if (files == INVALID_HANDLE_VALUE)
				continue;
			do
			{
				InstalledMod mod;
				mod.folder = path;
				if (ReadText(path + "\\" + file.cFileName, &mod.modinfo) && CivModIdentity(mod.modinfo, &mod.id, &mod.version))
					mods.push_back(mod);
			} while (FindNextFileA(files, &file));
			FindClose(files);
		} while (FindNextFileA(folders, &folder));
		FindClose(folders);
		return mods;
	}

	// The last active mod, other than the one in ownFolder, importing fileName; empty when none does.
	std::string ImportedByActiveMod(const std::vector<InstalledMod>& installed, const std::string& ownFolder,
		const std::vector<CivActiveMod>& active, const std::string& fileName)
	{
		const std::string own = FullPath(ownFolder);
		std::string source;
		for (size_t a = 0; a < active.size(); ++a)
		{
			for (size_t i = 0; i < installed.size(); ++i)
			{
				const InstalledMod& mod = installed[i];
				if (!SameText(mod.id, active[a].id) || mod.version != active[a].version || SameText(FullPath(mod.folder), own))
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
		result.xmlSource = expansion1 && Exists(expansionSetup + kXml) ? expansionSetup + kXml : gameSetup + kXml;
	if (result.luaSource.empty())
		result.luaSource = gameSetup + kLua;

	const std::string copy = ownFolder + "\\" + kCopyName;
	const std::string sources[] = {result.xmlSource, result.luaSource};
	const std::string targets[] = {copy + ".xml", copy + ".lua"};
	for (int i = 0; i < 2; ++i)
	{
		// CopyFile keeps the source's attributes, and it cannot write over a read-only copy left by an earlier visit.
		SetFileAttributesA(targets[i].c_str(), FILE_ATTRIBUTE_NORMAL);
		if (!CopyFileA(sources[i].c_str(), targets[i].c_str(), FALSE))
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
