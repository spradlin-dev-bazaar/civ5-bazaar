#include "CivHostDlc.h"
#include "CivHostPath.h"

#include <windows.h>
#include <objbase.h>
#include <shlwapi.h>
#include <stdlib.h>
#include <xmllite.h>

#pragma comment(lib, "shlwapi.lib")
#pragma comment(lib, "xmllite.lib")

namespace
{
	const UINT kUtf16 = 1200;

	template<class T> class ComRef
	{
	public:
		ComRef() : p(0) {}
		~ComRef()
		{
			if (p)
				p->Release();
		}
		T* p;

	private:
		ComRef(const ComRef&);
		ComRef& operator=(const ComRef&);
	};

	std::wstring Trimmed(const std::wstring& text)
	{
		const size_t first = text.find_first_not_of(L" \t\r\n");
		if (first == std::wstring::npos)
			return std::wstring();
		return text.substr(first, text.find_last_not_of(L" \t\r\n") - first + 1);
	}

	std::wstring Attribute(IXmlReader* reader, const wchar_t* name)
	{
		std::wstring value;
		const wchar_t* text = 0;
		if (reader->MoveToAttributeByName(name, NULL) == S_OK && reader->GetValue(&text, NULL) == S_OK)
			value = text;
		reader->MoveToElement();
		return value;
	}

	// Package files come saved as UTF-16, as UTF-8 or in the system's code page, whatever their declaration says.
	std::wstring Decoded(const std::string& bytes)
	{
		if (bytes.compare(0, 2, "\xFF\xFE") == 0)
			return std::wstring((const wchar_t*)(bytes.data() + 2), (bytes.size() - 2) / sizeof(wchar_t));
		return CivWide(bytes.compare(0, 3, "\xEF\xBB\xBF") == 0 ? bytes.substr(3) : bytes);
	}

	bool IsPriority(const std::vector<std::wstring>& open)
	{
		return open.size() == 2 && open[0] == L"Civ5Package" && open[1] == L"Priority";
	}

	bool InSkin(const std::vector<std::wstring>& open, const wchar_t* entry)
	{
		return open.size() == 4 && open[0] == L"Civ5Package" && open[1] == L"UISkin" && (open[2] == L"Skin" || open[2] == L"GameplaySkin")
			&& open[3] == entry;
	}

	bool ReadSkin(const std::string& file, const std::string& packFolder, CivDlcSkin* skin)
	{
		std::string bytes;
		if (!CivReadFile(file, &bytes))
			return false;
		const std::wstring wide = Decoded(bytes);
		ComRef<IStream> stream;
		stream.p = SHCreateMemStream((const BYTE*)wide.data(), (UINT)(wide.size() * sizeof(wchar_t)));
		ComRef<IUnknown> input;
		ComRef<IXmlReader> reader;
		if (!stream.p || FAILED(CreateXmlReaderInputWithEncodingCodePage(stream.p, NULL, kUtf16, FALSE, NULL, &input.p))
			|| FAILED(CreateXmlReader(__uuidof(IXmlReader), (void**)&reader.p, NULL)) || FAILED(reader.p->SetInput(input.p)))
			return false;
		std::vector<std::wstring> open;
		bool braveSkin = false;
		std::wstring text;
		XmlNodeType type;
		HRESULT result;
		while ((result = reader.p->Read(&type)) == S_OK)
		{
			bool ends = type == XmlNodeType_EndElement;
			if (type == XmlNodeType_Element)
			{
				const wchar_t* name = 0;
				if (FAILED(reader.p->GetLocalName(&name, NULL)) || !name)
					break;
				const std::wstring element = name;
				ends = reader.p->IsEmptyElement() != FALSE;
				if (open.size() == 1 && element == L"UISkin")
					braveSkin = Attribute(reader.p, L"set") == L"Expansion2" && Attribute(reader.p, L"platform") == L"Common";
				open.push_back(element);
				text.clear();
			}
			else if (type == XmlNodeType_Text || type == XmlNodeType_CDATA || type == XmlNodeType_Whitespace)
			{
				const wchar_t* value = 0;
				if (reader.p->GetValue(&value, NULL) == S_OK)
					text += value;
			}
			if (ends && !open.empty())
			{
				const std::wstring value = Trimmed(text);
				const bool folder = InSkin(open, L"Directory");
				if (IsPriority(open))
					skin->priority = _wtoi(value.c_str());
				// An empty name would make the pack's own folder a skin folder.
				else if (braveSkin && !value.empty() && (folder || InSkin(open, L"File")))
					(folder ? skin->folders : skin->files).push_back(CivFullPath(packFolder + "\\" + CivUtf8(value)));
				open.pop_back();
			}
		}
		return result == S_FALSE;
	}

	void ReadPackFolder(const std::string& folder, std::vector<CivDlcSkin>* skins, std::vector<std::string>* unreadable)
	{
		WIN32_FIND_DATAW package;
		HANDLE packages = FindFirstFileW(CivWide(folder + "\\*.Civ5Pkg").c_str(), &package);
		if (packages == INVALID_HANDLE_VALUE)
			return;
		do
		{
			const std::string file = folder + "\\" + CivUtf8(package.cFileName);
			CivDlcSkin skin;
			if (!ReadSkin(file, folder, &skin))
				unreadable->push_back(file);
			else if (!skin.folders.empty() || !skin.files.empty())
				skins->push_back(skin);
		} while (FindNextFileW(packages, &package));
		FindClose(packages);
	}

	std::string FindInside(const std::string& folder, const std::string& fileName)
	{
		WIN32_FIND_DATAW entry;
		HANDLE entries = FindFirstFileW(CivWide(folder + "\\*").c_str(), &entry);
		if (entries == INVALID_HANDLE_VALUE)
			return std::string();
		std::string path;
		do
		{
			const std::string name = CivUtf8(entry.cFileName);
			if (!(entry.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY))
			{
				if (CivSameText(name, fileName))
					path = folder + "\\" + name;
			}
			else if (name != "." && name != "..")
				path = FindInside(folder + "\\" + name, fileName);
		} while (path.empty() && FindNextFileW(entries, &entry));
		FindClose(entries);
		return path;
	}

	std::string ListedFile(const std::string& listed, const std::string& fileName)
	{
		const size_t slash = listed.find_last_of('\\');
		if (!PathMatchSpecW(CivWide(fileName).c_str(), CivWide(listed.substr(slash + 1)).c_str()))
			return std::string();
		const std::string path = listed.substr(0, slash) + "\\" + fileName;
		return CivExists(path) ? path : std::string();
	}

	std::string FileInSkin(const CivDlcSkin& skin, const std::string& fileName)
	{
		std::string path;
		for (size_t f = 0; path.empty() && f < skin.files.size(); ++f)
			path = ListedFile(skin.files[f], fileName);
		for (size_t f = 0; path.empty() && f < skin.folders.size(); ++f)
			path = FindInside(skin.folders[f], fileName);
		return path;
	}
}

std::vector<CivDlcSkin> CivReadDlcSkins(const std::string& gameFolder, std::vector<std::string>* unreadable)
{
	std::vector<CivDlcSkin> skins;
	const std::string dlc = gameFolder + "\\Assets\\DLC\\";
	WIN32_FIND_DATAW pack;
	HANDLE packs = FindFirstFileW(CivWide(dlc + "*").c_str(), &pack);
	if (packs == INVALID_HANDLE_VALUE)
		return skins;
	do
	{
		if ((pack.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && pack.cFileName[0] != L'.')
			ReadPackFolder(dlc + CivUtf8(pack.cFileName), &skins, unreadable);
	} while (FindNextFileW(packs, &pack));
	FindClose(packs);
	return skins;
}

std::string CivFileInDlcSkins(const std::vector<CivDlcSkin>& skins, const std::string& fileName)
{
	std::string best;
	int bestPriority = 0;
	for (size_t s = 0; s < skins.size(); ++s)
	{
		if (!best.empty() && skins[s].priority <= bestPriority)
			continue;
		const std::string path = FileInSkin(skins[s], fileName);
		if (!path.empty())
		{
			best = path;
			bestPriority = skins[s].priority;
		}
	}
	return best;
}
