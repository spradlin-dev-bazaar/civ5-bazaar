// The Plugins screen's host logic, which needs no plugins: the player's order and the Advanced Setup screen it replaced.
#include "harness.h"
#include "CivHostOrder.h"
#include "CivHostSetup.h"

#include <stdio.h>

namespace
{
	CivOrderEntry Entry(const char* file, bool skip, const char* name)
	{
		CivOrderEntry entry;
		entry.file = file;
		entry.skip = skip;
		entry.name = name;
		return entry;
	}

	void WriteText(const std::string& path, const std::string& text)
	{
		for (size_t slash = path.find('\\', 3); slash != std::string::npos; slash = path.find('\\', slash + 1))
			CreateDirectoryA(path.substr(0, slash).c_str(), 0);
		SetFileAttributesA(path.c_str(), FILE_ATTRIBUTE_NORMAL);
		FILE* f = 0;
		if (fopen_s(&f, path.c_str(), "wb") == 0 && f)
		{
			fwrite(text.data(), 1, text.size(), f);
			fclose(f);
		}
	}

	std::string ReadText(const std::string& path)
	{
		std::string text;
		FILE* f = 0;
		if (fopen_s(&f, path.c_str(), "rb") == 0 && f)
		{
			char buffer[256];
			for (size_t n; (n = fread(buffer, 1, sizeof(buffer), f)) > 0;)
				text.append(buffer, n);
			fclose(f);
		}
		return text;
	}

	std::string ModInfo(const char* id, int version, const char* files)
	{
		char head[256];
		_snprintf_s(head, sizeof(head), _TRUNCATE, "\xEF\xBB\xBF<?xml version=\"1.0\"?>\r\n<Mod id=\"%s\" version=\"%d\">\r\n", id, version);
		return std::string(head) + "  <Dependencies>\r\n    <Mod id=\"dependency\" minversion=\"0\" maxversion=\"999\" title=\"Other\" />\r\n"
			"  </Dependencies>\r\n  <Files>\r\n" + files + "  </Files>\r\n</Mod>\r\n";
	}

	CivActiveMod Active(const char* id, int version)
	{
		CivActiveMod mod;
		mod.id = id;
		mod.version = version;
		return mod;
	}

	void TestApplyOrder()
	{
		std::vector<std::string> listed;
		listed.push_back("A.dll");
		listed.push_back("b.dll");
		listed.push_back("c.dll");
		listed.push_back("A.dll");
		std::vector<CivOrderEntry> saved;
		saved.push_back(Entry("c.dll", true, "Toy C"));
		saved.push_back(Entry("gone.dll", false, ""));
		saved.push_back(Entry("a.DLL", false, ""));
		const std::vector<CivOrderEntry> order = CivApplyOrder(listed, saved);
		Check(order.size() == 4, "every listed plugin is in the order once per listing, and a saved one no longer listed is not");
		if (order.size() != 4)
			return;
		Check(order[0].file == "c.dll" && order[1].file == "A.dll" && order[2].file == "b.dll",
			"saved plugins come first in the saved order, matched in any case, then the rest in listed order");
		Check(order[0].skip, "a saved skip is kept");
		Check(!order[1].skip, "a saved plugin that was not skipped stays unskipped, though matched in another case");
		Check(!order[2].skip, "a plugin new to the order is not skipped");
		Check(order[3].file == "A.dll", "a plugin listed twice stays listed twice, so loading can refuse the second");

		std::vector<CivOrderEntry> named = order;
		named[1].name = "Toy\tA";
		named[1].version = "1.0";
		const std::vector<CivOrderEntry> parsed = CivParseOrder(CivFormatOrder(named));
		Check(parsed.size() == 4 && parsed[0].skip && parsed[3].file == "A.dll", "a saved order reads back in the same order, with the same skips");
		Check(parsed.size() == 4 && parsed[0].name == "Toy C" && parsed[1].version == "1.0", "a saved order reads back with the same names and versions");
		Check(parsed.size() == 4 && parsed[1].name == "Toy A", "a tab in a name is saved as a space");
	}

	void TestOrderText()
	{
		const std::vector<CivOrderEntry> messy = CivParseOrder("junk\nskip\tx.dll\nload\t\nload\ty.dll\r\n");
		Check(messy.size() == 2 && messy[0].skip && messy[0].file == "x.dll", "lines it does not recognise are ignored");
		Check(messy.size() == 2 && messy[1].file == "y.dll", "a Windows line end is not read as part of the file name");
		const std::vector<CivOrderEntry> marked = CivParseOrder("\xEF\xBB\xBFskip\tx.dll\n");
		Check(marked.size() == 1 && marked[0].skip, "a byte-order mark an editor added does not hide the first line");

		std::vector<CivOrderEntry> applied;
		applied.push_back(Entry("a.dll", false, ""));
		applied.push_back(Entry("b.dll", false, ""));
		std::vector<CivOrderEntry> before;
		before.push_back(Entry("off.dll", true, "Toy Off"));
		before.push_back(Entry("A.DLL", true, ""));
		const std::vector<CivOrderEntry> kept = CivKeepUnlisted(applied, before);
		Check(kept.size() == 3 && kept[2].file == "off.dll", "saving keeps a plugin whose mod is off, after the plugins listed now");
		Check(kept.size() == 3 && kept[2].skip, "a plugin whose mod is off keeps its skip when the order is saved");
		Check(kept.size() == 3 && kept[0].file == "a.dll" && !kept[0].skip, "an older saved choice does not override the order being saved");
	}

	void TestOrderRows()
	{
		std::vector<CivOrderEntry> entries;
		entries.push_back(Entry("first.dll", false, ""));
		entries.push_back(Entry("skipped.dll", true, "Toy Skipped"));
		entries.push_back(Entry("missing.dll", false, ""));
		entries.push_back(Entry("last.dll", false, ""));
		entries.push_back(Entry("ghost.dll", false, ""));
		const std::vector<std::string> missing(1, "MISSING.dll");
		std::vector<CivPluginReportRow> loaded(2);
		loaded[0].name = "Toy Last";
		loaded[0].file = "last.dll";
		loaded[1].name = "Toy First";
		loaded[1].file = "FIRST.DLL";
		const std::vector<CivPluginReportRow> rows = CivOrderReportRows(entries, missing, loaded);
		Check(rows.size() == 5, "the Plugins screen gets one row per plugin in the order");
		if (rows.size() != 5)
			return;
		Check(rows[0].name == "Toy First" && rows[3].name == "Toy Last",
			"each loaded plugin's row is matched by its file name and keeps its place among skipped and missing ones");
		Check(rows[1].skipped && !rows[1].failed && rows[1].status == "Skipped", "a skipped plugin is listed as Skipped, not as a failure");
		Check(rows[1].name == "Toy Skipped", "a skipped plugin is listed by its saved name");
		Check(rows[2].failed && rows[2].status == "Not loaded", "a missing file is listed in its place as Not loaded");
		Check(rows[2].problems == CIV_REPORT_FILE_NOT_FOUND, "a missing plugin's row says the file was not found");
		Check(rows[2].name == "missing.dll", "a missing plugin is listed by its file name");
		Check(rows[4].failed && rows[4].status == "Not loaded", "a plugin with no loaded row is listed as Not loaded, not as blank");
		Check(rows[0].file == "first.dll", "each row carries the file name as listed, which the screen sends back");
	}

	void TestUseBoth()
	{
		std::vector<CivOrderEntry> order;
		order.push_back(Entry("a.dll", false, "Toy A"));
		order.push_back(Entry("b.dll", false, "Toy B"));
		order[1].version = "2.0";
		order[1].useBothWith.push_back("a.dll");
		order[1].useBothWith.push_back("c.dll");
		const std::vector<CivOrderEntry> parsed = CivParseOrder(CivFormatOrder(order));
		Check(parsed.size() == 2 && parsed[0].useBothWith.empty(), "a plugin with no Use both anyway choice reads back with none");
		Check(parsed.size() == 2 && parsed[1].useBothWith == order[1].useBothWith && parsed[1].name == "Toy B" && parsed[1].version == "2.0",
			"a plugin's Use both anyway choices read back, after its name and version");
		const std::vector<CivOrderEntry> gap = CivParseOrder("load\tx.dll\tToy X\t1.0\t\ty.dll\n");
		Check(gap.size() == 1 && gap[0].useBothWith == std::vector<std::string>(1, "y.dll"), "an empty choice in a saved line is ignored");

		const CivFilePairs pairs = CivUseBothPairs(order);
		Check(pairs.size() == 2 && pairs[0] == CivFilePair("b.dll", "a.dll") && pairs[1] == CivFilePair("b.dll", "c.dll"),
			"each choice pairs the plugin with the one it is used with");
		const std::vector<CivPluginReportRow> rows = CivOrderReportRows(order, std::vector<std::string>(), std::vector<CivPluginReportRow>());
		Check(rows.size() == 2 && rows[1].useBothWith == order[1].useBothWith, "the Plugins screen gets each plugin's choices");
		Check(rows.size() == 2 && rows[0].useBothWith == std::vector<std::string>(1, "b.dll"), "a choice saved on one plugin's line also shows on the other plugin's row");
		std::vector<CivOrderEntry> bothLines = order;
		bothLines[0].useBothWith.push_back("B.DLL");
		const std::vector<CivPluginReportRow> bothRows = CivOrderReportRows(bothLines, std::vector<std::string>(), std::vector<CivPluginReportRow>());
		Check(bothRows.size() == 2 && bothRows[0].useBothWith.size() == 1 && bothRows[1].useBothWith.size() == 2,
			"a choice saved on both plugins' lines is listed once on each row");
		const std::vector<CivOrderEntry> kept = CivKeepUnlisted(std::vector<CivOrderEntry>(1, order[0]), order);
		Check(kept.size() == 2 && kept[1].useBothWith == order[1].useBothWith, "a plugin whose mod is off keeps its choices when the order is saved");
	}
}

void TestOrder()
{
	TestApplyOrder();
	TestOrderText();
	TestOrderRows();
	TestUseBoth();
}

void TestReplacedSetup()
{
	const std::string ras = ModInfo("ras-id", 15,
		"    <File md5=\"1\" import=\"0\">Unused/AdvancedSetup.xml</File>\r\n"
		"    <File md5=\"2\" import=\"1\">UI Overrides/AdvancedSetup.xml</File>\r\n"
		"    <File import=\"1\" md5=\"3\">UI Overrides/AdvancedSetup.lua</File>\r\n");
	std::string id;
	int version = 0;
	Check(CivModIdentity(ras, &id, &version) && id == "ras-id", "a mod description gives its ID, not a dependency's");
	Check(version == 15, "a mod description gives its version");
	Check(CivImportedFile(ras, "advancedsetup.XML") == "UI Overrides/AdvancedSetup.xml", "it finds a file the mod imports into the game, by name in any case");
	Check(CivImportedFile(ModInfo("x", 1, "    <File import=\"0\">AdvancedSetup.xml</File>\r\n"), "AdvancedSetup.xml").empty(),
		"a file the mod does not import is not counted");
	Check(CivImportedFile(ModInfo("x", 1, "    <File import=\"1\">Fish &amp; Chips/AdvancedSetup.lua</File>\r\n"), "AdvancedSetup.lua")
			== "Fish & Chips/AdvancedSetup.lua",
		"an escaped character in a path is read back");

	const std::string root = OutFile("setup_test");
	const std::string mods = root + "\\MODS";
	const std::string own = mods + "\\Bazaar (v 1)";
	const std::string game = root + "\\Game";
	const std::string rasXml = mods + "\\RAS (v 15)\\UI Overrides\\AdvancedSetup.xml";
	WriteText(mods + "\\RAS (v 15)\\RAS (v 15).modinfo", ras);
	WriteText(rasXml, "ras xml");
	WriteText(mods + "\\RAS (v 15)\\UI Overrides\\AdvancedSetup.lua", "ras lua");
	WriteText(mods + "\\Other (v 1)\\Other (v 1).modinfo", ModInfo("other-id", 1, "    <File import=\"1\">Other.lua</File>\r\n"));
	WriteText(own + "\\Bazaar (v 1).modinfo", ModInfo("bazaar-id", 1, "    <File import=\"1\">frontend/AdvancedSetup.xml</File>\r\n"));
	WriteText(own + "\\frontend\\AdvancedSetup.xml", "bazaar xml");
	WriteText(game + "\\Assets\\UI\\FrontEnd\\GameSetup\\AdvancedSetup.xml", "game xml");
	WriteText(game + "\\Assets\\UI\\FrontEnd\\GameSetup\\AdvancedSetup.lua", "game lua");
	WriteText(game + "\\Assets\\DLC\\Expansion\\UI\\FrontEnd\\GameSetup\\AdvancedSetup.xml", "expansion xml");

	std::vector<CivActiveMod> withRas;
	withRas.push_back(Active("ras-id", 15));
	withRas.push_back(Active("other-id", 1));
	withRas.push_back(Active("bazaar-id", 1));
	const CivReplacedSetup first = CivCopyReplacedSetup(mods, game, own, withRas, true);
	const std::string copy = own + "\\BazaarNextSetup";
	Check(first.copy == copy, "another active mod's screen is copied beside Bazaar under a name of its own");
	Check(ReadText(copy + ".xml") == "ras xml", "its layout is that mod's, and Bazaar's own is passed over");
	Check(ReadText(copy + ".lua") == "ras lua", "the copied script is that mod's too");
	Check(first.xmlSource == rasXml, "it says which file it copied");

	SetFileAttributesA(rasXml.c_str(), FILE_ATTRIBUTE_READONLY);
	// This copy is read-only too, and the next copy must still overwrite it.
	CivCopyReplacedSetup(mods, game, own, withRas, true);
	Check(!CivCopyReplacedSetup(mods, game, own, withRas, true).copy.empty(), "a read-only source does not stop the next copy");
	SetFileAttributesA(rasXml.c_str(), FILE_ATTRIBUTE_NORMAL);

	std::vector<CivActiveMod> withoutRas(withRas.begin() + 1, withRas.end());
	CivCopyReplacedSetup(mods, game, own, withoutRas, true);
	Check(ReadText(copy + ".xml") == "expansion xml", "with no such mod active, the game's own layout is copied");
	Check(ReadText(copy + ".lua") == "game lua", "with no such mod active, the game's own script is copied");
	CivCopyReplacedSetup(mods, game, own, withoutRas, false);
	Check(ReadText(copy + ".xml") == "game xml", "the game's base layout is used when Gods and Kings is off");
	withoutRas.push_back(Active("ras-id", 14));
	const CivReplacedSetup otherVersion = CivCopyReplacedSetup(mods, game, own, withoutRas, false);
	Check(otherVersion.xmlSource == game + "\\Assets\\UI\\FrontEnd\\GameSetup\\AdvancedSetup.xml",
		"an installed mod counts only in the version that is active");

	const CivReplacedSetup failed = CivCopyReplacedSetup(mods, root + "\\NoGame", own, withoutRas, false);
	Check(failed.copy.empty(), "a screen that cannot be copied gives no path");
	Check(failed.problem.find("Could not copy") == 0, "a screen that cannot be copied gives a reason");
}
