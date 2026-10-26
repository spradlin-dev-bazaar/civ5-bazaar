#pragma once

// What the runtime test sections share. Each section loads the plugins it needs first, so any one can run alone and in
// any order. A section that leaves a plugin in memory on purpose uses a toy no other section loads, and runs at most once
// per process, because the host refuses that toy until the process ends.
#include "CivHostRuntime.h"
#include "toy_api.h"

#include <windows.h>

#include <string>
#include <vector>

void Check(bool ok, const char* what);
std::string OutFile(const char* name);
std::vector<std::string> OutFiles(const char* const* names, size_t count);
template<size_t N> std::vector<std::string> OutFiles(const char* const (&names)[N])
{
	return OutFiles(names, N);
}

// Unloads every plugin, clears the log and loads these, top first.
void StartWith(const char* const* names, size_t count);
template<size_t N> void StartWith(const char* const (&names)[N])
{
	StartWith(names, N);
}
void StartWithNone();
// Adds one plugin without unloading the others.
void Load(const char* name);

const CivPluginRecord* Find(const char* fileName);
CivPluginReportRow ReportRow(const char* fileName);
bool HasStatus(const char* fileName, CivPluginStatus status);
bool IsQuarantined(const char* fileName);
bool IsInMemory(const char* fileName);

void ClearLog();
int LogIndex(const char* text, int from = 0);
std::string LogLine(int index);
bool LogHas(const char* text);
int FaultCount();
bool LastFaultWhileShuttingDown();

FARPROC ToyExport(const char* fileName, const char* function);
// A toy's export, looked up as the type toy_api.h gives it; null when the toy is not loaded.
#define TOY_FUNCTION(fileName, name) (reinterpret_cast<name##Fn*>(ToyExport(fileName, #name)))
int Call(int (*fn)(), int fallback);
