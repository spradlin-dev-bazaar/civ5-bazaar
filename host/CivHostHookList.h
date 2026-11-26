#pragma once

#include <string>

const char* CivHookName(int id);
std::string CivHookShortName(int id);
void CivHookAdd(int plugin, int id, int kind, void* fn);
void CivHookRemoveAll();
