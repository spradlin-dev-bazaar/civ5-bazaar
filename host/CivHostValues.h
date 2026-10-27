#pragma once

#include <string>

// Objects are told apart by key: a player by its number, a city or unit by its owner and its number, which the game
// reuses only when it sets up a player's slot again, and a plot by where it is.
__int64 CivObjectKey(int first, int second);
// False when the object cannot be told apart.
typedef bool (*CivHostObjectKeySink)(int objectKind, const void* object, __int64* key);
void CivHostSetObjectKeySink(CivHostObjectKeySink sink);

// Only while a plugin's entry function runs. The number given back holds once the plugin is kept; -1 comes with why.
int CivValuesDeclare(int plugin, int objectKind, int valueType, const char* name, int flags, const void* start, std::string* problem);
void CivValuesCommitPending();
void CivValuesDiscardPending();
bool CivValuesPending();
bool CivValuesDeclaredBy(int plugin);
void CivValuesForgetAll();
void CivValuesClearCells();
void CivValuesDropPlayer(int player);
void CivValuesReplaced(int objectKind, __int64 oldKey, const void* newObject);

int CivFindValue(int plugin, const char* modId, const char* pluginId, const char* name, int objectKind, int valueType);
int CivGetIntValue(int plugin, int value, const void* object);
bool CivSetIntValue(int plugin, int value, const void* object, int n);
__int64 CivGetInt64Value(int plugin, int value, const void* object);
bool CivSetInt64Value(int plugin, int value, const void* object, __int64 n);
double CivGetDoubleValue(int plugin, int value, const void* object);
bool CivSetDoubleValue(int plugin, int value, const void* object, double n);
int CivGetTextValue(int plugin, int value, const void* object, char* buffer, int size);
bool CivSetTextValue(int plugin, int value, const void* object, const char* text);
