#include "CivHostImage.h"
#include "CivHostPath.h"

#include <tlhelp32.h>
#include <string.h>

namespace
{
	typedef LONG(WINAPI* QueryThreadFn)(HANDLE thread, int infoClass, void* info, ULONG size, ULONG* written);

	const int kThreadBasicInformation = 0;
	const int kThreadStartAddress = 9;

	struct ThreadBasicInfo
	{
		LONG exitStatus;
		NT_TIB* tib;
		void* clientProcess;
		void* clientThread;
		ULONG_PTR affinity;
		LONG priority;
		LONG basePriority;
	};

	// A stack value counts only if it could be a return address into the DLL: the bytes before it are one of
	// the x86 CALL forms. Ordinary numbers that merely fall inside the DLL's address range then rarely match.
	bool IsReturnInto(DWORD value, const BYTE* start, const BYTE* end)
	{
		const BYTE* p = reinterpret_cast<const BYTE*>(value);
		if (p < start + 7 || p >= end)
			return false;
		if (p[-5] == 0xE8)
			return true;
		for (int length = 2; length <= 7; ++length)
			if (p[-length] == 0xFF && (p[1 - length] & 0x38) == 0x10)
				return true;
		return false;
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	bool StackPointsInto(const NT_TIB* tib, DWORD esp, const BYTE* start, const BYTE* end)
	{
		__try
		{
			const DWORD* top = static_cast<const DWORD*>(tib->StackBase);
			for (const DWORD* p = reinterpret_cast<const DWORD*>(esp); p < top; ++p)
				if (IsReturnInto(*p, start, end))
					return true;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
		}
		return false;
	}

	// The thread is suspended only while its registers and stack are read, which takes no locks, so it
	// cannot be holding anything this thread then waits for. Anything that cannot be checked counts as
	// inside: keeping a DLL loaded is the safe mistake.
	bool ThreadIsInside(DWORD id, const BYTE* start, const BYTE* end, QueryThreadFn query)
	{
		HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, id);
		if (!thread)
			return GetLastError() != ERROR_INVALID_PARAMETER; // that error means the thread has already ended
		bool inside = true;
		DWORD exitCode = 0;
		const BYTE* entry = 0;
		ThreadBasicInfo info = {};
		if (GetExitCodeThread(thread, &exitCode) && exitCode != STILL_ACTIVE)
			inside = false;
		else if (query(thread, kThreadStartAddress, &entry, sizeof(entry), 0) == 0 && entry >= start && entry < end)
			inside = true;
		else if (query(thread, kThreadBasicInformation, &info, sizeof(info), 0) == 0 && SuspendThread(thread) != (DWORD)-1)
		{
			CONTEXT context;
			context.ContextFlags = CONTEXT_CONTROL;
			if (GetThreadContext(thread, &context))
			{
				const BYTE* eip = reinterpret_cast<const BYTE*>(context.Eip);
				inside = (eip >= start && eip < end) || StackPointsInto(info.tib, context.Esp, start, end);
			}
			ResumeThread(thread);
		}
		CloseHandle(thread);
		return inside;
	}

	bool Fits(DWORD offset, unsigned __int64 bytes, DWORD imageSize)
	{
		return offset <= imageSize && bytes <= imageSize - offset;
	}

	// Copies a named data export out of a file mapped with LOAD_LIBRARY_AS_IMAGE_RESOURCE, where GetProcAddress does not
	// work. A file that cannot be read counts as missing. No C++ objects may live in this frame, or __try is not allowed.
	CivExportRead CopyExportedData(HMODULE image, const char* name, void* out, DWORD size)
	{
		__try
		{
			// Windows marks such a handle in its low bits.
			const BYTE* base = (const BYTE*)((ULONG_PTR)image & ~(ULONG_PTR)3);
			const IMAGE_NT_HEADERS32* nt = (const IMAGE_NT_HEADERS32*)(base + ((const IMAGE_DOS_HEADER*)base)->e_lfanew);
			if (nt->OptionalHeader.Magic == IMAGE_NT_OPTIONAL_HDR64_MAGIC)
				return CIV_EXPORT_64_BIT;
			if (nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR32_MAGIC || nt->OptionalHeader.NumberOfRvaAndSizes <= IMAGE_DIRECTORY_ENTRY_EXPORT)
				return CIV_EXPORT_MISSING;
			const DWORD imageSize = nt->OptionalHeader.SizeOfImage;
			const IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT];
			if (!dir.VirtualAddress || !Fits(dir.VirtualAddress, sizeof(IMAGE_EXPORT_DIRECTORY), imageSize))
				return CIV_EXPORT_MISSING;
			const IMAGE_EXPORT_DIRECTORY* exports = (const IMAGE_EXPORT_DIRECTORY*)(base + dir.VirtualAddress);
			const unsigned __int64 count = exports->NumberOfNames;
			if (!Fits(exports->AddressOfNames, count * sizeof(DWORD), imageSize)
				|| !Fits(exports->AddressOfNameOrdinals, count * sizeof(WORD), imageSize)
				|| !Fits(exports->AddressOfFunctions, (unsigned __int64)exports->NumberOfFunctions * sizeof(DWORD), imageSize))
				return CIV_EXPORT_MISSING;
			const DWORD* names = (const DWORD*)(base + exports->AddressOfNames);
			const WORD* ordinals = (const WORD*)(base + exports->AddressOfNameOrdinals);
			const DWORD* functions = (const DWORD*)(base + exports->AddressOfFunctions);
			const size_t nameBytes = strlen(name) + 1;
			for (DWORD i = 0; i < exports->NumberOfNames; ++i)
			{
				if (!Fits(names[i], nameBytes, imageSize) || memcmp(base + names[i], name, nameBytes) != 0)
					continue;
				if (ordinals[i] >= exports->NumberOfFunctions)
					return CIV_EXPORT_MISSING;
				const DWORD rva = functions[ordinals[i]];
				// A forwarded export's address points at the forwarding text, inside the export directory.
				const bool forwarded = rva >= dir.VirtualAddress && rva - dir.VirtualAddress < dir.Size;
				if (!rva || forwarded || !Fits(rva, size, imageSize))
					return CIV_EXPORT_MISSING;
				memcpy(out, base + rva, size);
				return CIV_EXPORT_FOUND;
			}
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
		}
		return CIV_EXPORT_MISSING;
	}
}

// Windows maps the file without running any of it or loading the DLLs it imports, so a refused plugin never runs.
CivExportRead CivImageReadApi(const std::string& path, CivApiVersion* built, int* builtRelease, DWORD* openError)
{
	HMODULE image = LoadLibraryExW(CivWide(path).c_str(), 0, LOAD_LIBRARY_AS_IMAGE_RESOURCE);
	if (!image)
	{
		*openError = GetLastError();
		return CIV_EXPORT_NOT_OPENED;
	}
	const CivExportRead read = CopyExportedData(image, CIV_PLUGIN_API_VERSION_NAME, built, sizeof(*built));
	if (read == CIV_EXPORT_FOUND)
		CopyExportedData(image, CIV_PLUGIN_API_RELEASE_NAME, builtRelease, sizeof(*builtRelease));
	FreeLibrary(image);
	return read;
}

// A thread the plugin left running, even one only waiting, would crash once the DLL is gone. A thread
// started through the C runtime begins outside the DLL, so its stack is searched as well. A thread
// started after the snapshot is not seen; by then the plugin's own shutdown has already run.
bool CivImageThreadInside(HMODULE module)
{
	QueryThreadFn query = (QueryThreadFn)GetProcAddress(GetModuleHandleA("ntdll.dll"), "NtQueryInformationThread");
	if (!query)
		return true;
	HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
	if (snapshot == INVALID_HANDLE_VALUE)
		return true;
	const BYTE* start = reinterpret_cast<const BYTE*>(module);
	const IMAGE_NT_HEADERS* headers = reinterpret_cast<const IMAGE_NT_HEADERS*>(
		start + reinterpret_cast<const IMAGE_DOS_HEADER*>(start)->e_lfanew);
	const BYTE* end = start + headers->OptionalHeader.SizeOfImage;
	THREADENTRY32 entry;
	entry.dwSize = sizeof(entry);
	bool inside = false;
	for (BOOL more = Thread32First(snapshot, &entry); more && !inside; more = Thread32Next(snapshot, &entry))
		if (entry.th32OwnerProcessID == GetCurrentProcessId() && entry.th32ThreadID != GetCurrentThreadId())
			inside = ThreadIsInside(entry.th32ThreadID, start, end, query);
	CloseHandle(snapshot);
	return inside;
}
