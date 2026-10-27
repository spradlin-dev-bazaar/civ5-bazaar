#include "CvGameCoreDLLPCH.h"
#include "CvNotifications.h"

#include "CivHostEngine.h"
#include "CivHostLock.h"
#include "CivHostMods.h"
#include "CivHostNotices.h"
#include "CivHostOrder.h"
#include "CivHostPath.h"
#include "CivHostRuntime.h"
#include "CivHostSaves.h"
#include "CivHostSetup.h"
#include "CivHostValues.h"

#include <stdio.h>
#include <string.h>

// shlobj.h does not compile under the engine's trimmed windows.h, so declare the one call we need.
extern "C" __declspec(dllimport) HRESULT __stdcall SHGetFolderPathW(HWND, int, HANDLE, DWORD, LPWSTR);
#pragma comment(lib, "shell32.lib")

namespace
{
	const int kCsidlPersonal = 0x0005;

	std::string s_userFolder;

	std::string UserFolder()
	{
		if (s_userFolder.empty())
		{
			wchar_t docs[MAX_PATH];
			if (SHGetFolderPathW(NULL, kCsidlPersonal, NULL, 0, docs) == S_OK)
				s_userFolder = CivUtf8(docs) + "\\My Games\\Sid Meier's Civilization 5";
		}
		return s_userFolder;
	}

	// The game unloads and reloads this DLL at the main menu, which resets a static flag but not the process's environment,
	// so the log is emptied once per run of the game rather than before each game.
	const char* const kLogStarted = "BAZAAR_LOG_STARTED";
	CivLock s_logLock;

	void LogLine(const char* line)
	{
		CivLockHold hold(s_logLock);
		if (UserFolder().empty())
			return;
		const bool fresh = GetEnvironmentVariableA(kLogStarted, NULL, 0) == 0;
		FILE* f = 0;
		if (_wfopen_s(&f, CivWide(UserFolder() + "\\Logs\\Bazaar.log").c_str(), fresh ? L"w" : L"a") == 0 && f)
		{
			if (fresh)
				SetEnvironmentVariableA(kLogStarted, "1");
			fprintf(f, "%s\n", line);
			fclose(f);
		}
	}

	void OnFault(int, const char* name, bool shuttingDown, unsigned int)
	{
		if (shuttingDown)
			CivQueueNotice("Plugin disabled", std::string(name) + " stopped working while shutting down, so it stays off until you restart Civilization V. Details are in Logs\\Bazaar.log.");
		else
		{
			const std::string rest = " stopped working and was turned off until you return to the main menu.[NEWLINE][NEWLINE]The game may now be unstable. If you want to keep this game, save it in a new save slot rather than over your main save, and play on at your own risk.[NEWLINE][NEWLINE]Details are in Logs\\Bazaar.log.";
			CivQueuePopup(CivShortened(name, sizeof(CvPopupInfo().szText) - 1 - rest.size()) + rest);
		}
	}

	void ShowPopup(const std::string& text)
	{
		// The game's TextPopup.lua takes Data1 as the width to wrap the text at.
		CvPopupInfo popup(BUTTONPOPUP_TEXT, 500);
		strncpy_s(popup.szText, sizeof(popup.szText), text.c_str(), _TRUNCATE);
		GC.GetEngineUserInterface()->AddPopup(popup);
	}

	const char* const kPluginProblem = "Plugin problem";
	const char* const kPluginNotLoaded = "Plugin not loaded";
	const char* const kListUnreadable = "Bazaar could not read the list of plugins, so any plugins already loaded were left as they were.";
	const char* const kModsUnreadable = "Bazaar could not read the game's list of mods, so any plugins already loaded were left as they were.";
	const char* const kBusy = "Your plugin changes were not applied because a plugin was busy. They will be applied the next time your mods change, or when you restart Civilization V.";
	const char* const kNotSaved = "Bazaar could not save your plugin order, so the old order comes back when a game starts. Details are in Logs\\Bazaar.log.";
	const char* const kPluginDataNotLoaded = "Plugin data not loaded";
	const char* const kSaveOverWarning = " If you save over this game, that data is lost for good; save in a new slot to keep the old save as it is.";

	// A damaged length must not crash the load; a part not read in full comes back empty, which counts as damaged.
	std::string ReadSavePart(FDataStream& stream)
	{
		uint size = 0;
		stream >> size;
		std::string part;
		try
		{
			part.resize(size);
		}
		catch (const std::exception&)
		{
			return std::string();
		}
		if (size && stream.ReadIt(size, &part[0]) != size)
			return std::string();
		return part;
	}

	std::string Lines(const std::vector<std::string>& lines)
	{
		std::string text;
		for (size_t i = 0; i < lines.size(); ++i)
			text += (i ? "\n" : "") + lines[i];
		return text;
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
				files->push_back(CivUtf8(CivWide(file)));
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
		std::string text;
		if (!CivReadFile(OrderFile(), &text))
		{
			if (CivExists(OrderFile()))
				LogLine(("Could not read " + OrderFile() + ", so the plugins load in the order the mods list them.").c_str());
			return std::vector<CivOrderEntry>();
		}
		return CivParseOrder(text);
	}

	// Written beside the old file and then moved over it, so a failed write never leaves half an order.
	bool SaveOrder(const std::vector<CivOrderEntry>& order)
	{
		if (UserFolder().empty())
			return false;
		CreateDirectoryW(CivWide(UserFolder() + "\\ModUserData").c_str(), NULL);
		const std::string path = OrderFile();
		const std::wstring temp = CivWide(path + ".new");
		const std::string text = CivFormatOrder(order);
		FILE* f = 0;
		bool saved = _wfopen_s(&f, temp.c_str(), L"wb") == 0 && f;
		if (saved)
		{
			saved = fwrite(text.data(), 1, text.size(), f) == text.size();
			saved = fclose(f) == 0 && saved;
		}
		saved = saved && MoveFileExW(temp.c_str(), CivWide(path).c_str(), MOVEFILE_REPLACE_EXISTING);
		if (!saved)
			LogLine(("Could not save the plugin order to " + path + ".").c_str());
		return saved;
	}

	void NotifyNotLoaded(const std::vector<CivNotLoaded>& notLoaded)
	{
		std::vector<std::string> lines;
		for (size_t i = 0; i < notLoaded.size(); ++i)
			lines.push_back(notLoaded[i].file + ": " + notLoaded[i].reason);
		if (CivReplaceNoticesOnce(kPluginNotLoaded, lines))
			for (size_t i = 0; i < lines.size(); ++i)
				LogLine(lines[i].c_str());
	}

	std::string Text(Database::Results& rows, int column)
	{
		const char* text = rows.GetText(column);
		return text ? text : "";
	}

	// Only the game's mod database knows which of a mod's installed versions is switched on.
	bool ActiveMods(std::vector<CivActiveMod>* mods)
	{
		Database::Connection* modding = gDLL->GetModsDatabase();
		Database::Results rows;
		if (!modding || !modding->Execute(rows,
			"SELECT m.ModID, m.Version, (SELECT p.Value FROM ModProperties p WHERE p.ModID = m.ModID AND p.Version = m.Version "
			"AND p.Name = 'AffectsSavedGames'), f.EvaluatedPath, f.Import FROM Mods m JOIN ModFiles f ON f.ModID = m.ModID "
			"AND f.Version = m.Version WHERE m.Activated = 1 ORDER BY m.RowID, f.rowid"))
			return false;
		while (rows.Step())
			CivAddModRow(mods, Text(rows, 0), rows.GetInt(1), Text(rows, 2), CivUtf8(CivWide(Text(rows, 3))), rows.GetInt(4) != 0);
		return true;
	}

	// No C++ objects may live in this frame: luaL_error, and any Lua error the plugin raises, jump out of it.
	int CallPluginLuaFunction(lua_State* L)
	{
		char why[256] = "";
		int results = 0;
		const unsigned int serial = (unsigned int)lua_tointeger(L, lua_upvalueindex(1));
		CivLuaFunction fn = (CivLuaFunction)lua_touserdata(L, lua_upvalueindex(2));
		if (!CivHostCallLuaFunction(serial, fn, L, &results, why, sizeof(why)))
			return luaL_error(L, "%s", why);
		// Lua takes any negative count for a yield.
		if (results < 0 && lua_status(L) != LUA_YIELD)
			return luaL_error(L, "A plugin's Lua function returned %d, which only lua_yield may return.", results);
		return results;
	}

	void PushPluginLuaFunction(lua_State* L, unsigned int serial, CivLuaFunction fn)
	{
		lua_pushinteger(L, (lua_Integer)serial);
		lua_pushlightuserdata(L, (void*)fn);
		lua_pushcclosure(L, &CallPluginLuaFunction, 2);
	}

	// A kind added to CivObjectKind without a case in these two fails the build.
#pragma warning(push)
#pragma warning(error : 4062)
	bool ObjectKey(int kind, const void* object, __int64* key)
	{
		switch (static_cast<CivObjectKind>(kind))
		{
		case CIV_ON_PLAYER:
			*key = CivObjectKey(static_cast<const CvPlayer*>(object)->GetID(), 0);
			return true;
		case CIV_ON_CITY:
			*key = CivObjectKey(static_cast<const CvCity*>(object)->getOwner(), static_cast<const CvCity*>(object)->GetID());
			return true;
		case CIV_ON_UNIT:
			*key = CivObjectKey(static_cast<const CvUnit*>(object)->getOwner(), static_cast<const CvUnit*>(object)->GetID());
			return true;
		case CIV_ON_PLOT:
			*key = CivObjectKey(static_cast<const CvPlot*>(object)->getX(), static_cast<const CvPlot*>(object)->getY());
			return true;
		}
		return false;
	}

	// The game's lists give back whatever is in a slot for a number without its ID part, such as 0, and its map wraps
	// plot coordinates, so what they find is checked against the numbers asked for.
	bool ObjectAlive(int kind, int first, int second)
	{
		const bool owned = first >= 0 && first < MAX_PLAYERS;
		switch (static_cast<CivObjectKind>(kind))
		{
		case CIV_ON_PLAYER:
			return owned && second == 0;
		case CIV_ON_CITY:
		{
			const CvCity* city = owned ? GET_PLAYER((PlayerTypes)first).getCity(second) : NULL;
			return city && city->GetID() == second;
		}
		case CIV_ON_UNIT:
		{
			const CvUnit* unit = owned ? GET_PLAYER((PlayerTypes)first).getUnit(second) : NULL;
			return unit && unit->GetID() == second;
		}
		case CIV_ON_PLOT:
			return first >= 0 && first < GC.getMap().getGridWidth() && second >= 0 && second < GC.getMap().getGridHeight();
		}
		return false;
	}
#pragma warning(pop)

	void NotifyPluginProblems()
	{
		std::vector<std::string> lines;
		const std::vector<CivPluginRecord>& plugins = CivHostPlugins();
		for (size_t i = 0; i < plugins.size(); ++i)
			for (size_t j = 0; j < plugins[i].problems.size(); ++j)
				lines.push_back(plugins[i].name + ": " + plugins[i].problems[j]);
		CivReplaceNotices(kPluginProblem, lines);
	}

	// False when the plugins were left as they were; the Plugins screen's report says why. A warning, if any, heads the
	// report.
	bool UseListedPlugins(const std::vector<CivOrderEntry>& wanted, const char* warning)
	{
		CivHostSetLogSink(&LogLine);
		CivHostSetFaultSink(&OnFault);
		CivHostSetLuaPusher(&PushPluginLuaFunction);
		CivHostSetObjectKeySink(&ObjectKey);
		CivHostSetObjectAliveSink(&ObjectAlive);
		std::vector<std::string> files;
		if (!ListedPluginFiles(&files))
		{
			LogLine("Could not read the DllPlugins table, so the plugins were left as they were.");
			WritePluginReport(CivWithNote(kListUnreadable, CivWithNote(warning, CivHostReportRows())));
			return false;
		}

		const std::vector<CivOrderEntry> order = CivOrderListedFiles(files, wanted);
		std::vector<std::string> loading;
		for (size_t i = 0; i < order.size(); ++i)
			if (!order[i].skip)
				loading.push_back(order[i].file);
		std::vector<CivActiveMod> mods;
		if (!loading.empty() && !ActiveMods(&mods))
		{
			LogLine("Could not read the game's list of mods, so the plugins were left as they were.");
			WritePluginReport(CivWithNote(kModsUnreadable, CivWithNote(warning, CivHostReportRows())));
			return false;
		}
		std::vector<CivNotLoaded> notLoaded;
		const std::vector<CivPluginFile> plugins = CivPluginFiles(loading, mods, &notLoaded);

		const CivPluginListResult result = CivHostSetPlugins(plugins, CivUseBothPairs(order));
		if (result == CIV_PLUGINS_BUSY)
		{
			CivQueueNotice("Plugins not changed", kBusy);
			WritePluginReport(CivWithNote(kBusy, CivWithNote(warning, CivHostReportRows())));
			return false;
		}
		NotifyNotLoaded(notLoaded);
		WritePluginReport(CivWithNote(warning, CivOrderReportRows(order, notLoaded, CivHostReportRows())));
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
	bool SaveAndReloadFromScreen(lua_State* L)
	{
		const std::vector<CivOrderEntry> requested = RequestedOrder(L, 2);
		const bool saved = SaveOrder(CivKeepUnlisted(requested, SavedOrder()));
		return UseListedPlugins(requested, saved ? NULL : kNotSaved);
	}

	std::string FolderOf(const std::string& path)
	{
		return path.empty() ? path : path.substr(0, path.find_last_of("\\/"));
	}

	// The DLL sits in the host mod's own folder.
	std::string OwnFolder()
	{
		MEMORY_BASIC_INFORMATION info;
		if (!VirtualQuery((const void*)&CivHostOnFrontEndCall, &info, sizeof(info)))
			return std::string();
		return FolderOf(CivModuleFile(info.AllocationBase));
	}

	std::string GameFolder()
	{
		return FolderOf(CivModuleFile(NULL));
	}

	// Pushes the copied screen's path, without extension, for LoadNewContext; nil when it could not be copied.
	void PushReplacedSetup(lua_State* L)
	{
		const std::string own = OwnFolder();
		const std::string game = GameFolder();
		std::vector<CivActiveMod> mods;
		if (!ActiveMods(&mods))
			LogLine("Could not read the game's list of mods, so Continue looks only for the game's own Advanced Setup screen.");
		CivReplacedSetup setup;
		setup.problem = "Bazaar could not find its own folder or the game's.";
		if (!own.empty() && !game.empty())
			setup = CivCopyReplacedSetup(game, own, mods, lua_toboolean(L, 2) != 0);
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
	UseListedPlugins(SavedOrder(), NULL);
}

// A type added to CivValueType without a case here fails the build.
#pragma warning(push)
#pragma warning(error : 4062)
int CivHostLuaGetPluginValue(lua_State* L)
{
	const char* modId = luaL_checkstring(L, 1);
	const char* pluginId = luaL_optstring(L, 2, "");
	const char* name = luaL_checkstring(L, 3);
	const int first = luaL_checkint(L, 4);
	const int second = luaL_optint(L, 5, 0);
	// After the checks: a Lua error jumps out of this frame without running the destructor of its text.
	CivPublishedValue value;
	if (!CivValuesGetPublished(modId, pluginId, name, first, second, &value))
	{
		lua_pushnil(L);
		return 1;
	}
	switch (static_cast<CivValueType>(value.valueType))
	{
	case CIV_VALUE_INT:
	case CIV_VALUE_INT64:
		lua_pushnumber(L, (lua_Number)value.whole);
		break;
	case CIV_VALUE_DOUBLE:
		lua_pushnumber(L, value.decimal);
		break;
	case CIV_VALUE_TEXT:
		lua_pushlstring(L, value.text.data(), value.text.size());
		break;
	}
	return 1;
}
#pragma warning(pop)

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
		lua_pushboolean(L, SaveAndReloadFromScreen(L));
	else if (request == "bazaar:nextsetup")
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
	if (!CivNoticesWaiting())
		return;
	const PlayerTypes active = GC.getGame().getActivePlayer();
	if (active == NO_PLAYER)
		return;
	CvNotifications* notifications = GET_PLAYER(active).GetNotifications();
	if (!notifications)
		return;
	// A plugin's notification hook can crash here, and the crash's own notice must not move the strings being sent.
	const std::vector<CivNotice> sending = CivTakeNotices();
	for (size_t i = 0; i < sending.size(); ++i)
	{
		if (sending[i].popup)
			ShowPopup(sending[i].message);
		else
			notifications->Add(NOTIFICATION_GENERIC, sending[i].message.c_str(), sending[i].summary.c_str(), -1, -1, -1);
	}
}

void CivHostOnWriteSave(FDataStream& stream)
{
	const std::string part = CivHostSavePart();
	stream << (uint)part.size();
	stream.WriteIt((uint)part.size(), part.data());
}

void CivHostOnReadSave(FDataStream& stream, unsigned int version)
{
	if (version < CIV_HOST_SAVE_VERSION)
	{
		CivHostLoadPart(NULL);
		return;
	}
	const std::string part = ReadSavePart(stream);
	const std::string problem = CivHostLoadPart(&part);
	if (problem.empty())
		return;
	LogLine(problem.c_str());
	CivQueueNotice(kPluginDataNotLoaded, problem + kSaveOverWarning);
}

void CivHostOnNewGame()
{
	CivHostLoadPart(NULL);
}

void CivHostOnPlayerReset(int player)
{
	CivValuesDropPlayer(player);
}

// Plugins link against this DLL, so Windows cannot unload it while any plugin stays loaded.
void CivHostOnEngineShutdown()
{
	if (!CivHostUnloadPlugins())
		LogLine("Plugins were not unloaded because one of them was still running.");
	CivForgetNamedNotices();
}
