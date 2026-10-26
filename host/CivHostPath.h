#pragma once

#include <string>
#include <vector>

// Bazaar keeps paths and file names in UTF-8, as the game's database and Lua hold them, and gives them to Windows as
// wide characters, so a name outside the system's code page still works.

// Text that is not valid UTF-8, such as a name from a file saved in the system's code page, is read in that code page.
std::wstring CivWide(const std::string& utf8);
std::string CivUtf8(const std::wstring& wide);

// Without regard to case, as Windows compares file names; for paths and mod IDs too.
bool CivSameText(const std::string& a, const std::string& b);
std::string CivFullPath(const std::string& path);
bool CivExists(const std::string& path);
bool CivReadFile(const std::string& path, std::string* text);
// The file of the DLL or program loaded at this address; NULL gives the game's program.
std::string CivModuleFile(const void* module);

struct CivFolderEntry
{
	std::string name;
	bool folder;
};

// The entries of folder whose names match pattern, such as "*.modinfo", without "." and "..".
std::vector<CivFolderEntry> CivFolderEntries(const std::string& folder, const char* pattern);
