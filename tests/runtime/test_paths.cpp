// Folder and file names outside the system's code page, which Bazaar keeps in UTF-8 and gives Windows as wide characters.
#include "harness.h"
#include "CivHostPath.h"

namespace
{
	// "Plugins" in Russian: Cyrillic letters, which no Western code page has.
	const char* const kFolder = "\xD0\x9F\xD0\xBB\xD0\xB0\xD0\xB3\xD0\xB8\xD0\xBD\xD1\x8B";
}

void TestPaths()
{
	const std::string word = kFolder;
	Check(CivUtf8(CivWide(word)) == word, "a name outside the system's code page survives the trip to Windows and back");
	Check(CivSameText("\xC3\x84pfel.dll", "\xC3\xA4PFEL.DLL"), "file names match in any case, accented letters too");
	Check(!CivSameText("a.dll", "b.dll"), "different names do not match");
	if (GetACP() == 1252)
		Check(CivUtf8(CivWide("caf\xE9")) == "caf\xC3\xA9", "a name that is not UTF-8 is read in the system's code page");

	StartWithNone();
	const std::string folder = OutFile(kFolder);
	const std::string copy = folder + "\\toy_basic.dll";
	CreateDirectoryW(CivWide(folder).c_str(), NULL);
	Check(CopyFileW(CivWide(OutFile("toy_basic.dll")).c_str(), CivWide(copy).c_str(), FALSE) != 0, "a toy plugin is copied into a folder outside the system's code page");
	std::string text;
	Check(CivReadFile(copy, &text) && text.compare(0, 2, "MZ") == 0, "a file in such a folder can be read");
	CivHostSetPlugins(std::vector<std::string>(1, copy));
	Check(HasStatus("toy_basic.dll", CIV_PLUGIN_LOADED), "a plugin in such a folder loads");
	StartWithNone();
}
