#include "CivHostSaves.h"
#include "CivHostLock.h"
#include "CivHostPart.h"
#include "CivHostRuntime.h"
#include "CivHostValues.h"

#include <vector>

namespace
{
	// Raised when the layout of Bazaar's part changes; the layouts of older saves must still be read.
	const unsigned int kFormat = 3;
	const unsigned int kFormatWithValues = 2;
	const unsigned int kFormatWithCrashMark = 3;
	const char* const kDamaged = "Bazaar's part of this save is damaged, so no plugin gets its saved data.";
	const char* const kDamagedLater = "Bazaar's part of this save is damaged, so some plugins do not get their saved data.";

	struct PluginData
	{
		std::string modId;
		std::string pluginId;
		std::string data;
	};

	// Updated at every load and save, so the data of a plugin that is off, or crashed, goes into the next save unchanged.
	std::vector<PluginData> s_data;
	CivLock s_lock;

	PluginData* Find(const CivPluginRecord& plugin)
	{
		for (size_t i = 0; i < s_data.size(); ++i)
			if (CivSameSaveKey(plugin, s_data[i].modId, s_data[i].pluginId))
				return &s_data[i];
		return 0;
	}

	void Keep(const CivPluginRecord& plugin, const std::string& data)
	{
		if (PluginData* found = Find(plugin))
		{
			found->data = data;
			return;
		}
		PluginData added = { plugin.modId, plugin.pluginId, data };
		s_data.push_back(added);
	}

	std::string ReadPart(const std::string& part, bool* savedAfterCrash)
	{
		CivPartReader reader(part);
		unsigned int format = 0;
		unsigned int count = 0;
		if (!reader.Number(&format) || format == 0)
			return kDamaged;
		if (format > kFormat)
			return "This save was made with a newer Bazaar, which keeps plugin data in a way this one cannot read, so no plugin gets its saved data.";
		if (!reader.Number(&count))
			return kDamaged;
		for (unsigned int i = 0; i < count; ++i)
		{
			PluginData read;
			if (!reader.Text(&read.modId) || !reader.Text(&read.pluginId) || !reader.Text(&read.data))
				return kDamagedLater;
			s_data.push_back(read);
		}
		if (format >= kFormatWithValues && !CivValuesLoad(&reader))
			return kDamagedLater;
		unsigned int crashed = 0;
		if (format >= kFormatWithCrashMark && !reader.Number(&crashed))
			return kDamagedLater;
		*savedAfterCrash = crashed != 0;
		return std::string();
	}
}

std::string CivHostSavePart()
{
	CivLockHold hold(s_lock);
	const std::vector<CivPluginRecord>& plugins = CivHostPlugins();
	for (size_t i = 0; i < plugins.size(); ++i)
	{
		std::string data;
		if (CivHostCallSaveFunction((int)i, &data))
			Keep(plugins[i], data);
	}
	std::string part;
	CivPutNumber(&part, kFormat);
	CivPutNumber(&part, (unsigned int)s_data.size());
	for (size_t i = 0; i < s_data.size(); ++i)
	{
		CivPutText(&part, s_data[i].modId);
		CivPutText(&part, s_data[i].pluginId);
		CivPutText(&part, s_data[i].data);
	}
	CivValuesSave(&part);
	CivPutNumber(&part, CivHostGameMayBeDamaged() ? 1u : 0u);
	return part;
}

std::string CivHostLoadPart(const std::string* part, bool* savedAfterCrash)
{
	CivLockHold hold(s_lock);
	s_data.clear();
	CivValuesClearGame();
	bool crashed = false;
	const std::string problem = part ? ReadPart(*part, &crashed) : std::string();
	if (savedAfterCrash)
		*savedAfterCrash = crashed;
	const std::vector<CivPluginRecord>& plugins = CivHostPlugins();
	for (size_t i = 0; i < plugins.size(); ++i)
	{
		const PluginData* found = Find(plugins[i]);
		CivHostCallLoadFunction((int)i, found ? &found->data : 0);
	}
	return problem;
}
