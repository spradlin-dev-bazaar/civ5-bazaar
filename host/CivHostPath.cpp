#include "CivHostPath.h"

#include <windows.h>
#include <stdio.h>
#include <vector>

namespace
{
	std::wstring Widen(const std::string& text, UINT codePage, DWORD flags)
	{
		const int n = MultiByteToWideChar(codePage, flags, text.data(), (int)text.size(), NULL, 0);
		if (n <= 0)
			return std::wstring();
		std::wstring wide(n, L'\0');
		MultiByteToWideChar(codePage, flags, text.data(), (int)text.size(), &wide[0], n);
		return wide;
	}

	std::wstring Upper(const std::wstring& text)
	{
		if (text.empty())
			return text;
		std::wstring upper(text.size(), L'\0');
		const int n = LCMapStringW(LOCALE_INVARIANT, LCMAP_UPPERCASE, text.data(), (int)text.size(), &upper[0], (int)upper.size());
		return n == (int)text.size() ? upper : text;
	}
}

std::wstring CivWide(const std::string& utf8)
{
	if (utf8.empty())
		return std::wstring();
	const std::wstring wide = Widen(utf8, CP_UTF8, MB_ERR_INVALID_CHARS);
	return wide.empty() ? Widen(utf8, CP_ACP, 0) : wide;
}

std::string CivUtf8(const std::wstring& wide)
{
	if (wide.empty())
		return std::string();
	const int n = WideCharToMultiByte(CP_UTF8, 0, wide.data(), (int)wide.size(), NULL, 0, NULL, NULL);
	if (n <= 0)
		return std::string();
	std::string text(n, '\0');
	WideCharToMultiByte(CP_UTF8, 0, wide.data(), (int)wide.size(), &text[0], n, NULL, NULL);
	return text;
}

std::string CivShortened(const std::string& utf8, size_t most)
{
	if (utf8.size() <= most)
		return utf8;
	size_t end = most < 3 ? 0 : most - 3;
	while (end > 0 && (utf8[end] & 0xC0) == 0x80)
		--end;
	return utf8.substr(0, end) + "...";
}

bool CivSameText(const std::string& a, const std::string& b)
{
	return a == b || Upper(CivWide(a)) == Upper(CivWide(b));
}

std::string CivFullPath(const std::string& path)
{
	const std::wstring wide = CivWide(path);
	const DWORD size = GetFullPathNameW(wide.c_str(), 0, NULL, NULL);
	if (size == 0)
		return path;
	std::vector<wchar_t> full(size);
	const DWORD length = GetFullPathNameW(wide.c_str(), size, &full[0], NULL);
	return (length > 0 && length < size) ? CivUtf8(std::wstring(&full[0], length)) : path;
}

bool CivExists(const std::string& path)
{
	return GetFileAttributesW(CivWide(path).c_str()) != INVALID_FILE_ATTRIBUTES;
}

bool CivReadFile(const std::string& path, std::string* text)
{
	FILE* f = 0;
	if (_wfopen_s(&f, CivWide(path).c_str(), L"rb") != 0 || !f)
		return false;
	char buffer[4096];
	for (size_t n; (n = fread(buffer, 1, sizeof(buffer), f)) > 0;)
		text->append(buffer, n);
	fclose(f);
	return true;
}

std::string CivModuleFile(const void* module)
{
	wchar_t path[MAX_PATH];
	const DWORD length = GetModuleFileNameW((HMODULE)module, path, MAX_PATH);
	return (length > 0 && length < MAX_PATH) ? CivUtf8(std::wstring(path, length)) : std::string();
}
