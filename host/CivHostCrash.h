#pragma once

#include <windows.h>

#include <string>
#include <vector>

// Call from the exception filter, before the handler reuses the stack. A crash is not recorded while an earlier one
// waits for its report.
void CivCrashRecord(unsigned int code, const EXCEPTION_POINTERS* info, const void* owner);

// Every guarded call that caught a crash must ask for its report with the owner it recorded, or later crashes go
// unrecorded.
std::vector<std::string> CivCrashReport(const void* owner);

// Call before freeing a plugin DLL, or a DLL loaded at its address later gets the freed one's symbols.
void CivCrashForgetModule(HMODULE module);
