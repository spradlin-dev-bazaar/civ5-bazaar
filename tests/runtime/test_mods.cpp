// Mod descriptions (.modinfo files): a mod's ID, version and files, and whether it affects saved games.
#include "harness.h"
#include "CivHostMods.h"

namespace
{
	CivModInfo Read(const std::string& text, const char* what)
	{
		CivModInfo mod;
		Check(CivReadModInfo(text, &mod), what);
		return mod;
	}

	CivModInfo WithProperties(const char* properties, const char* what)
	{
		return Read(ModDescription("mod-id", 3, properties, ""), what);
	}

	CivModInfo WithFiles(const char* files, const char* what)
	{
		return Read(ModDescription("mod-id", 3, "", files), what);
	}
}

void TestModDescriptions()
{
	const CivModInfo saves = WithProperties("    <AffectsSavedGames>1</AffectsSavedGames>\r\n", "a mod description is read");
	Check(saves.id == "mod-id" && saves.version == 3, "it gives the mod's own ID and version, not a dependency's");
	Check(saves.affectsSavedGames, "a mod that affects saved games says so");
	Check(WithProperties("    <AffectsSavedGames>\r\n      1\r\n    </AffectsSavedGames>\r\n", "a setting across lines is read").affectsSavedGames,
		"the setting counts however it is laid out");
	Check(!WithProperties("    <AffectsSavedGames>0</AffectsSavedGames>\r\n", "a setting of 0 is read").affectsSavedGames,
		"0 does not affect saved games");
	Check(!WithProperties("    <AffectsSavedGames>true</AffectsSavedGames>\r\n", "a setting of true is read").affectsSavedGames,
		"only 1 counts, as in the game's own Mods screen");
	Check(!WithProperties("    <!-- <AffectsSavedGames>1</AffectsSavedGames> -->\r\n", "a commented-out setting is read past").affectsSavedGames,
		"a commented-out setting does not count");
	Check(!Read(ModDescription("mod-id", 3, "", "    <AffectsSavedGames>1</AffectsSavedGames>\r\n"), "a setting in the wrong place is read past")
			.affectsSavedGames,
		"the setting counts only among the mod's properties");

	const CivModInfo files = WithFiles(
		"    <File md5=\"1\" import=\"0\">Plugin.dll</File>\r\n"
		"    <!-- <File import=\"1\">Old.lua</File> -->\r\n"
		"    <File import=\"1\"><![CDATA[Fish & Chips/Screen.lua]]></File>\r\n"
		"    <File import=\"1\">  First/Same.lua  </File>\r\n"
		"    <File>Unflagged.lua</File>\r\n"
		"    <File import=\"1\">Second/SAME.lua</File>\r\n"
		"    <File import=\"1\">\xD0\x9C\xD0\xBE\xD0\xB4/Screen.xml</File>\r\n",
		"a description listing files is read");
	Check(files.files.size() == 6, "each listed file is read once, and a commented-out one is not");
	Check(CivModFilePath(files, "plugin.DLL") == "Plugin.dll", "a file is found by name in any case, imported or not");
	Check(CivModImportedFilePath(files, "Plugin.dll").empty(), "a file the game does not import is left out of the imported ones");
	Check(CivModImportedFilePath(files, "Unflagged.lua").empty(), "a file with no import flag is not imported");
	Check(CivModImportedFilePath(files, "Screen.lua") == "Fish & Chips\\Screen.lua", "a path written as character data is read");
	Check(CivModImportedFilePath(files, "Old.lua").empty(), "a commented-out file is not found");
	Check(CivModImportedFilePath(files, "same.lua") == "Second\\SAME.lua", "of two files with one name, the last listed is found");
	Check(files.files[2].path == "First/Same.lua", "spaces around a path are left out");
	Check(CivModImportedFilePath(files, "Screen.xml") == "\xD0\x9C\xD0\xBE\xD0\xB4\\Screen.xml", "a path in any language is read as UTF-8");

	const CivModInfo plain = Read("<Mod id=\"plain\" version=\"2\"><Properties><Description>Caf\xE9</Description></Properties></Mod>",
		"a description with no byte order mark or declaration, and a byte from the system's code page, is read");
	Check(plain.id == "plain" && plain.version == 2, "it gives its ID and version");
	const CivModInfo declared = Read("<?xml version=\"1.0\" encoding=\"windows-1252\"?><Mod id=\"x\" version=\"1\"><Files><File>Caf\xE9.lua</File></Files></Mod>",
		"a description declaring another encoding is read");
	if (GetACP() == 1252)
		Check(declared.files.size() == 1 && declared.files[0].path == "Caf\xC3\xA9.lua", "its letters from the system's code page are read right");
	const std::wstring utf16 = L"\xFEFF<Mod id=\"wide\" version=\"4\"></Mod>";
	Check(Read(std::string((const char*)utf16.data(), utf16.size() * sizeof(wchar_t)), "a description saved as UTF-16 is read").id == "wide",
		"it gives its ID");

	CivModInfo broken;
	broken.id = "left over";
	Check(!CivReadModInfo("<Mod id=\"x\" version=\"1\"><Files></Mod>", &broken), "a description that is not valid XML is refused");
	Check(broken.id.empty(), "a refused description leaves nothing behind");
	Check(!CivReadModInfo("<Mod id=\"x\"></Mod>", &broken), "a description without a version is refused");
	Check(!CivReadModInfo("<Mod id=\"\" version=\"1\"></Mod>", &broken), "a description without an ID is refused");
	Check(!CivReadModInfo("<Other id=\"x\" version=\"1\"></Other>", &broken), "a file that is not a mod description is refused");
}
