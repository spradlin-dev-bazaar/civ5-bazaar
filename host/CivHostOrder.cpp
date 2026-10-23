#include "CivHostOrder.h"

#include <string.h>

namespace
{
	const char* const kLoad = "load";
	const char* const kSkip = "skip";

	bool SameFile(const std::string& a, const std::string& b)
	{
		return _stricmp(a.c_str(), b.c_str()) == 0;
	}

	bool Contains(const std::vector<std::string>& files, const std::string& file)
	{
		for (size_t i = 0; i < files.size(); ++i)
			if (SameFile(files[i], file))
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

	bool TakeLoadedRow(const std::vector<CivPluginReportRow>& loaded, const std::string& file, std::vector<bool>* taken,
		CivPluginReportRow* row)
	{
		for (size_t i = 0; i < loaded.size(); ++i)
		{
			if ((*taken)[i] || !SameFile(loaded[i].file, file))
				continue;
			(*taken)[i] = true;
			*row = loaded[i];
			return true;
		}
		return false;
	}
}

std::vector<CivOrderEntry> CivApplyOrder(const std::vector<std::string>& listedFiles, const std::vector<CivOrderEntry>& saved)
{
	std::vector<bool> placed(listedFiles.size(), false);
	std::vector<CivOrderEntry> order;
	for (size_t s = 0; s < saved.size(); ++s)
	{
		for (size_t l = 0; l < listedFiles.size(); ++l)
		{
			if (placed[l] || !SameFile(listedFiles[l], saved[s].file))
				continue;
			placed[l] = true;
			CivOrderEntry entry = saved[s];
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
			listed = SameFile(kept[k].file, saved[s].file);
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
		text += std::string(e.skip ? kSkip : kLoad) + "\t" + Field(e.file) + "\t" + Field(e.name) + "\t" + Field(e.version) + "\r\n";
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
		order.push_back(entry);
	}
	return order;
}

std::vector<CivPluginReportRow> CivOrderReportRows(const std::vector<CivOrderEntry>& order, const std::vector<std::string>& missing,
	const std::vector<CivPluginReportRow>& loaded)
{
	std::vector<CivPluginReportRow> rows;
	std::vector<bool> taken(loaded.size(), false);
	for (size_t i = 0; i < order.size(); ++i)
	{
		const CivOrderEntry& e = order[i];
		CivPluginReportRow row;
		row.name = e.name.empty() ? e.file : e.name;
		row.version = e.version;
		if (e.skip)
		{
			row.status = "Skipped";
			row.skipped = true;
		}
		else if (Contains(missing, e.file))
		{
			row.status = CIV_REPORT_NOT_LOADED;
			row.problems = CIV_REPORT_FILE_NOT_FOUND;
			row.failed = true;
		}
		else if (!TakeLoadedRow(loaded, e.file, &taken, &row))
		{
			row.status = CIV_REPORT_NOT_LOADED;
			row.failed = true;
		}
		row.file = e.file;
		rows.push_back(row);
	}
	return rows;
}
