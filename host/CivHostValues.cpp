#include "CivHostValues.h"
#include "CivHostLock.h"
#include "CivHostRuntime.h"

#include <stdio.h>
#include <string.h>

#include <map>
#include <vector>

namespace
{
	struct Cell
	{
		Cell() : whole(0), decimal(0) {}

		__int64 whole;
		double decimal;
		std::string text;
	};

	enum Misuse
	{
		MISUSE_WRONG_TYPE = 1,
		MISUSE_PRIVATE = 2,
		MISUSE_NOT_OWNER = 4,
	};

	struct Value
	{
		Value() : plugin(-1), objectKind(0), valueType(0), flags(0) {}

		int plugin;
		int objectKind;
		int valueType;
		int flags;
		std::string name;
		Cell start;
		std::map<__int64, Cell> cells;
		// The kinds of misuse already logged for each plugin, so a hook that runs every turn logs each once.
		std::map<int, int> logged;
	};

	// Declared only while plugins load, which never happens during a game, so only the cells and the misuse marks need
	// the lock. Plugin pointers are read before it is taken: a crash there would leave it taken.
	std::vector<Value> s_values;
	std::vector<Value> s_pending;
	CivHostObjectKeySink s_objectKey = 0;
	CivLock s_lock;

	const char* MisuseText(Misuse misuse)
	{
		switch (misuse)
		{
		case MISUSE_WRONG_TYPE:
			return "as another type than it has, so nothing was read or changed";
		case MISUSE_PRIVATE:
			return "although that plugin keeps it to itself, so it read as zero or empty";
		case MISUSE_NOT_OWNER:
			return "to change it, although only that plugin can, so it was left as it was";
		}
		return "";
	}

	void LogMisuse(Value& value, int plugin, Misuse misuse)
	{
		{
			CivLockHold hold(s_lock);
			int& logged = value.logged[plugin];
			if (logged & misuse)
				return;
			logged |= misuse;
		}
		char line[512];
		_snprintf_s(line, sizeof(line), _TRUNCATE, "Plugin %s used the value %s of %s %s. This is logged only once.",
			CivHostPluginName(plugin), value.name.c_str(), CivHostPluginName(value.plugin), MisuseText(misuse));
		CivHostLogLine(line);
	}

	// Null, after logging why once, when the plugin may not use the value this way.
	Value* Usable(int plugin, int value, int valueType, bool changing)
	{
		if (value < 0 || value >= (int)s_values.size())
			return 0;
		Value& v = s_values[value];
		if (v.valueType != valueType)
			LogMisuse(v, plugin, MISUSE_WRONG_TYPE);
		else if (changing && v.plugin != plugin)
			LogMisuse(v, plugin, MISUSE_NOT_OWNER);
		else if (!changing && v.plugin != plugin && !(v.flags & CIV_VALUE_PUBLISHED))
			LogMisuse(v, plugin, MISUSE_PRIVATE);
		else
			return &v;
		return 0;
	}

	bool KeyOf(int objectKind, const void* object, __int64* key)
	{
		return s_objectKey && object && s_objectKey(objectKind, object, key);
	}

	Cell Read(const Value& v, const void* object)
	{
		__int64 key = 0;
		if (!KeyOf(v.objectKind, object, &key))
			return v.start;
		CivLockHold hold(s_lock);
		std::map<__int64, Cell>::const_iterator found = v.cells.find(key);
		return found == v.cells.end() ? v.start : found->second;
	}

	bool Write(Value* v, const void* object, const Cell& value)
	{
		__int64 key = 0;
		if (!v || !KeyOf(v->objectKind, object, &key))
			return false;
		CivLockHold hold(s_lock);
		v->cells[key] = value;
		return true;
	}

	Cell Whole(__int64 n)
	{
		Cell cell;
		cell.whole = n;
		return cell;
	}

	Cell Decimal(double n)
	{
		Cell cell;
		cell.decimal = n;
		return cell;
	}

	int KeyOwner(__int64 key)
	{
		return (int)(key >> 32);
	}
}

__int64 CivObjectKey(int first, int second)
{
	return ((__int64)first << 32) | (unsigned int)second;
}

void CivHostSetObjectKeySink(CivHostObjectKeySink sink)
{
	s_objectKey = sink;
}

int CivValuesDeclare(int plugin, int objectKind, int valueType, const char* name, int flags, const void* start, std::string* problem)
{
	Value v;
	v.plugin = plugin;
	v.objectKind = objectKind;
	v.valueType = valueType;
	v.flags = flags;
	v.name = name ? name : "";
	if (v.name.empty())
		*problem = "it has no name";
	else if (objectKind < CIV_ON_PLAYER || objectKind > CIV_ON_PLOT)
		*problem = "it is not on players, cities, units or plots";
	else if (valueType < CIV_VALUE_INT || valueType > CIV_VALUE_TEXT)
		*problem = "its type is not one Bazaar knows";
	else if (flags & ~(CIV_VALUE_PUBLISHED | CIV_VALUE_CARRIES_OVER))
		*problem = "it asks for something Bazaar does not know";
	for (size_t i = 0; i < s_pending.size() && problem->empty(); ++i)
		if (s_pending[i].name == v.name)
			*problem = "the plugin already has a value of that name";
	if (!problem->empty())
		return -1;
	if (start && valueType == CIV_VALUE_INT)
		v.start.whole = *static_cast<const int*>(start);
	else if (start && valueType == CIV_VALUE_INT64)
		v.start.whole = *static_cast<const __int64*>(start);
	else if (start && valueType == CIV_VALUE_DOUBLE)
		v.start.decimal = *static_cast<const double*>(start);
	else if (start)
		v.start.text = static_cast<const char*>(start);
	s_pending.push_back(v);
	return (int)(s_values.size() + s_pending.size() - 1);
}

void CivValuesCommitPending()
{
	s_values.insert(s_values.end(), s_pending.begin(), s_pending.end());
	s_pending.clear();
}

void CivValuesDiscardPending()
{
	s_pending.clear();
}

bool CivValuesPending()
{
	return !s_pending.empty();
}

bool CivValuesDeclaredBy(int plugin)
{
	for (size_t i = 0; i < s_values.size(); ++i)
		if (s_values[i].plugin == plugin)
			return true;
	return false;
}

void CivValuesForgetAll()
{
	CivLockHold hold(s_lock);
	s_values.clear();
	s_pending.clear();
}

void CivValuesClearCells()
{
	CivLockHold hold(s_lock);
	for (size_t i = 0; i < s_values.size(); ++i)
		s_values[i].cells.clear();
}

void CivValuesDropPlayer(int player)
{
	CivLockHold hold(s_lock);
	for (size_t i = 0; i < s_values.size(); ++i)
	{
		Value& v = s_values[i];
		if (v.objectKind == CIV_ON_PLOT)
			continue;
		for (std::map<__int64, Cell>::iterator cell = v.cells.begin(); cell != v.cells.end();)
		{
			if (KeyOwner(cell->first) == player)
				v.cells.erase(cell++);
			else
				++cell;
		}
	}
}

void CivValuesReplaced(int objectKind, __int64 oldKey, const void* newObject)
{
	__int64 newKey = 0;
	if (!KeyOf(objectKind, newObject, &newKey))
		return;
	CivLockHold hold(s_lock);
	for (size_t i = 0; i < s_values.size(); ++i)
	{
		Value& v = s_values[i];
		if (v.objectKind != objectKind || !(v.flags & CIV_VALUE_CARRIES_OVER))
			continue;
		std::map<__int64, Cell>::const_iterator found = v.cells.find(oldKey);
		if (found != v.cells.end())
			v.cells[newKey] = found->second;
		else
			v.cells.erase(newKey);
	}
}

int CivFindValue(int, const char* modId, const char* pluginId, const char* name, int objectKind, int valueType)
{
	const std::vector<CivPluginRecord>& plugins = CivHostPlugins();
	const std::string wanted = name ? name : "";
	for (size_t i = 0; i < s_values.size(); ++i)
	{
		const Value& v = s_values[i];
		if (!(v.flags & CIV_VALUE_PUBLISHED) || v.objectKind != objectKind || v.valueType != valueType || v.name != wanted)
			continue;
		if (v.plugin < (int)plugins.size() && CivSameSaveKey(plugins[v.plugin], modId ? modId : "", pluginId ? pluginId : ""))
			return (int)i;
	}
	return -1;
}

int CivGetIntValue(int plugin, int value, const void* object)
{
	const Value* v = Usable(plugin, value, CIV_VALUE_INT, false);
	return v ? (int)Read(*v, object).whole : 0;
}

bool CivSetIntValue(int plugin, int value, const void* object, int n)
{
	return Write(Usable(plugin, value, CIV_VALUE_INT, true), object, Whole(n));
}

__int64 CivGetInt64Value(int plugin, int value, const void* object)
{
	const Value* v = Usable(plugin, value, CIV_VALUE_INT64, false);
	return v ? Read(*v, object).whole : 0;
}

bool CivSetInt64Value(int plugin, int value, const void* object, __int64 n)
{
	return Write(Usable(plugin, value, CIV_VALUE_INT64, true), object, Whole(n));
}

double CivGetDoubleValue(int plugin, int value, const void* object)
{
	const Value* v = Usable(plugin, value, CIV_VALUE_DOUBLE, false);
	return v ? Read(*v, object).decimal : 0;
}

bool CivSetDoubleValue(int plugin, int value, const void* object, double n)
{
	return Write(Usable(plugin, value, CIV_VALUE_DOUBLE, true), object, Decimal(n));
}

int CivGetTextValue(int plugin, int value, const void* object, char* buffer, int size)
{
	const Value* v = Usable(plugin, value, CIV_VALUE_TEXT, false);
	const std::string text = v ? Read(*v, object).text : std::string();
	if (buffer && size > 0)
	{
		const size_t copied = text.size() < (size_t)(size - 1) ? text.size() : (size_t)(size - 1);
		memcpy(buffer, text.data(), copied);
		buffer[copied] = 0;
	}
	return (int)text.size();
}

bool CivSetTextValue(int plugin, int value, const void* object, const char* text)
{
	Cell cell;
	cell.text = text ? text : "";
	return Write(Usable(plugin, value, CIV_VALUE_TEXT, true), object, cell);
}
