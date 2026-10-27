#pragma once

#include "CivHostPart.h"

#include <string>

// Objects are told apart by key: a player by its number, a city or unit by its owner and its number, which the game
// reuses only when it sets up a player's slot again, and a plot by where it is.
__int64 CivObjectKey(int first, int second);
// False when the object cannot be told apart.
typedef bool (*CivHostObjectKeySink)(int objectKind, const void* object, __int64* key);
void CivHostSetObjectKeySink(CivHostObjectKeySink sink);
// Whether the object with this key still exists; without a sink, every object does.
typedef bool (*CivHostObjectAliveSink)(int objectKind, int first, int second);
void CivHostSetObjectAliveSink(CivHostObjectAliveSink sink);

// Only while a plugin's entry function runs. The number given back holds once the plugin is kept; -1 comes with why.
int CivValuesDeclare(int plugin, int objectKind, int valueType, const char* name, int flags, const void* start, std::string* problem);
void CivValuesCommitPending(const std::string& modId, const std::string& pluginId);
void CivValuesDiscardPending();
bool CivValuesPending();
bool CivValuesDeclaredBy(int plugin);
// Declared or still pending.
bool CivValuesCarryOver(int plugin, int objectKind);
void CivValuesForgetAll();
// For a new game or a save loading.
void CivValuesClearGame();
void CivValuesDropPlayer(int player);
void CivValuesReplaced(int objectKind, __int64 oldKey, const void* newObject);
// First drops, from memory too, the values of units and cities that are gone.
void CivValuesSave(std::string* part);
// Saved values no loaded plugin declares stay unclaimed and go into the next save. False when the part is damaged.
bool CivValuesLoad(CivPartReader* reader);

int CivFindValue(int plugin, const char* modId, const char* pluginId, const char* name, int objectKind, int valueType);
int CivGetIntValue(int plugin, int value, const void* object);
bool CivSetIntValue(int plugin, int value, const void* object, int n);
__int64 CivGetInt64Value(int plugin, int value, const void* object);
bool CivSetInt64Value(int plugin, int value, const void* object, __int64 n);
double CivGetDoubleValue(int plugin, int value, const void* object);
bool CivSetDoubleValue(int plugin, int value, const void* object, double n);
int CivGetTextValue(int plugin, int value, const void* object, char* buffer, int size);
bool CivSetTextValue(int plugin, int value, const void* object, const char* text);

struct CivPublishedValue
{
	int valueType;
	__int64 whole;
	double decimal;
	std::string text;
};
// For Lua, which names the object by the two numbers of its key. False when no loaded plugin publishes that value, or
// the object does not exist.
bool CivValuesGetPublished(const char* modId, const char* pluginId, const char* name, int first, int second, CivPublishedValue* out);
