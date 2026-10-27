#include "harness.h"
#include "CivHostHand.h"
#include "CivHostSaves.h"
#include "CivHostValues.h"

#include <set>

namespace
{
	const char* const kValues = "toy_values.dll";
	const char* const kReader = "toy_values_reader.dll";
	const char* const kDecline = "toy_decline.dll";
	const char* const kSave = "toy_save.dll";
	const char* const kValuesMod = "{VALUES}";
	const char* const kReaderMod = "{READER}";

	struct Thing
	{
		int first;
		int second;
	};

	bool ThingKey(int, const void* object, __int64* key)
	{
		const Thing* thing = static_cast<const Thing*>(object);
		*key = CivObjectKey(thing->first, thing->second);
		return true;
	}

	typedef std::set<std::pair<int, std::pair<int, int> > > Gone;
	Gone s_gone;

	bool ThingAlive(int objectKind, int first, int second)
	{
		return !s_gone.count(std::make_pair(objectKind, std::make_pair(first, second)));
	}

	// Toy Values' values are numbered in the order its entry function declares them.
	const int kKills = 0;
	const int kVeteran = 1;
	const int kMorale = 2;

	void Start(const std::vector<CivPluginFile>& files)
	{
		StartWithNone();
		CivHostSetObjectKeySink(&ThingKey);
		CivHostLoadPlugins(files);
	}

	// False, with the failure checked, when a toy did not load: its functions cannot be called then.
	bool StartWithValues(bool withReader)
	{
		std::vector<CivPluginFile> files;
		files.push_back(CivPluginFile(OutFile(kValues), kValuesMod));
		if (withReader)
			files.push_back(CivPluginFile(OutFile(kReader), kReaderMod));
		Start(files);
		const bool loaded = HasStatus(kValues, CIV_PLUGIN_LOADED) && (!withReader || HasStatus(kReader, CIV_PLUGIN_LOADED));
		Check(loaded, "the plugins that declare and read values load");
		return loaded;
	}

	void Finish()
	{
		CivHostLoadPart(0);
		CivHostSetObjectKeySink(0);
		CivHostSetObjectAliveSink(0);
		s_gone.clear();
	}

	bool StartOnly(const char* name, const char* modId)
	{
		std::vector<CivPluginFile> files;
		files.push_back(CivPluginFile(OutFile(name), modId));
		Start(files);
		const bool loaded = HasStatus(name, CIV_PLUGIN_LOADED);
		Check(loaded, "the plugin loads on its own");
		return loaded;
	}

	void MarkGone(int objectKind, int first, int second)
	{
		CivHostSetObjectAliveSink(&ThingAlive);
		s_gone.insert(std::make_pair(objectKind, std::make_pair(first, second)));
	}

	// Written by hand rather than by Bazaar, so the tests check the format itself.
	void PutSavedValue(std::string* part, const char* modId, const char* pluginId, const char* name, int objectKind, int valueType,
		__int64 key, int n)
	{
		CivPutText(part, modId);
		CivPutText(part, pluginId);
		CivPutText(part, name);
		CivPutNumber(part, (unsigned int)objectKind);
		CivPutNumber(part, (unsigned int)valueType);
		CivPutNumber(part, (unsigned int)CIV_VALUE_PUBLISHED);
		CivPutNumber(part, 1u);
		CivPutNumber(part, key);
		if (valueType == CIV_VALUE_DOUBLE)
			CivPutNumber(part, (double)n);
		else
			CivPutNumber(part, (__int64)n);
	}

	std::string ValuesOnlyPart(unsigned int valueCount)
	{
		std::string part;
		CivPutNumber(&part, 2u);
		CivPutNumber(&part, 0u);
		CivPutNumber(&part, valueCount);
		return part;
	}

	int Occurrences(const std::string& text, const char* part)
	{
		int count = 0;
		for (size_t at = text.find(part); at != std::string::npos; at = text.find(part, at + 1))
			++count;
		return count;
	}
}

void TestValueDeclarations()
{
	if (!StartWithValues(false))
		return Finish();
	ToyValuesDeclaredFn* declared = TOY_FUNCTION(kValues, ToyValuesDeclared);
	Check(declared(0) == 0 && LogHas("Plugin Toy Values: its value Kills was refused because the plugin already has a value of that name."),
		"a second value of the same name is refused, and the log says why");
	Check(declared(1) == 0 && LogHas("its value  was refused because it has no name."), "a value needs a name");
	Check(declared(2) == -1 && declared(3) == -1 && declared(4) == -1,
		"a value must be on players, cities, units or plots, of a type Bazaar knows, asking for nothing Bazaar does not know");
	Check(declared(5) == 0 && LogHas("its value Late was refused because it was declared outside the plugin's entry function"),
		"values are declared only from the entry function");
	Finish();
}

void TestValueReadsAndWrites()
{
	if (!StartWithValues(false))
		return Finish();
	Thing unit = {1, 8193};
	Thing other = {1, 16385};
	Thing sameNumber = {2, 8193};
	Thing city = {2, 8193};
	Thing player = {3, 0};
	Thing plot = {10, 20};
	ToyValuesKillsFn* kills = TOY_FUNCTION(kValues, ToyValuesKills);
	ToyValuesMoraleFn* morale = TOY_FUNCTION(kValues, ToyValuesMorale);
	ToyValuesMottoFn* motto = TOY_FUNCTION(kValues, ToyValuesMotto);
	ToyValuesShortFn* shortValue = TOY_FUNCTION(kValues, ToyValuesShort);
	ToyValuesSpeedFn* speed = TOY_FUNCTION(kValues, ToyValuesSpeed);
	ToyValuesBigFn* big = TOY_FUNCTION(kValues, ToyValuesBig);
	ToyValuesSetKillsFn* setKills = TOY_FUNCTION(kValues, ToyValuesSetKills);
	Check(kills(&unit) == 0 && morale(&city) == 100.0 && motto(&player) == "none yet" && shortValue(&unit) == 7 && speed(&unit) == 1.5f
		&& big(&plot) == 5000000000LL,
		"a value never set reads as its starting value");
	Check(setKills(&unit, 3) && kills(&unit) == 3 && kills(&other) == 0 && kills(&sameNumber) == 0,
		"a value set on one object reads back there, and not on another, even one of another player with the same number");
	Check(!setKills(0, 5) && kills(0) == 0 && morale(0) == 100.0, "a null object cannot be set, and reads as the starting value");

	TOY_FUNCTION(kValues, ToyValuesSetVeteran)(&unit, true);
	TOY_FUNCTION(kValues, ToyValuesSetMorale)(&city, 87.25);
	TOY_FUNCTION(kValues, ToyValuesSetBig)(&plot, 9000000000000000000LL);
	TOY_FUNCTION(kValues, ToyValuesSetSpeed)(&unit, 0.1f);
	TOY_FUNCTION(kValues, ToyValuesSetShort)(&unit, 65535);
	TOY_FUNCTION(kValues, ToyValuesSetWide)(&unit, 4000000000u);
	Check(TOY_FUNCTION(kValues, ToyValuesVeteran)(&unit) && morale(&city) == 87.25 && big(&plot) == 9000000000000000000LL
		&& speed(&unit) == 0.1f && shortValue(&unit) == 65535 && TOY_FUNCTION(kValues, ToyValuesWide)(&unit) == 4000000000u,
		"true or false, decimals, large whole numbers, floats, unsigned shorts and unsigned ints read back exactly as they were set");
	ToyValuesSetMottoFn* setMotto = TOY_FUNCTION(kValues, ToyValuesSetMotto);
	const std::string fits(255, 'x');
	setMotto(&player, fits.c_str());
	const bool fitsReadBack = motto(&player) == fits;
	const std::string longer(256, 'y');
	setMotto(&player, longer.c_str());
	Check(fitsReadBack && motto(&player) == longer, "a text that fills the helper's first buffer, and one a letter longer, read back whole");

	CivHostLoadPart(0);
	Check(kills(&unit) == 0 && morale(&city) == 100.0, "a new game, or a save loading, starts every value again");
	Finish();
}

void TestPublishedValues()
{
	std::vector<CivPluginFile> files;
	files.push_back(CivPluginFile(OutFile(kValues), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kReader), kReaderMod));
	files.push_back(CivPluginFile(OutFile(kSave), "{SAVE}"));
	Start(files);
	if (!HasStatus(kValues, CIV_PLUGIN_LOADED) || !HasStatus(kReader, CIV_PLUGIN_LOADED) || !HasStatus(kSave, CIV_PLUGIN_LOADED))
	{
		Check(false, "the plugins that declare and read values load");
		return Finish();
	}
	Thing unit = {1, 8193};
	Thing player = {3, 0};
	ToyReaderFoundFn* found = TOY_FUNCTION(kReader, ToyReaderFound);
	Check(found(0) == 1 && found(1) == 1, "another plugin finds a published value by its mod's ID, plugin ID and name");
	Check(found(2) == 0, "a value that was not published cannot be found");
	Check(found(3) == 0 && found(4) == 0, "a value cannot be found as another type than it has, or on another kind of object");
	Check(found(5) == 1, "a value can be found through any type kept the same way, such as long for int");
	Check(found(6) == 0 && found(7) == 0, "a value cannot be found under another plugin ID or another mod's ID");

	ToyReaderKillsFn* readKills = TOY_FUNCTION(kReader, ToyReaderKills);
	ToyReaderSetKillsFn* setKills = TOY_FUNCTION(kReader, ToyReaderSetKills);
	ToyReaderReadIntFn* readInt = TOY_FUNCTION(kReader, ToyReaderReadInt);
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&unit, 5);
	TOY_FUNCTION(kValues, ToyValuesSetMotto)(&player, "Onward");
	Check(readKills(&unit) == 5 && TOY_FUNCTION(kReader, ToyReaderMotto)(&player) == "Onward",
		"another plugin reads a published value as its plugin set it");
	const char* const notOwner = "Plugin Toy Reader used the value Kills of Toy Values to change it, although only that plugin can, so it "
		"was left as it was. This is logged only once.";
	Check(!setKills(&unit, 99) && !setKills(&unit, 98) && readKills(&unit) == 5 && LogCount(notOwner) == 1,
		"another plugin cannot change a published value, and the log says so once");
	const int saveIndex = (int)(Find(kSave) - &CivHostPlugins()[0]);
	CivSetIntValue(saveIndex, kKills, &unit, 97);
	Check(readKills(&unit) == 5 && LogCount("used the value Kills of Toy Values to change it") == 2,
		"each plugin that misuses a value is logged once");
	Check(readInt(kVeteran, &unit) == 0
		&& LogHas("Plugin Toy Reader used the value Veteran of Toy Values although that plugin keeps it to itself, so it read as zero or empty."),
		"another plugin cannot read a value that was not published, even by its number");
	Check(readInt(kMorale, 0) == 0 && LogHas("Plugin Toy Reader used the value Morale of Toy Values as another type than it has"),
		"a value read as another type than it has reads as zero, and the log says so");
	Check(readInt(-1, &unit) == 0 && readInt(999, &unit) == 0, "a value number Bazaar never gave out reads as zero");
	Finish();
}

void TestCarriedValues()
{
	if (!StartWithValues(false))
		return Finish();
	Thing oldUnit = {1, 8193};
	Thing newUnit = {2, 16385};
	Thing thirdUnit = {3, 24577};
	Thing oldCity = {1, 8193};
	Thing newCity = {2, 8193};
	ToyValuesKillsFn* kills = TOY_FUNCTION(kValues, ToyValuesKills);
	ToyValuesSetKillsFn* setKills = TOY_FUNCTION(kValues, ToyValuesSetKills);
	setKills(&oldUnit, 4);
	TOY_FUNCTION(kValues, ToyValuesSetVeteran)(&oldUnit, true);
	TOY_FUNCTION(kValues, ToyValuesSetMorale)(&oldCity, 42.0);
	CivHandUnitReplaced(oldUnit.first, oldUnit.second, reinterpret_cast<CvUnit*>(&newUnit));
	CivHandCityReplaced(oldCity.first, oldCity.second, reinterpret_cast<CvCity*>(&newCity));
	Check(kills(&newUnit) == 4 && TOY_FUNCTION(kValues, ToyValuesMorale)(&newCity) == 42.0,
		"values that carry over are copied to the unit or city the game made in place of the old one");
	Check(TOY_FUNCTION(kValues, ToyValuesKillsWhenReplaced)() == 4, "a plugin's UnitReplaced hook already reads the copied values");
	Check(!TOY_FUNCTION(kValues, ToyValuesVeteran)(&newUnit), "values that do not carry over stay behind");

	CivHandUnitReplaced(newUnit.first, newUnit.second, reinterpret_cast<CvUnit*>(&thirdUnit));
	Check(kills(&thirdUnit) == 4, "a value carries over again when the new unit is replaced in turn");
	Thing unset = {4, 8193};
	CivHandUnitReplaced(unset.first, unset.second, reinterpret_cast<CvUnit*>(&thirdUnit));
	Check(kills(&thirdUnit) == 0, "a unit replacing one that never had the value reads as the starting value");
	Finish();
}

void TestValuesOfResetPlayers()
{
	if (!StartWithValues(false))
		return Finish();
	Thing unit = {2, 8193};
	Thing otherPlayersUnit = {3, 8193};
	Thing player = {2, 0};
	Thing plot = {2, 5};
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&unit, 6);
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&otherPlayersUnit, 7);
	TOY_FUNCTION(kValues, ToyValuesSetMotto)(&player, "Gone");
	TOY_FUNCTION(kValues, ToyValuesSetBig)(&plot, 8);
	CivValuesDropPlayer(2);
	Check(TOY_FUNCTION(kValues, ToyValuesKills)(&unit) == 0 && TOY_FUNCTION(kValues, ToyValuesMotto)(&player) == "none yet",
		"when the game sets up a player's slot again, the values of that player and its units start again");
	Check(TOY_FUNCTION(kValues, ToyValuesKills)(&otherPlayersUnit) == 7 && TOY_FUNCTION(kValues, ToyValuesBig)(&plot) == 8,
		"the values of other players' units, and of plots, stay");
	Finish();
}

void TestValuesOfRefusedPlugins()
{
	std::vector<CivPluginFile> files;
	files.push_back(CivPluginFile(OutFile(kDecline), "{DECLINE}"));
	files.push_back(CivPluginFile(OutFile(kValues), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kReader), kReaderMod));
	Start(files);
	if (!HasStatus(kValues, CIV_PLUGIN_LOADED) || !HasStatus(kReader, CIV_PLUGIN_LOADED))
	{
		Check(false, "the plugins that declare and read values load after one that declines");
		return Finish();
	}
	Thing unit = {1, 8193};
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&unit, 5);
	Check(TOY_FUNCTION(kReader, ToyReaderKills)(&unit) == 5 && TOY_FUNCTION(kReader, ToyReaderReadInt)(kVeteran, &unit) == 0
		&& LogHas("used the value Veteran of Toy Values"),
		"the values of a plugin that declines are dropped, and the next plugin's values keep their numbers");

	files.clear();
	files.push_back(CivPluginFile(OutFile(kValues), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kSave), kValuesMod));
	Start(files);
	Check(HasStatus(kValues, CIV_PLUGIN_LOADED) && HasStatus(kSave, CIV_PLUGIN_SAVE_ID_TAKEN),
		"a plugin that keeps data is refused when one higher in the list, with values, comes from the same mod with the same "
		"plugin ID");

	files.clear();
	files.push_back(CivPluginFile(OutFile(kSave), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kValues), kValuesMod));
	Start(files);
	Check(HasStatus(kSave, CIV_PLUGIN_LOADED) && HasStatus(kValues, CIV_PLUGIN_SAVE_ID_TAKEN),
		"a plugin with values is refused when one higher in the list that keeps data comes from the same mod with the same "
		"plugin ID");

	files.clear();
	files.push_back(CivPluginFile(OutFile(kReader), kValuesMod));
	files.push_back(CivPluginFile(OutFile(kValues), kValuesMod));
	Start(files);
	Check(HasStatus(kReader, CIV_PLUGIN_LOADED) && HasStatus(kValues, CIV_PLUGIN_LOADED),
		"a plugin with values loads below one from the same mod that keeps no data");
	Finish();
}

void TestCapturedFrom()
{
	int owner = -1;
	int unit = -1;
	Check(!CivHostTakeCapturedFrom(&owner, &unit), "no unit is being captured at first");
	CivHostCaptureFrom(1, 8193);
	CivHostCaptureFrom(2, 16385);
	const bool inner = CivHostTakeCapturedFrom(&owner, &unit) && owner == 2 && unit == 16385;
	Check(inner && !CivHostTakeCapturedFrom(&owner, &unit), "a capture inside another gives its own unit, once");
	CivHostCaptureDone();
	Check(CivHostTakeCapturedFrom(&owner, &unit) && owner == 1 && unit == 8193, "the outer capture still gives its unit after the inner one");
	CivHostCaptureDone();
	Check(!CivHostTakeCapturedFrom(&owner, &unit), "once every capture is done, none is left");
}

void TestSavedValues()
{
	if (!StartWithValues(false))
		return Finish();
	Thing unit = {1, 8193};
	Thing city = {2, 8193};
	Thing player = {3, 0};
	Thing plot = {10, 20};
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&unit, 3);
	TOY_FUNCTION(kValues, ToyValuesSetVeteran)(&unit, true);
	TOY_FUNCTION(kValues, ToyValuesSetMorale)(&city, 87.25);
	TOY_FUNCTION(kValues, ToyValuesSetMotto)(&player, "Onward");
	TOY_FUNCTION(kValues, ToyValuesSetBig)(&plot, 9000000000000000000LL);
	TOY_FUNCTION(kValues, ToyValuesSetSpeed)(&unit, 0.1f);
	const std::string part = CivHostSavePart();
	CivHostLoadPart(0);
	const bool cleared = TOY_FUNCTION(kValues, ToyValuesKills)(&unit) == 0;
	Check(cleared && CivHostLoadPart(&part).empty() && TOY_FUNCTION(kValues, ToyValuesKills)(&unit) == 3
		&& TOY_FUNCTION(kValues, ToyValuesVeteran)(&unit) && TOY_FUNCTION(kValues, ToyValuesMorale)(&city) == 87.25
		&& TOY_FUNCTION(kValues, ToyValuesMotto)(&player) == "Onward" && TOY_FUNCTION(kValues, ToyValuesBig)(&plot) == 9000000000000000000LL
		&& TOY_FUNCTION(kValues, ToyValuesSpeed)(&unit) == 0.1f,
		"values of every type and kind of object come back exactly when the save loads");
	Finish();
}

void TestValuesOfPluginsThatAreOff()
{
	if (!StartOnly(kValues, kValuesMod))
		return Finish();
	Thing unit = {1, 8193};
	Thing newUnit = {2, 16385};
	Thing gone = {1, 24577};
	Thing reset = {3, 8193};
	ToyValuesSetKillsFn* setKills = TOY_FUNCTION(kValues, ToyValuesSetKills);
	setKills(&unit, 5);
	setKills(&gone, 6);
	setKills(&reset, 7);
	const std::string withValues = CivHostSavePart();

	if (!StartOnly(kReader, kReaderMod))
		return Finish();
	CivHostLoadPart(&withValues);
	CivHandUnitReplaced(unit.first, unit.second, reinterpret_cast<CvUnit*>(&newUnit));
	CivValuesDropPlayer(reset.first);
	MarkGone(CIV_ON_UNIT, gone.first, gone.second);
	const std::string whileOff = CivHostSavePart();
	CivHostLoadPart(0);
	const std::string afterNewGame = CivHostSavePart();

	if (!StartOnly(kValues, kValuesMod))
		return Finish();
	ToyValuesKillsFn* kills = TOY_FUNCTION(kValues, ToyValuesKills);
	CivHostLoadPart(&whileOff);
	Check(kills(&unit) == 5, "the values of a plugin that is off go into the next save");
	Check(kills(&newUnit) == 5, "they carry over to a new unit while their plugin is off, as they would with it on");
	Check(kills(&reset) == 0 && kills(&gone) == 0, "they are dropped for a player whose slot is set up again, and for a unit that is gone");
	CivHostLoadPart(&afterNewGame);
	Check(kills(&unit) == 0, "a new game drops the kept values of plugins that are off too");
	Finish();
}

void TestMatchingOfSavedValues()
{
	if (!StartWithValues(false))
		return Finish();
	Thing unit = {1, 8193};
	const __int64 key = CivObjectKey(unit.first, unit.second);
	ToyValuesKillsFn* kills = TOY_FUNCTION(kValues, ToyValuesKills);
	std::string matching = ValuesOnlyPart(1);
	PutSavedValue(&matching, "{values}", "", "Kills", CIV_ON_UNIT, CIV_VALUE_INT, key, 9);
	Check(CivHostLoadPart(&matching).empty() && kills(&unit) == 9, "a saved value goes to the plugin with its mod ID, plugin ID, name, kind of object and type");

	std::string others = ValuesOnlyPart(5);
	PutSavedValue(&others, kValuesMod, "", "Kills", CIV_ON_UNIT, CIV_VALUE_DOUBLE, key, 1);
	PutSavedValue(&others, kValuesMod, "", "Kills", CIV_ON_CITY, CIV_VALUE_INT, key, 2);
	PutSavedValue(&others, kValuesMod, "OTHER", "Kills", CIV_ON_UNIT, CIV_VALUE_INT, key, 3);
	PutSavedValue(&others, "{OTHER}", "", "Kills", CIV_ON_UNIT, CIV_VALUE_INT, key, 4);
	PutSavedValue(&others, kValuesMod, "", "OldKills", CIV_ON_UNIT, CIV_VALUE_INT, key, 5);
	Check(CivHostLoadPart(&others).empty() && kills(&unit) == 0,
		"a saved value of another type, kind of object, plugin ID, mod or name goes to no plugin");
	const std::string saved = CivHostSavePart();
	Check(Occurrences(saved, "Kills") == 5 && Occurrences(saved, "OldKills") == 1, "saved values that go to no plugin are written into the next save");

	std::string unknownKind = ValuesOnlyPart(1);
	PutSavedValue(&unknownKind, kValuesMod, "", "Kills", 9, CIV_VALUE_INT, key, 5);
	Check(CivHostLoadPart(&unknownKind).find("some plugins") != std::string::npos, "a saved value on a kind of object Bazaar does not know is reported as damaged");
	Finish();
}

void TestValuesOfGoneObjects()
{
	if (!StartWithValues(false))
		return Finish();
	Thing unit = {1, 8193};
	Thing gone = {1, 16385};
	Thing plot = {1, 16385};
	ToyValuesKillsFn* kills = TOY_FUNCTION(kValues, ToyValuesKills);
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&unit, 1);
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&gone, 2);
	TOY_FUNCTION(kValues, ToyValuesSetBig)(&plot, 3);
	MarkGone(CIV_ON_UNIT, gone.first, gone.second);
	const std::string part = CivHostSavePart();
	Check(kills(&gone) == 0 && kills(&unit) == 1 && TOY_FUNCTION(kValues, ToyValuesBig)(&plot) == 3,
		"saving drops the values of a unit that is gone, and only of that object");
	CivHostLoadPart(&part);
	Check(kills(&gone) == 0 && kills(&unit) == 1, "the save holds no values of the unit that is gone");
	Finish();
}

void TestDamagedValues()
{
	if (!StartWithValues(false))
		return Finish();
	Thing unit = {1, 8193};
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&unit, 4);
	const std::string part = CivHostSavePart();
	const std::string cut = part.substr(0, part.size() - 2);
	Check(CivHostLoadPart(&cut).find("some plugins") != std::string::npos, "a part whose values are cut short is reported as damaged");

	// The format before values were saved, with no plugin data: its number and a count of 0.
	std::string older;
	CivPutNumber(&older, 1u);
	CivPutNumber(&older, 0u);
	Check(CivHostLoadPart(&older).empty() && TOY_FUNCTION(kValues, ToyValuesKills)(&unit) == 0,
		"a part from before values were saved loads, and every value starts again");
	Finish();
}

void TestPublishedValueReads()
{
	if (!StartWithValues(false))
		return Finish();
	Thing unit = {1, 8193};
	Thing player = {3, 0};
	TOY_FUNCTION(kValues, ToyValuesSetKills)(&unit, 6);
	TOY_FUNCTION(kValues, ToyValuesSetMotto)(&player, "Onward");
	CivPublishedValue kills;
	CivPublishedValue motto;
	CivPublishedValue unset;
	Check(CivValuesGetPublished(kValuesMod, "", "Kills", 1, 8193, &kills) && kills.valueType == CIV_VALUE_INT && kills.whole == 6
		&& CivValuesGetPublished("{values}", 0, "Motto", 3, 0, &motto) && motto.text == "Onward",
		"Lua reads a published value by its mod's ID, plugin ID, name and the object's two numbers");
	Check(CivValuesGetPublished(kValuesMod, "", "Motto", 4, 0, &unset) && unset.text == "none yet",
		"Lua reads the starting value of an object the value was never set on");
	CivPublishedValue none;
	Check(!CivValuesGetPublished(kValuesMod, "", "Veteran", 1, 8193, &none) && !CivValuesGetPublished(kValuesMod, "", "Nothing", 1, 8193, &none)
		&& !CivValuesGetPublished("{OTHER}", "", "Kills", 1, 8193, &none),
		"Lua cannot read a value that was not published, or one that does not exist");
	MarkGone(CIV_ON_UNIT, unit.first, unit.second);
	Check(!CivValuesGetPublished(kValuesMod, "", "Kills", 1, 8193, &none), "Lua reads no value on a unit or city that is gone");
	Finish();
}
