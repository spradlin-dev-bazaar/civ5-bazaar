#include "CvGameCoreDLLPCH.h"
#include "CvNotifications.h"

#include "CivHostEngine.h"
#include "CivHostRuntime.h"

#include <stdio.h>

// shlobj.h does not compile under the engine's trimmed windows.h, so declare the one call we need.
extern "C" __declspec(dllimport) HRESULT __stdcall SHGetFolderPathA(HWND, int, HANDLE, DWORD, LPSTR);
#pragma comment(lib, "shell32.lib")

namespace
{
	const int kCsidlPersonal = 0x0005;

	std::string s_userFolder;
	std::vector<std::string> s_reportedMissing;
	std::vector<std::pair<std::string, std::string> > s_pendingNotices;

	std::string UserFolder()
	{
		if (s_userFolder.empty())
		{
			char docs[MAX_PATH];
			if (SHGetFolderPathA(NULL, kCsidlPersonal, NULL, 0, docs) == S_OK)
				s_userFolder = std::string(docs) + "\\My Games\\Sid Meier's Civilization 5";
		}
		return s_userFolder;
	}

	void LogLine(const char* line)
	{
		FILE* f = 0;
		if (fopen_s(&f, (UserFolder() + "\\Logs\\CivHost.log").c_str(), "a") == 0 && f)
		{
			fprintf(f, "%s\n", line);
			fclose(f);
		}
	}

	bool FindFile(const std::string& dir, const std::string& name, int depth, std::string* found)
	{
		WIN32_FIND_DATAA data;
		HANDLE h = FindFirstFileA((dir + "\\*").c_str(), &data);
		if (h == INVALID_HANDLE_VALUE)
			return false;
		bool ok = false;
		do
		{
			const std::string entry = data.cFileName;
			if (entry == "." || entry == "..")
				continue;
			const std::string path = dir + "\\" + entry;
			if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
				ok = depth > 0 && FindFile(path, name, depth - 1, found);
			else if (_stricmp(entry.c_str(), name.c_str()) == 0)
			{
				*found = path;
				ok = true;
			}
		} while (!ok && FindNextFileA(h, &data));
		FindClose(h);
		return ok;
	}

	void Notify(const std::string& summary, const std::string& message)
	{
		s_pendingNotices.push_back(std::make_pair(summary, message));
	}

	void OnFault(int, const char* name, int hookId, unsigned int)
	{
		if (hookId < 0)
			Notify("Plugin disabled", std::string(name) + " stopped working while shutting down, so it stays off until you restart Civilization V. Details are in Logs\\CivHost.log.");
		else
			Notify("Plugin disabled", std::string(name) + " stopped working and was turned off until you return to the main menu. The game may now be unstable: if you save, use a new save slot rather than overwriting your main save. Details are in Logs\\CivHost.log.");
	}

	// No DllPlugins table means no plugin mod is active; false means the table could not be read.
	bool ListedPluginFiles(std::vector<std::string>* files)
	{
		Database::Results tables;
		if (!DB.SelectWhere(tables, "sqlite_master", "type = 'table' AND name = 'DllPlugins'"))
			return false;
		if (!tables.Step())
			return true;
		Database::Results rows;
		if (!DB.SelectAll(rows, "DllPlugins"))
			return false;
		while (rows.Step())
		{
			const char* file = rows.GetText("File");
			if (file && *file)
				files->push_back(file);
		}
		return true;
	}
}

void CivHostOnDatabaseReady()
{
	std::vector<std::string> files;
	if (!ListedPluginFiles(&files))
	{
		LogLine("Could not read the DllPlugins table, so the plugins were left as they were.");
		return;
	}
	if (!files.empty() && UserFolder().empty())
	{
		Notify("Plugins not loaded", "The plugin host could not find your Documents folder, so it could not look for plugins.");
		return;
	}

	std::vector<std::string> paths;
	std::vector<std::string> missing;
	for (size_t i = 0; i < files.size(); ++i)
	{
		std::string path;
		if (FindFile(UserFolder() + "\\MODS", files[i], 3, &path))
			paths.push_back(path);
		else
			missing.push_back(files[i]);
	}
	if (missing != s_reportedMissing)
	{
		for (size_t i = 0; i < missing.size(); ++i)
		{
			const std::string line = "Plugin file not found in the MODS folder: " + missing[i];
			LogLine(line.c_str());
			Notify("Plugin missing", line);
		}
		s_reportedMissing = missing;
	}

	CivHostSetLogSink(&LogLine);
	CivHostSetFaultSink(&OnFault);
	switch (CivHostSetPlugins(paths))
	{
	case CIV_PLUGINS_UNCHANGED:
		return;
	case CIV_PLUGINS_BUSY:
		Notify("Plugins not changed", "Your plugin changes were not applied because a plugin was busy. They will be applied the next time your mods change, or when you restart Civilization V.");
		return;
	case CIV_PLUGINS_CHANGED:
		break;
	}

	const std::vector<CivPluginRecord>& plugins = CivHostPlugins();
	for (size_t i = 0; i < plugins.size(); ++i)
		for (size_t j = 0; j < plugins[i].problems.size(); ++j)
			Notify("Plugin problem", plugins[i].name + ": " + plugins[i].problems[j]);
}

void CivHostOnGameUpdate()
{
	if (s_pendingNotices.empty())
		return;
	const PlayerTypes active = GC.getGame().getActivePlayer();
	if (active == NO_PLAYER)
		return;
	CvNotifications* notifications = GET_PLAYER(active).GetNotifications();
	if (!notifications)
		return;
	for (size_t i = 0; i < s_pendingNotices.size(); ++i)
		notifications->Add(NOTIFICATION_GENERIC, s_pendingNotices[i].second.c_str(), s_pendingNotices[i].first.c_str(), -1, -1, -1);
	s_pendingNotices.clear();
}

// Plugins link against this DLL, so Windows cannot unload it while any plugin stays loaded.
void CivHostOnEngineShutdown()
{
	if (!CivHostUnloadPlugins())
		LogLine("Plugins were not unloaded because one of them was still running.");
	s_reportedMissing.clear();
}
