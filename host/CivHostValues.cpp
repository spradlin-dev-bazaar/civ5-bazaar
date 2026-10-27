#include "CivHostValues.h"
#include "CivHostLock.h"
#include "CivHostRuntime.h"

#include <stdio.h>
#include <string.h>

#include <map>
#include <set>
#include <vector>

// A kind of object or a value type added to CivPluginApi.h without a case in this file's switches fails the build.
#pragma warning(error : 4062)

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

	typedef std::map<__int64, Cell> Cells;

	struct Value
	{
		Value() : plugin(-1), objectKind(0), valueType(0), flags(0) {}

		// -1 on a kept value.
		int plugin;
		std::string modId;
		std::string pluginId;
		int objectKind;
		int valueType;
		int flags;
		std::string name;
		Cell start;
		Cells cells;
		// The kinds of misuse already logged for each plugin, so a hook that runs every turn logs each once.
		std::map<int, int> logged;
	};

	// Declared only while plugins load, which never happens during a game, so only the cells and the misuse marks need
	// the lock. Plugin pointers are read before it is taken: a crash there would leave it taken.
	std::vector<Value> s_values;
	std::vector<Value> s_pending;
	// Values in the loaded save that no loaded plugin declares, written back at each save.
	std::vector<Value> s_kept;
	CivHostObjectKeySink s_objectKey = 0;
	CivHostObjectAliveSink s_objectAlive = 0;
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

	Cell CellAt(const Value& v, __int64 key)
	{
		CivLockHold hold(s_lock);
		Cells::const_iterator found = v.cells.find(key);
		return found == v.cells.end() ? v.start : found->second;
	}

	Cell Read(const Value& v, const void* object)
	{
		__int64 key = 0;
		return KeyOf(v.objectKind, object, &key) ? CellAt(v, key) : v.start;
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

	int KeyFirst(__int64 key)
	{
		return (int)(key >> 32);
	}

	int KeySecond(__int64 key)
	{
		return (int)key;
	}

	const char* OrEmpty(const char* text)
	{
		return text ? text : "";
	}

	bool KnownKind(int objectKind)
	{
		switch (static_cast<CivObjectKind>(objectKind))
		{
		case CIV_ON_PLAYER:
		case CIV_ON_CITY:
		case CIV_ON_UNIT:
		case CIV_ON_PLOT:
			return true;
		}
		return false;
	}

	bool KnownType(int valueType)
	{
		switch (static_cast<CivValueType>(valueType))
		{
		case CIV_VALUE_INT:
		case CIV_VALUE_INT64:
		case CIV_VALUE_DOUBLE:
		case CIV_VALUE_TEXT:
			return true;
		}
		return false;
	}

	// Whether the first number of the object's key is the player who owns it.
	bool OwnedByPlayer(int objectKind)
	{
		switch (static_cast<CivObjectKind>(objectKind))
		{
		case CIV_ON_PLAYER:
		case CIV_ON_CITY:
		case CIV_ON_UNIT:
			return true;
		case CIV_ON_PLOT:
			return false;
		}
		return false;
	}

	// The published value of that name, whatever its kind and type, or -1.
	int FindPublished(const char* modId, const char* pluginId, const char* name)
	{
		for (size_t i = 0; i < s_values.size(); ++i)
		{
			const Value& v = s_values[i];
			if ((v.flags & CIV_VALUE_PUBLISHED) && v.name == OrEmpty(name) && CivSameSaveKey(v.modId, v.pluginId, OrEmpty(modId), OrEmpty(pluginId)))
				return (int)i;
		}
		return -1;
	}

	Value* Declared(const Value& saved)
	{
		for (size_t i = 0; i < s_values.size(); ++i)
		{
			Value& v = s_values[i];
			if (v.name == saved.name && v.objectKind == saved.objectKind && v.valueType == saved.valueType
				&& CivSameSaveKey(v.modId, v.pluginId, saved.modId, saved.pluginId))
				return &v;
		}
		return 0;
	}

	void DropPlayerIn(std::vector<Value>& values, int player)
	{
		for (size_t i = 0; i < values.size(); ++i)
		{
			Value& v = values[i];
			if (!OwnedByPlayer(v.objectKind))
				continue;
			for (Cells::iterator cell = v.cells.begin(); cell != v.cells.end();)
			{
				if (KeyFirst(cell->first) == player)
					v.cells.erase(cell++);
				else
					++cell;
			}
		}
	}

	void CarryIn(std::vector<Value>& values, int objectKind, __int64 oldKey, __int64 newKey)
	{
		for (size_t i = 0; i < values.size(); ++i)
		{
			Value& v = values[i];
			if (v.objectKind != objectKind || !(v.flags & CIV_VALUE_CARRIES_OVER))
				continue;
			Cells::const_iterator found = v.cells.find(oldKey);
			if (found != v.cells.end())
				v.cells[newKey] = found->second;
			else
				v.cells.erase(newKey);
		}
	}

	typedef std::set<std::pair<int, __int64> > Objects;

	void ObjectsIn(const std::vector<Value>& values, Objects* objects)
	{
		for (size_t i = 0; i < values.size(); ++i)
			for (Cells::const_iterator cell = values[i].cells.begin(); cell != values[i].cells.end(); ++cell)
				objects->insert(std::make_pair(values[i].objectKind, cell->first));
	}

	void EraseIn(std::vector<Value>& values, const Objects& gone)
	{
		for (size_t i = 0; i < values.size(); ++i)
		{
			Value& v = values[i];
			for (Cells::iterator cell = v.cells.begin(); cell != v.cells.end();)
			{
				if (gone.count(std::make_pair(v.objectKind, cell->first)))
					v.cells.erase(cell++);
				else
					++cell;
			}
		}
	}

	// A unit's or city's values stay after it is gone until a save drops them here: harmless, since its number is not
	// used again while its owner's slot lives.
	void DropGoneObjects()
	{
		if (!s_objectAlive)
			return;
		Objects objects;
		{
			CivLockHold hold(s_lock);
			ObjectsIn(s_values, &objects);
			ObjectsIn(s_kept, &objects);
		}
		Objects gone;
		for (Objects::const_iterator object = objects.begin(); object != objects.end(); ++object)
			if (!s_objectAlive(object->first, KeyFirst(object->second), KeySecond(object->second)))
				gone.insert(*object);
		if (gone.empty())
			return;
		CivLockHold hold(s_lock);
		EraseIn(s_values, gone);
		EraseIn(s_kept, gone);
	}

	// Changing this layout needs kFormat raised in CivHostSaves.cpp, and LoadValue must still read the older layouts.
	void SaveValue(std::string* part, const Value& v)
	{
		CivPutText(part, v.modId);
		CivPutText(part, v.pluginId);
		CivPutText(part, v.name);
		CivPutNumber(part, (unsigned int)v.objectKind);
		CivPutNumber(part, (unsigned int)v.valueType);
		CivPutNumber(part, (unsigned int)v.flags);
		CivPutNumber(part, (unsigned int)v.cells.size());
		for (Cells::const_iterator cell = v.cells.begin(); cell != v.cells.end(); ++cell)
		{
			CivPutNumber(part, cell->first);
			switch (static_cast<CivValueType>(v.valueType))
			{
			case CIV_VALUE_INT:
			case CIV_VALUE_INT64:
				CivPutNumber(part, cell->second.whole);
				break;
			case CIV_VALUE_DOUBLE:
				CivPutNumber(part, cell->second.decimal);
				break;
			case CIV_VALUE_TEXT:
				CivPutText(part, cell->second.text);
				break;
			}
		}
	}

	bool LoadCell(CivPartReader* reader, int valueType, Cell* cell)
	{
		switch (static_cast<CivValueType>(valueType))
		{
		case CIV_VALUE_INT:
		case CIV_VALUE_INT64:
			return reader->Number(&cell->whole);
		case CIV_VALUE_DOUBLE:
			return reader->Number(&cell->decimal);
		case CIV_VALUE_TEXT:
			return reader->Text(&cell->text);
		}
		return false;
	}

	bool LoadValue(CivPartReader* reader, Value* v)
	{
		unsigned int objectKind = 0;
		unsigned int valueType = 0;
		unsigned int flags = 0;
		unsigned int count = 0;
		if (!reader->Text(&v->modId) || !reader->Text(&v->pluginId) || !reader->Text(&v->name) || !reader->Number(&objectKind)
			|| !reader->Number(&valueType) || !reader->Number(&flags) || !reader->Number(&count) || !KnownKind((int)objectKind)
			|| !KnownType((int)valueType))
			return false;
		v->objectKind = (int)objectKind;
		v->valueType = (int)valueType;
		v->flags = (int)flags;
		for (unsigned int i = 0; i < count; ++i)
		{
			__int64 key = 0;
			Cell cell;
			if (!reader->Number(&key) || !LoadCell(reader, v->valueType, &cell))
				return false;
			v->cells[key] = cell;
		}
		return true;
	}

	unsigned int CountWithCells(const std::vector<Value>& values)
	{
		unsigned int count = 0;
		for (size_t i = 0; i < values.size(); ++i)
			if (!values[i].cells.empty())
				++count;
		return count;
	}

	void SaveAllWithCells(std::string* part, const std::vector<Value>& values)
	{
		for (size_t i = 0; i < values.size(); ++i)
			if (!values[i].cells.empty())
				SaveValue(part, values[i]);
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

void CivHostSetObjectAliveSink(CivHostObjectAliveSink sink)
{
	s_objectAlive = sink;
}

int CivValuesDeclare(int plugin, int objectKind, int valueType, const char* name, int flags, const void* start, std::string* problem)
{
	Value v;
	v.plugin = plugin;
	v.objectKind = objectKind;
	v.valueType = valueType;
	v.flags = flags;
	v.name = OrEmpty(name);
	if (v.name.empty())
		*problem = "it has no name";
	else if (!KnownKind(objectKind))
		*problem = "it is not on players, cities, units or plots";
	else if (!KnownType(valueType))
		*problem = "its type is not one Bazaar knows";
	else if (flags & ~(CIV_VALUE_PUBLISHED | CIV_VALUE_CARRIES_OVER))
		*problem = "it asks for something Bazaar does not know";
	for (size_t i = 0; i < s_pending.size() && problem->empty(); ++i)
		if (s_pending[i].name == v.name)
			*problem = "the plugin already has a value of that name";
	if (!problem->empty())
		return -1;
	if (start)
	{
		switch (static_cast<CivValueType>(valueType))
		{
		case CIV_VALUE_INT:
			v.start.whole = *static_cast<const int*>(start);
			break;
		case CIV_VALUE_INT64:
			v.start.whole = *static_cast<const __int64*>(start);
			break;
		case CIV_VALUE_DOUBLE:
			v.start.decimal = *static_cast<const double*>(start);
			break;
		case CIV_VALUE_TEXT:
			v.start.text = static_cast<const char*>(start);
			break;
		}
	}
	s_pending.push_back(v);
	return (int)(s_values.size() + s_pending.size() - 1);
}

void CivValuesCommitPending(const std::string& modId, const std::string& pluginId)
{
	for (size_t i = 0; i < s_pending.size(); ++i)
	{
		s_pending[i].modId = modId;
		s_pending[i].pluginId = pluginId;
	}
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
	s_kept.clear();
}

void CivValuesClearGame()
{
	CivLockHold hold(s_lock);
	for (size_t i = 0; i < s_values.size(); ++i)
		s_values[i].cells.clear();
	s_kept.clear();
}

void CivValuesDropPlayer(int player)
{
	CivLockHold hold(s_lock);
	DropPlayerIn(s_values, player);
	DropPlayerIn(s_kept, player);
}

void CivValuesReplaced(int objectKind, __int64 oldKey, const void* newObject)
{
	__int64 newKey = 0;
	if (!KeyOf(objectKind, newObject, &newKey))
		return;
	CivLockHold hold(s_lock);
	CarryIn(s_values, objectKind, oldKey, newKey);
	CarryIn(s_kept, objectKind, oldKey, newKey);
}

void CivValuesSave(std::string* part)
{
	DropGoneObjects();
	CivLockHold hold(s_lock);
	CivPutNumber(part, CountWithCells(s_values) + CountWithCells(s_kept));
	SaveAllWithCells(part, s_values);
	SaveAllWithCells(part, s_kept);
}

bool CivValuesLoad(CivPartReader* reader)
{
	unsigned int count = 0;
	if (!reader->Number(&count))
		return false;
	CivLockHold hold(s_lock);
	for (unsigned int i = 0; i < count; ++i)
	{
		Value saved;
		if (!LoadValue(reader, &saved))
			return false;
		if (Value* declared = Declared(saved))
			declared->cells.swap(saved.cells);
		else
			s_kept.push_back(saved);
	}
	return true;
}

int CivFindValue(int, const char* modId, const char* pluginId, const char* name, int objectKind, int valueType)
{
	const int found = FindPublished(modId, pluginId, name);
	return found >= 0 && s_values[found].objectKind == objectKind && s_values[found].valueType == valueType ? found : -1;
}

bool CivValuesGetPublished(const char* modId, const char* pluginId, const char* name, int first, int second, CivPublishedValue* out)
{
	const int found = FindPublished(modId, pluginId, name);
	if (found < 0)
		return false;
	const Value& v = s_values[found];
	if (s_objectAlive && !s_objectAlive(v.objectKind, first, second))
		return false;
	const Cell cell = CellAt(v, CivObjectKey(first, second));
	out->valueType = v.valueType;
	out->whole = cell.whole;
	out->decimal = cell.decimal;
	out->text = cell.text;
	return true;
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
	cell.text = OrEmpty(text);
	return Write(Usable(plugin, value, CIV_VALUE_TEXT, true), object, cell);
}
