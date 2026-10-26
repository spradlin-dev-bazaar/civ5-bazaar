#include "CivHostMods.h"
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

	std::string Trimmed(const std::wstring& text)
	{
		const size_t first = text.find_first_not_of(L" \t\r\n");
		if (first == std::wstring::npos)
			return std::string();
		return CivUtf8(text.substr(first, text.find_last_not_of(L" \t\r\n") - first + 1));
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

	bool At(const std::vector<std::wstring>& open, const wchar_t* parent, const wchar_t* element)
	{
		return open.size() == 3 && open[0] == L"Mod" && open[1] == parent && open[2] == element;
	}

	struct ModReader
	{
		explicit ModReader(CivModInfo* into) : mod(into), imported(false), hasVersion(false) {}

		CivModInfo* mod;
		std::vector<std::wstring> open;
		std::wstring text;
		bool imported;
		bool hasVersion;

		void Start(IXmlReader* reader, const wchar_t* name)
		{
			open.push_back(name);
			text.clear();
			if (open.size() == 1 && open[0] == L"Mod")
			{
				mod->id = CivUtf8(Attribute(reader, L"id"));
				const std::wstring version = Attribute(reader, L"version");
				hasVersion = !version.empty();
				mod->version = _wtoi(version.c_str());
			}
			else if (At(open, L"Files", L"File"))
				imported = Attribute(reader, L"import") == L"1";
		}

		void End()
		{
			if (At(open, L"Properties", L"AffectsSavedGames"))
			{
				mod->affectsSavedGames = Trimmed(text) == "1";
			}
			else if (At(open, L"Files", L"File"))
			{
				CivModFile file;
				file.path = Trimmed(text);
				file.imported = imported;
				mod->files.push_back(file);
			}
			open.pop_back();
		}
	};

	std::string FileNameOf(const std::string& path)
	{
		const size_t slash = path.find_last_of("\\/");
		return slash == std::string::npos ? path : path.substr(slash + 1);
	}

	std::string WindowsPath(const std::string& path)
	{
		std::string out = path;
		for (size_t i = 0; i < out.size(); ++i)
			if (out[i] == '/')
				out[i] = '\\';
		return out;
	}

	std::string LastFilePath(const CivModInfo& mod, const std::string& fileName, bool importedOnly)
	{
		std::string found;
		for (size_t i = 0; i < mod.files.size(); ++i)
			if ((mod.files[i].imported || !importedOnly) && CivSameText(FileNameOf(mod.files[i].path), fileName))
				found = WindowsPath(mod.files[i].path);
		return found;
	}
}

bool CivReadModInfo(const std::string& text, CivModInfo* mod)
{
	*mod = CivModInfo();
	std::wstring wide;
	if (text.compare(0, 2, "\xFF\xFE") == 0)
		wide.assign((const wchar_t*)(text.data() + 2), (text.size() - 2) / sizeof(wchar_t));
	else
		wide = CivWide(text.compare(0, 3, "\xEF\xBB\xBF") == 0 ? text.substr(3) : text);
	ComRef<IStream> stream;
	stream.p = SHCreateMemStream((const BYTE*)wide.data(), (UINT)(wide.size() * sizeof(wchar_t)));
	ComRef<IUnknown> input;
	ComRef<IXmlReader> reader;
	if (!stream.p || FAILED(CreateXmlReaderInputWithEncodingCodePage(stream.p, NULL, kUtf16, FALSE, NULL, &input.p))
		|| FAILED(CreateXmlReader(__uuidof(IXmlReader), (void**)&reader.p, NULL)) || FAILED(reader.p->SetInput(input.p)))
		return false;
	ModReader state(mod);
	XmlNodeType type;
	HRESULT result;
	while ((result = reader.p->Read(&type)) == S_OK)
	{
		if (type == XmlNodeType_Element)
		{
			const wchar_t* name = 0;
			if (FAILED(reader.p->GetLocalName(&name, NULL)) || !name)
				break;
			const bool empty = reader.p->IsEmptyElement() != FALSE;
			state.Start(reader.p, name);
			if (empty)
				state.End();
		}
		else if (type == XmlNodeType_EndElement)
			state.End();
		else if (type == XmlNodeType_Text || type == XmlNodeType_CDATA || type == XmlNodeType_Whitespace)
		{
			const wchar_t* value = 0;
			if (reader.p->GetValue(&value, NULL) == S_OK)
				state.text += value;
		}
	}
	const bool ok = result == S_FALSE && !mod->id.empty() && state.hasVersion;
	if (!ok)
		*mod = CivModInfo();
	return ok;
}

std::string CivModFilePath(const CivModInfo& mod, const std::string& fileName)
{
	return LastFilePath(mod, fileName, false);
}

std::string CivModImportedFilePath(const CivModInfo& mod, const std::string& fileName)
{
	return LastFilePath(mod, fileName, true);
}

std::vector<CivInstalledMod> CivInstalledMods(const std::string& modsFolder, std::vector<std::string>* unreadable)
{
	std::vector<CivInstalledMod> mods;
	const std::vector<CivFolderEntry> folders = CivFolderEntries(modsFolder, "*");
	for (size_t f = 0; f < folders.size(); ++f)
	{
		if (!folders[f].folder)
			continue;
		const std::string path = modsFolder + "\\" + folders[f].name;
		const std::vector<CivFolderEntry> files = CivFolderEntries(path, "*.modinfo");
		for (size_t i = 0; i < files.size(); ++i)
		{
			const std::string file = path + "\\" + files[i].name;
			std::string text;
			CivInstalledMod mod;
			mod.folder = path;
			if (CivReadFile(file, &text) && CivReadModInfo(text, &mod.info))
				mods.push_back(mod);
			else
				unreadable->push_back(file);
		}
	}
	return mods;
}
