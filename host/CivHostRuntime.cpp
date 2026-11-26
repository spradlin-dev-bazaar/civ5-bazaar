#include "CivHostCalls.h"
#include "CivHostConflicts.h"
#include "CivHostCrash.h"
#include "CivHostFunctions.h"
#include "CivHostHookList.h"
#include "CivHostImage.h"
#include "CivHostPath.h"
#include "CivHostRegister.h"
#include "CivHostRuntime.h"
#include "CivHostValues.h"

#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

namespace
{
	struct KeptPlugin
	{
		std::string path;
		std::string name;
	};

	std::vector<CivPluginRecord> s_plugins;
	std::vector<KeptPlugin> s_kept;
	CivHostLogSink s_logSink = 0;
	unsigned int s_lastSerial = 0;

	// A plugin registers and logs from its entry point, before the host has copied its name.
	const char* DisplayName(int plugin)
	{
		if (plugin < 0 || plugin >= (int)s_plugins.size())
			return "?";
		if (plugin == CivCallsEntryPlugin() && CivCallsEntryInfo()->name && *CivCallsEntryInfo()->name)
			return CivCallsEntryInfo()->name;
		return s_plugins[plugin].name.c_str();
	}

	// A plugin's name and version may point anywhere, even after its entry function crashed partway.
	// No C++ objects may live in this frame, or __try is not allowed.
	bool CopyPluginText(const char* text, char* out, size_t size)
	{
		out[0] = 0;
		__try
		{
			if (text)
				strncpy_s(out, size, text, _TRUNCATE);
			return true;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
			out[0] = 0;
			return false;
		}
	}

	// A plugin whose shutdown faulted, or that still has a thread inside its DLL, may still have code
	// referenced elsewhere, so the DLL stays loaded and the plugin stays refused until Civilization V restarts.
	void Unload(int plugin)
	{
		const bool clean = CivCallsShutDown(plugin);
		CivPluginRecord& rec = s_plugins[plugin];
		const bool threadLeft = clean && CivImageThreadInside((HMODULE)rec.module);
		if (clean && !threadLeft)
		{
			CivCrashForgetModule((HMODULE)rec.module);
			FreeLibrary((HMODULE)rec.module);
			CivRegisterFreeHostInfo(rec.host);
			CivHostLog("Plugin %s unloaded.", rec.name.c_str());
		}
		else
		{
			rec.host->pluginIndex = -1;
			KeptPlugin kept = { rec.path, rec.name };
			s_kept.push_back(kept);
			if (threadLeft)
				CivHostLog("Plugin %s stays in memory because one of its threads is still running.", rec.name.c_str());
			else
				CivHostLog("Plugin %s stays in memory because its shutdown function faulted.", rec.name.c_str());
		}
		rec.module = 0;
		rec.host = 0;
	}

	void Refuse(CivPluginRecord& rec, CivPluginStatus status, const std::string& problem)
	{
		rec.status = status;
		rec.problems.push_back(problem);
		CivHostLog("Plugin %s: %s", rec.name.c_str(), problem.c_str());
	}

	bool RefusedForTakenId(int plugin)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		const bool keepsData = CivRegisterPendingSave() || CivValuesPending();
		const bool publishes = CivFunctionsPending();
		if (!keepsData && !publishes)
			return false;
		const std::string id = rec.pluginId.empty() ? "no plugin ID" : "the plugin ID \"" + rec.pluginId + "\"";
		for (int i = 0; i < plugin; ++i)
		{
			const CivPluginRecord& other = s_plugins[i];
			if (!CivSameSaveKey(other, rec.modId, rec.pluginId))
				continue;
			if (keepsData && (other.saveFn || CivValuesDeclaredBy(i)))
			{
				Refuse(rec, CIV_PLUGIN_ID_TAKEN, CivHostFormat("%s, higher in the list, comes from the same mod and keeps its data in saves with %s too, so this plugin was not loaded, or their data would mix. Each plugin of a mod that keeps data in saves needs a plugin ID of its own; ask the plugin's author to fix this.",
					other.name.c_str(), id.c_str()));
				return true;
			}
			if (publishes && CivFunctionsPublishedBy(i))
			{
				Refuse(rec, CIV_PLUGIN_ID_TAKEN, CivHostFormat("%s, higher in the list, comes from the same mod and publishes functions with %s too, so this plugin was not loaded. Each plugin of a mod that publishes functions needs a plugin ID of its own, so that other plugins can tell whose functions they find; ask the plugin's author to fix this.",
					other.name.c_str(), id.c_str()));
				return true;
			}
		}
		return false;
	}

	bool ListedAbove(int plugin)
	{
		for (int i = 0; i < plugin; ++i)
			if (CivSameText(s_plugins[i].path, s_plugins[plugin].path))
				return true;
		return false;
	}

	const KeptPlugin* KeptInMemory(const std::string& path)
	{
		for (size_t i = 0; i < s_kept.size(); ++i)
			if (CivSameText(s_kept[i].path, path))
				return &s_kept[i];
		return 0;
	}

	bool RefusedForApiVersion(CivPluginRecord& rec)
	{
		CivApiVersion built = {0, 0};
		int builtRelease = 0;
		DWORD openError = 0;
		const CivExportRead read = CivImageReadApi(rec.path, &built, &builtRelease, &openError);
		if (read == CIV_EXPORT_NOT_OPENED)
		{
			Refuse(rec, CIV_PLUGIN_FILE_NOT_LOADED, CivHostFormat("Windows could not open the file (error %lu).", openError));
			return true;
		}
		if (read == CIV_EXPORT_64_BIT)
		{
			Refuse(rec, CIV_PLUGIN_FILE_NOT_LOADED, "It is a 64-bit DLL, and Civilization V can only load 32-bit ones.");
			return true;
		}
		if (read == CIV_EXPORT_MISSING)
		{
			Refuse(rec, CIV_PLUGIN_NO_API_VERSION, "The file does not say which Bazaar it was built for (it has no "
				CIV_PLUGIN_API_VERSION_NAME "), so it was built for an older Bazaar or is not a plugin.");
			return true;
		}
		rec.builtApiMajor = built.major;
		rec.builtApiMinor = built.minor;
		rec.builtApiRelease = builtRelease;
		const CivApiNumbers hostApi = {CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR, CIV_HOST_API_RELEASE};
		const CivApiNumbers builtApi = {built.major, built.minor, builtRelease};
		switch (CivApiFitOf(hostApi, builtApi))
		{
		case CIV_API_RUNS:
			return false;
		case CIV_API_NEWER_VERSION:
			Refuse(rec, CIV_PLUGIN_NEWER_API, CivHostFormat("Built for a newer Bazaar (API %d.%d); this Bazaar is API %d.%d.",
				built.major, built.minor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR));
			break;
		case CIV_API_LATER_RELEASE:
			Refuse(rec, CIV_PLUGIN_NEWER_API, CivHostFormat("Built for a newer Bazaar: it needs Bazaar %d.%d.%d or a later %d.%d release, "
				"and this Bazaar is an earlier one.", built.major, built.minor, builtRelease, built.major, built.minor));
			break;
		case CIV_API_OLDER_VERSION:
		default:
			Refuse(rec, CIV_PLUGIN_OLDER_API, CivHostFormat("Built for Bazaar API %d.%d, an older version, which this Bazaar (API %d.%d) "
				"cannot run. Rebuild it with Bazaar %d.%d's SDK.", built.major, built.minor, CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR,
				CIV_HOST_API_MAJOR, CIV_HOST_API_MINOR));
		}
		return true;
	}

	int AddRecord(const CivPluginFile& file)
	{
		CivPluginRecord rec;
		rec.path = CivFullPath(file.path);
		rec.modId = file.modId;
		rec.name = CivFileName(rec.path);
		rec.serial = ++s_lastSerial;
		s_plugins.push_back(rec);
		return (int)s_plugins.size() - 1;
	}

	// Nothing here may run the plugin's code: a refused plugin must never run.
	bool RefusedBeforeLoading(int plugin)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		if (ListedAbove(plugin))
		{
			Refuse(rec, CIV_PLUGIN_DUPLICATE, "It is listed more than once, so this listing was skipped.");
			return true;
		}
		if (const KeptPlugin* kept = KeptInMemory(rec.path))
		{
			rec.name = kept->name;
			Refuse(rec, CIV_PLUGIN_STILL_IN_MEMORY, "It could not be shut down safely earlier, so it stays off until you restart Civilization V.");
			return true;
		}
		return RefusedForApiVersion(rec);
	}

	void CopyDescription(CivPluginRecord& rec, const CivPluginInfo& info)
	{
		char text[256];
		if (CopyPluginText(info.name, text, sizeof(text)) && *text)
			rec.name = text;
		CopyPluginText(info.version, text, sizeof(text));
		rec.version = text;
		CopyPluginText(info.id, text, sizeof(text));
		rec.pluginId = text;
	}

	// When this is false, the plugin was refused and what it registered was discarded.
	bool EntryAccepted(int plugin)
	{
		// Held across the entry function: nothing a plugin can call while it loads adds or removes a record.
		CivPluginRecord& rec = s_plugins[plugin];
		// Lets a plugin's own helper DLLs load from its folder rather than the game's.
		HMODULE module = LoadLibraryExW(CivWide(rec.path).c_str(), 0, LOAD_WITH_ALTERED_SEARCH_PATH);
		if (!module)
		{
			Refuse(rec, CIV_PLUGIN_FILE_NOT_LOADED, CivHostFormat("Windows could not load the file (error %lu).", GetLastError()));
			return false;
		}
		CivPluginEntryFn entry = (CivPluginEntryFn)GetProcAddress(module, CIV_PLUGIN_ENTRY_NAME);
		if (!entry)
		{
			Refuse(rec, CIV_PLUGIN_NO_ENTRY, "The file has no " CIV_PLUGIN_ENTRY_NAME " function, so it is not a plugin.");
			CivCrashForgetModule(module);
			FreeLibrary(module);
			return false;
		}

		rec.module = module;
		rec.host = CivRegisterNewHostInfo(plugin);
		CivPluginInfo info = { 0, 0, 0 };
		CivEntryCall call = { entry, rec.host, &info, false };
		CivRegisterDiscard();
		unsigned int code = 0;
		const bool ran = CivCallsEntry(&call, &code);
		CopyDescription(rec, info);
		if (!ran)
		{
			CivRegisterDiscard();
			rec.quarantined = true;
			// Authors' copies of the in-game checker find load crashes by these words; see Quarantine in CivHostCalls.cpp.
			Refuse(rec, CIV_PLUGIN_FAULTED_AT_LOAD, CivHostFormat("It stopped working while loading (code 0x%08X) and was turned off until you return to the main menu.", code));
			CivCallsLogCrash(&code);
			return false;
		}
		if (!call.accepted)
		{
			CivRegisterDiscard();
			Refuse(rec, CIV_PLUGIN_ENTRY_DECLINED, "Declined to load.");
			Unload(plugin);
			return false;
		}
		return true;
	}

	void KeepOrTurnAway(int plugin)
	{
		CivPluginRecord& rec = s_plugins[plugin];
		if (RefusedForTakenId(plugin))
		{
			CivRegisterDiscard();
			Unload(plugin);
			return;
		}
		const CivPluginStatus verdict = CivConflictsVerdict(plugin);
		if (verdict != CIV_PLUGIN_LOADED)
		{
			CivRegisterDiscard();
			rec.status = verdict;
			Unload(plugin);
			return;
		}
		CivRegisterCommit(plugin);
		rec.status = CIV_PLUGIN_LOADED;
		CivHostLog("Plugin %s %s loaded (built for API %d.%d.%d).", rec.name.c_str(), rec.version.c_str(), rec.builtApiMajor, rec.builtApiMinor,
			rec.builtApiRelease);
	}

	void LoadOne(const CivPluginFile& file)
	{
		const int plugin = AddRecord(file);
		if (!RefusedBeforeLoading(plugin) && EntryAccepted(plugin))
			KeepOrTurnAway(plugin);
	}

	bool SameAsListed(const std::vector<CivPluginFile>& files)
	{
		if (files.size() != s_plugins.size())
			return false;
		for (size_t i = 0; i < files.size(); ++i)
			if (!CivSameText(CivFullPath(files[i].path), s_plugins[i].path) || !CivSameText(files[i].modId, s_plugins[i].modId))
				return false;
		return true;
	}
}

void CivHostLog(const char* format, ...)
{
	char line[1024];
	va_list args;
	va_start(args, format);
	_vsnprintf_s(line, sizeof(line), _TRUNCATE, format, args);
	va_end(args);
	if (s_logSink)
		s_logSink(line);
	OutputDebugStringA(line);
	OutputDebugStringA("\n");
}

std::string CivHostFormat(const char* format, ...)
{
	char text[1024];
	va_list args;
	va_start(args, format);
	_vsnprintf_s(text, sizeof(text), _TRUNCATE, format, args);
	va_end(args);
	return text;
}

bool CivHostAlive(int plugin)
{
	return plugin >= 0 && plugin < (int)s_plugins.size() && !s_plugins[plugin].quarantined;
}

CivPluginRecord& CivHostRecord(int plugin)
{
	return s_plugins[plugin];
}

void CivHostSetLogSink(CivHostLogSink sink)
{
	s_logSink = sink;
}

const std::vector<CivPluginRecord>& CivHostPlugins()
{
	return s_plugins;
}

void CivHostLogLine(const char* line)
{
	CivHostLog("%s", line);
}

CivApiFit CivApiFitOf(const CivApiNumbers& host, const CivApiNumbers& built)
{
	if (built.major > host.major || (built.major == host.major && built.minor > host.minor))
		return CIV_API_NEWER_VERSION;
	if (built.major != host.major || built.minor != host.minor)
		return CIV_API_OLDER_VERSION;
	return built.release > host.release ? CIV_API_LATER_RELEASE : CIV_API_RUNS;
}

const char* CivHostPluginName(int plugin)
{
	return DisplayName(plugin);
}

bool CivSameSaveKey(const std::string& modIdA, const std::string& pluginIdA, const std::string& modIdB, const std::string& pluginIdB)
{
	return CivSameText(modIdA, modIdB) && CivSameText(pluginIdA, pluginIdB);
}

bool CivSameSaveKey(const CivPluginRecord& plugin, const std::string& modId, const std::string& pluginId)
{
	return CivSameSaveKey(plugin.modId, plugin.pluginId, modId, pluginId);
}

std::vector<CivPluginReportRow> CivHostReportRows()
{
	std::vector<CivPluginReportRow> rows;
	for (size_t i = 0; i < s_plugins.size(); ++i)
	{
		const CivPluginRecord& p = s_plugins[i];
		CivPluginReportRow row;
		row.file = CivFileName(p.path);
		row.name = p.name;
		row.version = p.version;
		row.failed = p.status != CIV_PLUGIN_LOADED || p.quarantined;
		// Mod authors' checks files compare these words, and CivHostOrder.cpp's, so they stay as they are.
		if (p.quarantined)
			row.status = "Turned off after a crash";
		else if (row.failed)
			row.status = CIV_REPORT_NOT_LOADED;
		else
			row.status = "Loaded";
		for (size_t j = 0; j < p.problems.size(); ++j)
			row.problems += (j ? "\n" : "") + p.problems[j];
		for (size_t j = 0; j < p.notes.size(); ++j)
			row.problems += (row.problems.empty() ? "" : "\n") + p.notes[j];
		row.conflictsWith = p.conflictsWith;
		rows.push_back(row);
	}
	return rows;
}

void CivHostLoadPlugins(const std::vector<CivPluginFile>& files)
{
	for (size_t i = 0; i < files.size(); ++i)
		LoadOne(files[i]);
}

CivPluginListResult CivHostSetPlugins(const std::vector<CivPluginFile>& files, const CivFilePairs& useBoth)
{
	if (SameAsListed(files) && useBoth == CivConflictsUseBoth())
		return CIV_PLUGINS_UNCHANGED;
	if (!CivHostUnloadPlugins())
		return CIV_PLUGINS_BUSY;
	CivConflictsSetUseBoth(useBoth);
	if (!files.empty())
		CivHostLog("---- Loading plugins");
	CivHostLoadPlugins(files);
	return CIV_PLUGINS_CHANGED;
}

bool CivHostUnloadPlugins()
{
	// A plugin call on the stack means its code, and the hook list that called it, are still in use.
	if (CivCallsRunning())
		return false;
	CivHookRemoveAll();
	for (size_t i = s_plugins.size(); i-- > 0;)
		if (s_plugins[i].module)
			Unload((int)i);
	s_plugins.clear();
	CivConflictsSetUseBoth(CivFilePairs());
	CivRegisterForgetStrayWrites();
	CivValuesForgetAll();
	CivFunctionsForgetAll();
	return true;
}
