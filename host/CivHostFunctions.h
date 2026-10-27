#pragma once

#include <string>

// Called only while a plugin's entry function runs; false comes with why.
bool CivFunctionsPublish(int plugin, const char* name, const char* signature, void* fn, std::string* problem);
void CivFunctionsCommitPending(const std::string& modId, const std::string& pluginId);
void CivFunctionsDiscardPending();
void CivFunctionsForgetAll();
bool CivFunctionsPending();
bool CivFunctionsPublishedBy(int plugin);
int CivFunctionsFind(int plugin, const char* modId, const char* pluginId, const char* name, const char* signature);
bool CivFunctionsGet(int function, int* plugin, void** fn);
const char* CivFunctionsName(int function);
