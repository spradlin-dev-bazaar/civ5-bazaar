#include "CivHostCrash.h"
#include "CivHostPath.h"

#include <dbghelp.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#pragma comment(lib, "dbghelp.lib")

namespace
{
	const DWORD kStackCopyBytes = 64 * 1024;
	const int kMaxFrames = 64;

	// The handler reuses the stack the crash happened on, so the filter copies it here.
	struct Crash
	{
		const void* owner;
		DWORD address;
		bool hasAccess;
		ULONG_PTR accessKind;
		ULONG_PTR accessed;
		CONTEXT context;
		DWORD stackStart;
		DWORD stackBytes;
		BYTE stack[kStackCopyBytes];
	};
	Crash s_crash;

	HANDLE s_process = 0;
	bool s_symbolsTried = false;

	struct Symbol
	{
		SYMBOL_INFO info;
		char more[256];
	};

	// dbghelp's options are process-wide, shared with the game DLL's FireWorks session, so each report puts them back.
	struct SymbolOptions
	{
		DWORD saved;
		SymbolOptions() : saved(SymGetOptions())
		{
			SymSetOptions(saved | SYMOPT_DEFERRED_LOADS | SYMOPT_LOAD_LINES | SYMOPT_FAIL_CRITICAL_ERRORS | SYMOPT_NO_PROMPTS);
		}
		~SymbolOptions()
		{
			SymSetOptions(saved);
		}
	};

	// No C++ objects may live in this frame, or __try is not allowed.
	void CopyStack(DWORD esp)
	{
		const DWORD top = (DWORD)(DWORD_PTR)((const NT_TIB*)NtCurrentTeb())->StackBase;
		DWORD bytes = esp < top ? top - esp : 0;
		if (bytes > kStackCopyBytes)
			bytes = kStackCopyBytes;
		__try
		{
			memcpy(s_crash.stack, (const void*)(DWORD_PTR)esp, bytes);
			s_crash.stackBytes = bytes;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
			s_crash.stackBytes = 0;
		}
	}

	// The game DLL's FireWorks already has a session on the plain process handle, so this one uses a duplicate.
	// No C++ objects may live in this frame, or __try is not allowed.
	void StartSymbols()
	{
		__try
		{
			if (!s_symbolsTried)
			{
				s_symbolsTried = true;
				if (!DuplicateHandle(GetCurrentProcess(), GetCurrentProcess(), GetCurrentProcess(), &s_process, 0, FALSE, DUPLICATE_SAME_ACCESS))
					return;
				// "." keeps a symbol server named in the environment out of a crash; each DLL's recorded .pdb path is still tried.
				if (!SymInitialize(s_process, ".", TRUE))
				{
					CloseHandle(s_process);
					s_process = 0;
				}
				return;
			}
			if (s_process)
				SymRefreshModuleList(s_process);
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
		}
	}

	BOOL CALLBACK ReadCrashMemory(HANDLE, DWORD64 address, PVOID buffer, DWORD size, LPDWORD read)
	{
		const DWORD64 start = s_crash.stackStart;
		const DWORD64 end = start + s_crash.stackBytes;
		// dbghelp sign-extends addresses, so address + size can wrap past zero and pass an end check.
		if (address >= start && address < end && size <= end - address)
		{
			memcpy(buffer, s_crash.stack + (address - start), size);
			*read = size;
			return TRUE;
		}
		SIZE_T done = 0;
		const BOOL ok = ReadProcessMemory(GetCurrentProcess(), (LPCVOID)(DWORD_PTR)address, buffer, size, &done);
		*read = (DWORD)done;
		return ok;
	}

	bool RanCode()
	{
		return s_crash.hasAccess && (s_crash.accessKind == EXCEPTION_EXECUTE_FAULT || s_crash.accessed == s_crash.address);
	}

	// No C++ objects may live in this frame, or __try is not allowed.
	int WalkCrashStack(DWORD64* frames, int max)
	{
		if (!s_process)
			return 0;
		int count = 0;
		__try
		{
			CONTEXT context = s_crash.context;
			// A call through a bad pointer stopped before its target ran, so the caller's return address is on top.
			if (RanCode() && s_crash.stackBytes >= sizeof(DWORD))
			{
				frames[count++] = context.Eip;
				context.Eip = *(const DWORD*)s_crash.stack;
				context.Esp += sizeof(DWORD);
			}
			STACKFRAME64 frame;
			memset(&frame, 0, sizeof(frame));
			frame.AddrPC.Offset = context.Eip;
			frame.AddrPC.Mode = AddrModeFlat;
			frame.AddrFrame.Offset = context.Ebp;
			frame.AddrFrame.Mode = AddrModeFlat;
			frame.AddrStack.Offset = context.Esp;
			frame.AddrStack.Mode = AddrModeFlat;
			while (count < max
				&& StackWalk64(IMAGE_FILE_MACHINE_I386, s_process, GetCurrentThread(), &frame, &context, &ReadCrashMemory,
					SymFunctionTableAccess64, SymGetModuleBase64, 0)
				&& frame.AddrPC.Offset)
				frames[count++] = frame.AddrPC.Offset;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
		}
		return count;
	}

	const char* FileNameOf(const char* path)
	{
		const char* slash = strrchr(path, '\\');
		const char* forward = strrchr(path, '/');
		if (forward > slash)
			slash = forward;
		return slash ? slash + 1 : path;
	}

	// Without a .pdb, dbghelp names the nearest export; a record left by a freed DLL names that DLL's functions.
	// No C++ objects may live in this frame, or __try is not allowed. dbghelp names modules in the system's code page, so
	// the module's own name is read in it too.
	bool LookUp(DWORD64 address, char* name, size_t nameSize, char* file, size_t fileSize, DWORD* line)
	{
		__try
		{
			MEMORY_BASIC_INFORMATION mbi;
			char path[MAX_PATH];
			if (!s_process || !VirtualQuery((LPCVOID)(DWORD_PTR)address, &mbi, sizeof(mbi)) || !mbi.AllocationBase
				|| !GetModuleFileNameA((HMODULE)mbi.AllocationBase, path, MAX_PATH))
				return false;
			Symbol symbol;
			memset(&symbol, 0, sizeof(symbol));
			symbol.info.SizeOfStruct = sizeof(SYMBOL_INFO);
			symbol.info.MaxNameLen = sizeof(symbol.more) + 1;
			DWORD64 displacement = 0;
			IMAGEHLP_MODULE64 module;
			memset(&module, 0, sizeof(module));
			module.SizeOfStruct = sizeof(module);
			if (!SymFromAddr(s_process, address, &displacement, &symbol.info) || !SymGetModuleInfo64(s_process, address, &module))
				return false;
			if ((module.SymType != SymPdb && module.SymType != SymDia) || module.BaseOfImage != (DWORD64)(DWORD_PTR)mbi.AllocationBase
				|| _stricmp(FileNameOf(module.ImageName), FileNameOf(path)) != 0)
				return false;
			strncpy_s(name, nameSize, symbol.info.Name, _TRUNCATE);
			file[0] = 0;
			*line = 0;
			IMAGEHLP_LINE64 lineInfo;
			memset(&lineInfo, 0, sizeof(lineInfo));
			lineInfo.SizeOfStruct = sizeof(lineInfo);
			DWORD lineOffset = 0;
			if (SymGetLineFromAddr64(s_process, address, &lineOffset, &lineInfo) && lineInfo.FileName)
			{
				strncpy_s(file, fileSize, FileNameOf(lineInfo.FileName), _TRUNCATE);
				*line = lineInfo.LineNumber;
			}
			return true;
		}
		__except (EXCEPTION_EXECUTE_HANDLER)
		{
			return false;
		}
	}

	std::string Text(const char* format, ...)
	{
		char text[1024];
		va_list args;
		va_start(args, format);
		_vsnprintf_s(text, sizeof(text), _TRUNCATE, format, args);
		va_end(args);
		return text;
	}

	std::string ModuleOffset(DWORD64 address)
	{
		MEMORY_BASIC_INFORMATION mbi;
		if (!VirtualQuery((LPCVOID)(DWORD_PTR)address, &mbi, sizeof(mbi)) || !mbi.AllocationBase)
			return Text("0x%08X", (unsigned)address);
		const std::string path = CivModuleFile(mbi.AllocationBase);
		if (path.empty())
			return Text("0x%08X", (unsigned)address);
		return Text("%s+0x%08X", FileNameOf(path.c_str()), (unsigned)(address - (DWORD64)(DWORD_PTR)mbi.AllocationBase));
	}

	// A return address points just past its call, which may already be the next line or function.
	std::string Frame(DWORD64 address, bool returnAddress)
	{
		char name[256];
		char file[MAX_PATH];
		DWORD line = 0;
		std::string text = ModuleOffset(address);
		if (!LookUp(returnAddress ? address - 1 : address, name, sizeof(name), file, sizeof(file), &line))
			return text;
		return text + (file[0] ? Text(" (%s, %s line %lu)", name, file, line) : Text(" (%s)", name));
	}

	const char* AccessVerb(ULONG_PTR kind)
	{
		return kind == EXCEPTION_WRITE_FAULT ? "wrote to" : "read";
	}
}

void CivCrashRecord(unsigned int code, const EXCEPTION_POINTERS* info, const void* owner)
{
	if (s_crash.owner)
		return;
	const EXCEPTION_RECORD* record = info->ExceptionRecord;
	s_crash.address = (DWORD)(DWORD_PTR)record->ExceptionAddress;
	s_crash.hasAccess = (code == EXCEPTION_ACCESS_VIOLATION || code == EXCEPTION_IN_PAGE_ERROR) && record->NumberParameters >= 2;
	s_crash.accessKind = s_crash.hasAccess ? record->ExceptionInformation[0] : 0;
	s_crash.accessed = s_crash.hasAccess ? record->ExceptionInformation[1] : 0;
	s_crash.context = *info->ContextRecord;
	s_crash.stackStart = s_crash.context.Esp;
	CopyStack(s_crash.stackStart);
	s_crash.owner = owner;
}

std::vector<std::string> CivCrashReport(const void* owner)
{
	std::vector<std::string> lines;
	if (owner != s_crash.owner)
	{
		lines.push_back("  The call stack was not recorded, because another plugin's crash was still being reported.");
		return lines;
	}
	s_crash.owner = 0;
	const SymbolOptions options;
	StartSymbols();
	DWORD64 frames[kMaxFrames + 1];
	const int count = WalkCrashStack(frames, kMaxFrames + 1);
	if (RanCode())
		lines.push_back(Text("  It ran code at address 0x%08X.", (unsigned)s_crash.accessed));
	else if (s_crash.hasAccess)
		lines.push_back(Text("  It %s address 0x%08X, at %s.", AccessVerb(s_crash.accessKind), (unsigned)s_crash.accessed,
			Frame(s_crash.address, false).c_str()));
	else
		lines.push_back(Text("  It stopped at %s.", Frame(s_crash.address, false).c_str()));
	if (!count)
	{
		lines.push_back("  The call stack could not be read.");
		return lines;
	}
	lines.push_back("  Call stack, innermost first, as file+offset:");
	for (int i = 0; i < count && i < kMaxFrames; ++i)
		lines.push_back(Text("    #%02d %s", i, Frame(frames[i], i > 0).c_str()));
	if (count > kMaxFrames)
		lines.push_back("    (more frames not shown)");
	return lines;
}

// No C++ objects may live in this frame, or __try is not allowed.
void CivCrashForgetModule(HMODULE module)
{
	__try
	{
		if (s_process)
			SymUnloadModule64(s_process, (DWORD64)(DWORD_PTR)module);
	}
	__except (EXCEPTION_EXECUTE_HANDLER)
	{
	}
}
