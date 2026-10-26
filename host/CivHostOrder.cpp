#include "CivHostOrder.h"
#include "CivHostPath.h"

namespace
{
	const char* const kLoad = "load";
	const char* const kSkip = "skip";

	bool Contains(const std::vector<std::string>& files, const std::string& file)
	{
		for (size_t i = 0; i < files.size(); ++i)
			if (CivSameText(files[i], file))
				return true;
		return false;
	}

	std::vector<std::string> Split(const std::string& text, char separator)
	{
		std::vector<std::string> parts;
		size_t start = 0;
		for (;;)
		{
			const size_t end = text.find(separator, start);
			if (end == std::string::npos)
			{
				parts.push_back(text.substr(start));
				return parts;
			}
			parts.push_back(text.substr(start, end - start));
			start = end + 1;
		}
	}

	// Tabs and line breaks separate the saved fields, so none may appear inside one.
	std::string Field(const std::string& text)
	{
		std::string field = text;
		for (size_t i = 0; i < field.size(); ++i)
			if (field[i] == '\t' || field[i] == '\r' || field[i] == '\n')
				field[i] = ' ';
		return field;
	}

	// A choice is saved on one plugin's line but holds for both, so each of the two rows lists the other.
	std::vector<std::string> UseBothPartners(const std::vector<CivOrderEntry>& order, const std::string& file)
	{
		std::vector<std::string> partners;
		for (size_t i = 0; i < order.size(); ++i)
		{
			for (size_t j = 0; j < order[i].useBothWith.size(); ++j)
			{
				const std::string& a = order[i].file;
				const std::string& b = order[i].useBothWith[j];
				const std::string partner = CivSameText(a, file) ? b : (CivSameText(b, file) ? a : std::string());
				if (!partner.empty() && !Contains(partners, partner))
					partners.push_back(partner);
			}
		}
		return partners;
	}

	const CivNotLoaded* FindNotLoaded(const std::vector<CivNotLoaded>& notLoaded, const std::string& file)
	{
		for (size_t i = 0; i < notLoaded.size(); ++i)
			if (CivSameText(notLoaded[i].file, file))
				return &notLoaded[i];
		return 0;
	}

	bool TakeLoadedRow(const std::vector<CivPluginReportRow>& loaded, const std::string& file, std::vector<bool>* taken,
		CivPluginReportRow* row)
	{
		for (size_t i = 0; i < loaded.size(); ++i)
		{
			if ((*taken)[i] || !CivSameText(loaded[i].file, file))
				continue;
			(*taken)[i] = true;
			*row = loaded[i];
			return true;
		}
		return false;
	}
}

std::vector<CivOrderEntry> CivOrderListedFiles(const std::vector<std::string>& listedFiles, const std::vector<CivOrderEntry>& wanted)
{
	std::vector<bool> placed(listedFiles.size(), false);
	std::vector<CivOrderEntry> order;
	for (size_t w = 0; w < wanted.size(); ++w)
	{
		for (size_t l = 0; l < listedFiles.size(); ++l)
		{
			if (placed[l] || !CivSameText(listedFiles[l], wanted[w].file))
				continue;
			placed[l] = true;
			CivOrderEntry entry = wanted[w];
			entry.file = listedFiles[l];
			order.push_back(entry);
			break;
		}
	}
	for (size_t l = 0; l < listedFiles.size(); ++l)
	{
		if (placed[l])
			continue;
		CivOrderEntry entry;
		entry.file = listedFiles[l];
		order.push_back(entry);
	}
	return order;
}

std::vector<CivOrderEntry> CivKeepUnlisted(const std::vector<CivOrderEntry>& order, const std::vector<CivOrderEntry>& saved)
{
	std::vector<CivOrderEntry> kept = order;
	for (size_t s = 0; s < saved.size(); ++s)
	{
		bool listed = false;
		for (size_t k = 0; k < kept.size() && !listed; ++k)
			listed = CivSameText(kept[k].file, saved[s].file);
		if (!listed)
			kept.push_back(saved[s]);
	}
	return kept;
}

std::string CivFormatOrder(const std::vector<CivOrderEntry>& order)
{
	std::string text;
	for (size_t i = 0; i < order.size(); ++i)
	{
		const CivOrderEntry& e = order[i];
		text += std::string(e.skip ? kSkip : kLoad) + "\t" + Field(e.file) + "\t" + Field(e.name) + "\t" + Field(e.version);
		for (size_t j = 0; j < e.useBothWith.size(); ++j)
			text += "\t" + Field(e.useBothWith[j]);
		text += "\r\n";
	}
	return text;
}

std::vector<CivOrderEntry> CivParseOrder(const std::string& text)
{
	std::vector<CivOrderEntry> order;
	const char* const bom = "\xEF\xBB\xBF";
	const std::vector<std::string> lines = Split(text.compare(0, 3, bom) == 0 ? text.substr(3) : text, '\n');
	for (size_t i = 0; i < lines.size(); ++i)
	{
		std::string line = lines[i];
		if (!line.empty() && line[line.size() - 1] == '\r')
			line.erase(line.size() - 1);
		const std::vector<std::string> fields = Split(line, '\t');
		if (fields.size() < 2 || fields[1].empty() || (fields[0] != kLoad && fields[0] != kSkip))
			continue;
		CivOrderEntry entry;
		entry.skip = fields[0] == kSkip;
		entry.file = fields[1];
		entry.name = fields.size() > 2 ? fields[2] : "";
		entry.version = fields.size() > 3 ? fields[3] : "";
		for (size_t j = 4; j < fields.size(); ++j)
			if (!fields[j].empty())
				entry.useBothWith.push_back(fields[j]);
		order.push_back(entry);
	}
	return order;
}

CivFilePairs CivUseBothPairs(const std::vector<CivOrderEntry>& order)
{
	CivFilePairs pairs;
	for (size_t i = 0; i < order.size(); ++i)
		for (size_t j = 0; j < order[i].useBothWith.size(); ++j)
			pairs.push_back(CivFilePair(order[i].file, order[i].useBothWith[j]));
	return pairs;
}

std::vector<CivPluginReportRow> CivOrderReportRows(const std::vector<CivOrderEntry>& order, const std::vector<CivNotLoaded>& notLoaded,
	const std::vector<CivPluginReportRow>& loaded)
{
	std::vector<CivPluginReportRow> rows;
	std::vector<bool> taken(loaded.size(), false);
	for (size_t i = 0; i < order.size(); ++i)
	{
		const CivOrderEntry& e = order[i];
		const CivNotLoaded* notLoadedEntry = FindNotLoaded(notLoaded, e.file);
		CivPluginReportRow row;
		row.name = e.name.empty() ? e.file : e.name;
		row.version = e.version;
		if (e.skip)
		{
			row.status = "Skipped";
			row.skipped = true;
		}
		else if (notLoadedEntry)
		{
			row.status = CIV_REPORT_NOT_LOADED;
			row.problems = notLoadedEntry->reason;
			row.failed = true;
		}
		else if (!TakeLoadedRow(loaded, e.file, &taken, &row))
		{
			row.status = CIV_REPORT_NOT_LOADED;
			row.failed = true;
		}
		row.file = e.file;
		row.useBothWith = UseBothPartners(order, e.file);
		rows.push_back(row);
	}
	return rows;
}

std::vector<CivPluginReportRow> CivWithNote(const char* warning, const std::vector<CivPluginReportRow>& rows)
{
	std::vector<CivPluginReportRow> noted;
	if (warning)
	{
		CivPluginReportRow note;
		note.name = "Bazaar";
		note.status = "Warning";
		note.problems = warning;
		noted.push_back(note);
	}
	noted.insert(noted.end(), rows.begin(), rows.end());
	return noted;
}
