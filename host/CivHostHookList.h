#pragma once

#include <string>
#include <vector>

const char* CivHookName(int id);
std::string CivHookShortName(int id);
void CivHookAdd(int plugin, int id, int kind, void* fn);
void CivHookRemoveAll();
// The plugin whose replacement of hookId is in effect, or -1.
int CivHookReplacer(int hookId);
// The plugins that registered for the hand-placed hook, in load order.
std::vector<int> CivHandHookPlugins(int handHook);
