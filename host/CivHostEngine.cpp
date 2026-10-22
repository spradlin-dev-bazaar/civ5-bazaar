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

	void OnFault(int, const char* name, int, unsigned int)
	{
		Notify("Plugin disabled",
			std::string(name) + " stopped working and was turned off for this session. Details are in Logs\\CivHost.log.");
	}
}

void CivHostOnDatabaseReady()
{
	static bool s_loaded = false;
	if (s_loaded)
		return;

	Database::Results tables;
	if (!DB.SelectWhere(tables, "sqlite_master", "type = 'table' AND name = 'DllPlugins'") || !tables.Step())
		return;
	s_loaded = true;

	CivHostSetLogSink(&LogLine);
	CivHostSetFaultSink(&OnFault);
	LogLine("---- Loading plugins");

	std::vector<std::string> paths;
	Database::Results rows;
	if (DB.SelectAll(rows, "DllPlugins"))
	{
		while (rows.Step())
		{
			const char* file = rows.GetText("File");
			if (!file || !*file)
				continue;
			std::string path;
			if (FindFile(UserFolder() + "\\MODS", file, 3, &path))
				paths.push_back(path);
			else
			{
				std::string line = std::string("Plugin file not found in the MODS folder: ") + file;
				LogLine(line.c_str());
				Notify("Plugin missing", line);
			}
		}
	}
	CivHostLoadPlugins(paths);

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
