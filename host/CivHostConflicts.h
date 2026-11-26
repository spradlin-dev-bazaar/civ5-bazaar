#pragma once

#include "CivHostRuntime.h"

// When a plugin higher in the list already replaces hookId, marks the loading plugin to be turned away and gives back
// the problem; otherwise gives back nothing.
std::string CivConflictsTurnAwayIfReplaced(int hookId);
// Called while plugin, the loading plugin, registers a replacement or a hand-placed hook.
void CivConflictsOnReplace(int plugin, int hookId);
void CivConflictsOnHandHook(int handHook);
// Whether the loading plugin can load. Unless it is turned away for a replacement already taken, its possible conflicts
// are recorded on its record and in the log.
CivPluginStatus CivConflictsVerdict(int plugin);
void CivConflictsForget();
const CivFilePairs& CivConflictsUseBoth();
void CivConflictsSetUseBoth(const CivFilePairs& useBoth);
