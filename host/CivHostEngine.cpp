#include "CvGameCoreDLLPCH.h"
#include "CvNotifications.h"

#include "CivHostEngine.h"
#include "CivHostOrder.h"
#include "CivHostRuntime.h"
#include "CivHostSetup.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

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
		if (UserFolder().empty())
			return;
		FILE* f = 0;
		if (fopen_s(&f, (UserFolder() + "\\Logs\\Bazaar.log").c_str(), "a") == 0 && f)
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

	void DropNotices(const std::string& summary)
	{
		for (size_t i = s_pendingNotices.size(); i-- > 0;)
			if (s_pendingNotices[i].first == summary)
				s_pendingNotices.erase(s_pendingNotices.begin() + i);
	}

	void OnFault(int, const char* name, int hookId, unsigned int)
	{
		if (hookId < 0)
			Notify("Plugin disabled", std::string(name) + " stopped working while shutting down, so it stays off until you restart Civilization V. Details are in Logs\\Bazaar.log.");
		else
			Notify("Plugin disabled", std::string(name) + " stopped working and was turned off until you return to the main menu. The game may now be unstable: if you save, use a new save slot rather than overwriting your main save. Details are in Logs\\Bazaar.log.");
	}

	const char* const kPluginProblem = "Plugin problem";
	const char* const kPluginMissing = "Plugin missing";
	const char* const kNoDocuments = "Bazaar could not find your Documents folder, so it could not look for plugins.";
	const char* const kListUnreadable = "Bazaar could not read the list of plugins, so any plugins already loaded were left as they were.";
	const char* const kBusy = "Your plugin changes were not applied because a plugin was busy. They will be applied the next time your mods change, or when you restart Civilization V.";
	const char* const kNotSaved = "Bazaar could not save your plugin order, so the old order comes back when a game starts. Details are in Logs\\Bazaar.log.";

	std::string Lines(const std::vector<std::string>& lines)
	{
		std::string text;
		for (size_t i = 0; i < lines.size(); ++i)
			text += (i ? "\n" : "") + lines[i];
		return text;
	}

	// A row with no file is Bazaar's own note, which the Plugins screen keeps at the top.
	std::vector<CivPluginReportRow> WithNote(const char* warning, const std::vector<CivPluginReportRow>& plugins)
	{
		std::vector<CivPluginReportRow> rows;
		if (warning)
		{
			CivPluginReportRow note;
			note.name = "Bazaar";
			note.status = "Warning";
			note.problems = warning;
			rows.push_back(note);
		}
		rows.insert(rows.end(), plugins.begin(), plugins.end());
		return rows;
	}

	bool InsertPluginRows(const std::vector<CivPluginReportRow>& rows)
	{
		Database::Results insert;
		if (!DB.Execute("DROP TABLE IF EXISTS BazaarPlugins")
			|| !DB.Execute("CREATE TABLE BazaarPlugins (Position INTEGER, File TEXT, Name TEXT, Version TEXT, Status TEXT, Problems TEXT, Failed INTEGER, Skipped INTEGER, ConflictsWith TEXT, UseBothWith TEXT)")
			|| !DB.Execute(insert, "INSERT INTO BazaarPlugins (Position, File, Name, Version, Status, Problems, Failed, Skipped, ConflictsWith, UseBothWith) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"))
			return false;
		for (size_t i = 0; i < rows.size(); ++i)
		{
			insert.Bind(1, (int)i + 1);
			insert.Bind(2, rows[i].file.c_str());
			insert.Bind(3, rows[i].name.c_str());
			insert.Bind(4, rows[i].version.c_str());
			insert.Bind(5, rows[i].status.c_str());
			insert.Bind(6, rows[i].problems.c_str());
			insert.Bind(7, rows[i].failed ? 1 : 0);
			insert.Bind(8, rows[i].skipped ? 1 : 0);
			insert.Bind(9, Lines(rows[i].conflictsWith).c_str());
			insert.Bind(10, Lines(rows[i].useBothWith).c_str());
			insert.Execute();
			insert.Reset();
		}
		Database::Results count;
		return DB.Execute(count, "SELECT COUNT(*) FROM BazaarPlugins") && count.Step() && count.GetInt(0) == (int)rows.size();
	}

	// Read by the Plugins screen (frontend/AdvancedSetup.lua). Rebuilt on every call, because the game may have rebuilt its database.
	void WritePluginReport(const std::vector<CivPluginReportRow>& rows)
	{
		DB.BeginTransaction();
		const bool written = InsertPluginRows(rows);
		if (!written)
			DB.Execute("DROP TABLE IF EXISTS BazaarPlugins");
		DB.EndTransaction();
		if (!written)
			LogLine("Could not write the BazaarPlugins table, so the Plugins screen cannot list the plugins.");
	}

	// No DllPlugins table means no plugins are listed; false means the table could not be read.
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

	std::string OrderFile()
	{
		return UserFolder() + "\\ModUserData\\Bazaar plugin order.txt";
	}

	std::vector<CivOrderEntry> SavedOrder()
	{
		if (UserFolder().empty())
			return std::vector<CivOrderEntry>();
		FILE* f = 0;
		const errno_t error = fopen_s(&f, OrderFile().c_str(), "rb");
		if (error != 0 || !f)
		{
			if (error != ENOENT)
				LogLine(("Could not read " + OrderFile() + ", so the plugins load in the order the mods list them.").c_str());
			return std::vector<CivOrderEntry>();
		}
		std::string text;
		char buffer[4096];
		for (size_t n; (n = fread(buffer, 1, sizeof(buffer), f)) > 0;)
			text.append(buffer, n);
		fclose(f);
		return CivParseOrder(text);
	}

	// Written beside the old file and then moved over it, so a failed write never leaves half an order.
	bool SaveOrder(const std::vector<CivOrderEntry>& order)
	{
		if (UserFolder().empty())
			return false;
		CreateDirectoryA((UserFolder() + "\\ModUserData").c_str(), NULL);
		const std::string path = OrderFile();
		const std::string temp = path + ".new";
		const std::string text = CivFormatOrder(order);
		FILE* f = 0;
		bool saved = fopen_s(&f, temp.c_str(), "wb") == 0 && f;
		if (saved)
		{
			saved = fwrite(text.data(), 1, text.size(), f) == text.size();
			saved = fclose(f) == 0 && saved;
		}
		saved = saved && MoveFileExA(temp.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING);
		if (!saved)
			LogLine(("Could not save the plugin order to " + path + ".").c_str());
		return saved;
	}

	// Waiting notices about files that were missing before are replaced, so a file still missing is named once.
	void NotifyMissing(const std::vector<std::string>& missing)
	{
		if (missing == s_reportedMissing)
			return;
		DropNotices(kPluginMissing);
		for (size_t i = 0; i < missing.size(); ++i)
		{
			const std::string line = missing[i] + ": " + CIV_REPORT_FILE_NOT_FOUND;
			LogLine(line.c_str());
			Notify(kPluginMissing, line);
		}
		s_reportedMissing = missing;
	}

	void ResolvePaths(const std::vector<CivOrderEntry>& order, std::vector<std::string>* paths, std::vector<std::string>* missing)
	{
		for (size_t i = 0; i < order.size(); ++i)
		{
			std::string path;
			if (order[i].skip)
				continue;
			if (FindFile(UserFolder() + "\\MODS", order[i].file, 3, &path))
				paths->push_back(path);
			else
				missing->push_back(order[i].file);
		}
	}

	void NotifyPluginProblems()
	{
		DropNotices(kPluginProblem);
		const std::vector<CivPluginRecord>& plugins = CivHostPlugins();
		for (size_t i = 0; i < plugins.size(); ++i)
			for (size_t j = 0; j < plugins[i].problems.size(); ++j)
				Notify(kPluginProblem, plugins[i].name + ": " + plugins[i].problems[j]);
	}

	// False when the plugins were left as they were; the Plugins screen's report says why. A warning, if any, heads the
	// report.
	bool LoadPlugins(const std::vector<CivOrderEntry>& saved, const char* warning)
	{
		std::vector<std::string> files;
		if (!ListedPluginFiles(&files))
		{
			LogLine("Could not read the DllPlugins table, so the plugins were left as they were.");
			WritePluginReport(WithNote(kListUnreadable, WithNote(warning, CivHostReportRows())));
			return false;
		}
		if (!files.empty() && UserFolder().empty())
		{
			Notify("Plugins not loaded", kNoDocuments);
			WritePluginReport(WithNote(kNoDocuments, CivHostReportRows()));
			return false;
		}

		const std::vector<CivOrderEntry> order = CivApplyOrder(files, saved);
		std::vector<std::string> paths;
		std::vector<std::string> missing;
		ResolvePaths(order, &paths, &missing);
		NotifyMissing(missing);

		CivHostSetLogSink(&LogLine);
		CivHostSetFaultSink(&OnFault);
		const CivPluginListResult result = CivHostSetPlugins(paths, CivUseBothPairs(order));
		if (result == CIV_PLUGINS_BUSY)
		{
			Notify("Plugins not changed", kBusy);
			WritePluginReport(WithNote(kBusy, WithNote(warning, CivHostReportRows())));
			return false;
		}
		WritePluginReport(WithNote(warning, CivOrderReportRows(order, missing, CivHostReportRows())));
		if (result == CIV_PLUGINS_CHANGED)
			NotifyPluginProblems();
		return true;
	}

	// Raw access only, so no metamethod runs: a Lua error would jump past the destructors of this file's locals.
	std::string LuaText(lua_State* L, int table, const char* key)
	{
		lua_pushstring(L, key);
		lua_rawget(L, table);
		const std::string text = lua_type(L, -1) == LUA_TSTRING ? lua_tostring(L, -1) : "";
		lua_pop(L, 1);
		return text;
	}

	bool LuaFlag(lua_State* L, int table, const char* key)
	{
		lua_pushstring(L, key);
		lua_rawget(L, table);
		const bool flag = lua_toboolean(L, -1) != 0;
		lua_pop(L, 1);
		return flag;
	}

	int LuaNumber(lua_State* L, int table, const char* key)
	{
		lua_pushstring(L, key);
		lua_rawget(L, table);
		const int number = lua_type(L, -1) == LUA_TNUMBER ? (int)lua_tonumber(L, -1) : 0;
		lua_pop(L, 1);
		return number;
	}

	std::vector<std::string> LuaTexts(lua_State* L, int table, const char* key)
	{
		std::vector<std::string> texts;
		lua_pushstring(L, key);
		lua_rawget(L, table);
		const int list = lua_gettop(L);
		const int count = lua_type(L, list) == LUA_TTABLE ? (int)lua_objlen(L, list) : 0;
		for (int i = 1; i <= count; ++i)
		{
			lua_rawgeti(L, list, i);
			if (lua_type(L, -1) == LUA_TSTRING)
				texts.push_back(lua_tostring(L, -1));
			lua_pop(L, 1);
		}
		lua_pop(L, 1);
		return texts;
	}

	// The screen sends { { File = ..., Skip = ..., Name = ..., Version = ..., UseBothWith = { file, ... } }, ... }, top first.
	std::vector<CivOrderEntry> RequestedOrder(lua_State* L, int arg)
	{
		std::vector<CivOrderEntry> order;
		const int count = (int)lua_objlen(L, arg);
		for (int i = 1; i <= count; ++i)
		{
			lua_rawgeti(L, arg, i);
			const int row = lua_gettop(L);
			if (lua_type(L, row) == LUA_TTABLE)
			{
				CivOrderEntry entry;
				entry.file = LuaText(L, row, "File");
				entry.skip = LuaFlag(L, row, "Skip");
				entry.name = LuaText(L, row, "Name");
				entry.version = LuaText(L, row, "Version");
				entry.useBothWith = LuaTexts(L, row, "UseBothWith");
				if (!entry.file.empty())
					order.push_back(entry);
			}
			lua_pop(L, 1);
		}
		return order;
	}

	// Saved before reloading so a failed save shows on the screen: when a game starts, the plugins reload from the saved order.
	bool ApplyOrder(lua_State* L)
	{
		const std::vector<CivOrderEntry> requested = RequestedOrder(L, 2);
		const bool saved = SaveOrder(CivKeepUnlisted(requested, SavedOrder()));
		return LoadPlugins(requested, saved ? NULL : kNotSaved);
	}

	// The screen sends Modding.GetActivatedMods(): { { ID = ..., Version = ... }, ... }, in the order the game switched them on.
	std::vector<CivActiveMod> ActiveMods(lua_State* L, int arg)
	{
		std::vector<CivActiveMod> mods;
		const int count = (int)lua_objlen(L, arg);
		for (int i = 1; i <= count; ++i)
		{
			lua_rawgeti(L, arg, i);
			const int row = lua_gettop(L);
			if (lua_type(L, row) == LUA_TTABLE)
			{
				CivActiveMod mod;
				mod.id = LuaText(L, row, "ID");
				mod.version = LuaNumber(L, row, "Version");
				mods.push_back(mod);
			}
			lua_pop(L, 1);
		}
		return mods;
	}

	std::string FolderOf(const char* path)
	{
		const std::string full = path;
		return full.substr(0, full.find_last_of("\\/"));
	}

	// The DLL sits in the host mod's own folder.
	std::string OwnFolder()
	{
		MEMORY_BASIC_INFORMATION info;
		char path[MAX_PATH];
		if (!VirtualQuery((const void*)&CivHostOnFrontEndCall, &info, sizeof(info)) || !GetModuleFileNameA((HMODULE)info.AllocationBase, path, MAX_PATH))
			return std::string();
		return FolderOf(path);
	}

	std::string GameFolder()
	{
		char path[MAX_PATH];
		return GetModuleFileNameA(NULL, path, MAX_PATH) ? FolderOf(path) : std::string();
	}

	// Pushes the copied screen's path, without extension, for LoadNewContext; nil when it could not be copied.
	void PushReplacedSetup(lua_State* L)
	{
		const std::string own = OwnFolder();
		const std::string game = GameFolder();
		CivReplacedSetup setup;
		setup.problem = "Bazaar could not find its own folder or the game's.";
		if (!own.empty() && !game.empty())
			setup = CivCopyReplacedSetup(UserFolder() + "\\MODS", game, own, ActiveMods(L, 2), lua_toboolean(L, 3) != 0);
		if (setup.copy.empty())
		{
			LogLine(("Could not open the Advanced Setup screen that Bazaar replaced: " + setup.problem).c_str());
			lua_pushnil(L);
			return;
		}
		LogLine(("Continue opened Advanced Setup from " + setup.xmlSource + " and " + setup.luaSource + ".").c_str());
		lua_pushstring(L, setup.copy.c_str());
	}
}

std::vector<int> CivHostTeamPlayers(int team)
{
	std::vector<int> players;
	for (int i = 0; i < MAX_CIV_PLAYERS; ++i)
		if (GET_PLAYER((PlayerTypes)i).isAlive() && GET_PLAYER((PlayerTypes)i).getTeam() == (TeamTypes)team)
			players.push_back(i);
	return players;
}

void CivHostOnDatabaseReady()
{
	LoadPlugins(SavedOrder(), NULL);
}

bool CivHostOnFrontEndCall(lua_State* L, int* results)
{
	if (lua_type(L, 1) != LUA_TSTRING || strncmp(lua_tostring(L, 1), "bazaar:", 7) != 0)
		return false;
	const std::string request = lua_tostring(L, 1);
	*results = 1;
	// Any Lua can make this call, and reloading the plugins in the middle of a game would reset them.
	if (GC.getGame().isFinalInitialized())
	{
		LogLine(("Ignored a Plugins screen request during a game: " + request).c_str());
		lua_pushnil(L);
		return true;
	}
	if (request == "bazaar:apply" && lua_type(L, 2) == LUA_TTABLE)
		lua_pushboolean(L, ApplyOrder(L));
	else if (request == "bazaar:nextsetup" && lua_type(L, 2) == LUA_TTABLE)
		PushReplacedSetup(L);
	else
	{
		LogLine(("The Plugins screen sent a request Bazaar could not use: " + request).c_str());
		lua_pushnil(L);
	}
	return true;
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
