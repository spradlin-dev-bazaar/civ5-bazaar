#include "CivHostSaves.h"
#include "CivHostLock.h"
#include "CivHostRuntime.h"
#include "CivHostValues.h"

#include <string.h>

#include <vector>

namespace
{
	// Raised when the layout of Bazaar's part changes; the layouts of older saves must still be read.
	const unsigned int kFormat = 1;
	const char* const kDamaged = "Bazaar's part of this save is damaged, so no plugin gets its saved data.";

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

	void PutNumber(std::string* part, unsigned int n)
	{
		part->append(reinterpret_cast<const char*>(&n), sizeof(n));
	}

	void PutText(std::string* part, const std::string& text)
	{
		PutNumber(part, (unsigned int)text.size());
		part->append(text);
	}

	class PartReader
	{
	public:
		explicit PartReader(const std::string& part) : m_part(part), m_at(0) {}

		bool Number(unsigned int* n)
		{
			if (m_part.size() - m_at < sizeof(*n))
				return false;
			memcpy(n, m_part.data() + m_at, sizeof(*n));
			m_at += sizeof(*n);
			return true;
		}

		bool Text(std::string* text)
		{
			unsigned int size = 0;
			if (!Number(&size) || m_part.size() - m_at < size)
				return false;
			text->assign(m_part, m_at, size);
			m_at += size;
			return true;
		}

	private:
		const std::string& m_part;
		size_t m_at;
	};

	std::string ReadPart(const std::string& part)
	{
		PartReader reader(part);
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
				return "Bazaar's part of this save is damaged, so some plugins do not get their saved data.";
			s_data.push_back(read);
		}
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
	PutNumber(&part, kFormat);
	PutNumber(&part, (unsigned int)s_data.size());
	for (size_t i = 0; i < s_data.size(); ++i)
	{
		PutText(&part, s_data[i].modId);
		PutText(&part, s_data[i].pluginId);
		PutText(&part, s_data[i].data);
	}
	return part;
}

std::string CivHostLoadPart(const std::string* part)
{
	CivLockHold hold(s_lock);
	s_data.clear();
	CivValuesClearCells();
	const std::string problem = part ? ReadPart(*part) : std::string();
	const std::vector<CivPluginRecord>& plugins = CivHostPlugins();
	for (size_t i = 0; i < plugins.size(); ++i)
	{
		const PluginData* found = Find(plugins[i]);
		CivHostCallLoadFunction((int)i, found ? &found->data : 0);
	}
	return problem;
}
