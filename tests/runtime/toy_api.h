#pragma once

// The types of the functions toy plugins export for the tests. toy_plugins.cpp declares each export with its type, so a
// toy whose export no longer matches the type the tests look it up as fails to compile.
#include <string>
#include <vector>

typedef void ToyActionFn();
typedef bool ToyHostCallFn();

typedef int ToyBeforeCallsFn();
typedef int ToyRegisterLateFn();
typedef int ToyRegisterHandLateFn();
typedef void ToyFaultOnShutdownFn();
typedef void ToySetShutdownProbeFn(ToyActionFn* probe);
typedef void ToyFillStringsFn(std::string& s, std::vector<std::string>& v);
typedef void ToyReleaseStringsFn(std::string& s, std::vector<std::string>& v);
typedef void ToySetHostCallFn(ToyHostCallFn* call);
typedef int ToyHostCallResultFn();
typedef void ToyBreakOnNextCallFn();
typedef void ToyStartThreadFn(int throughRuntime);
typedef void ToyLeaveThreadRunningFn();
typedef int ToyExplodeLineFn();
typedef void ToySaveSetFn(int value);
typedef int ToySaveValueFn();
typedef int ToySaveLoadsFn();
typedef bool ToySaveHadDataFn();
// 1 crashes the next save, 2 the next load.
typedef void ToySaveCrashNextFn(int where);
// The results of the registrations its entry function tried, in order; 4 tries one more now.
typedef int ToySaveRegisteredFn(int attempt);
// The next save also writes with the saving it was given in the save before.
typedef void ToySaveWriteKeptFn();
// The results of the values its entry function declared, in toy_plugins.cpp's order; the last tries one more now.
typedef int ToyValuesDeclaredFn(int attempt);
typedef bool ToyValuesSetKillsFn(const void* unit, int kills);
typedef int ToyValuesKillsFn(const void* unit);
typedef void ToyValuesSetVeteranFn(const void* unit, bool veteran);
typedef bool ToyValuesVeteranFn(const void* unit);
typedef void ToyValuesSetMoraleFn(const void* city, double morale);
typedef double ToyValuesMoraleFn(const void* city);
typedef void ToyValuesSetMottoFn(const void* player, const char* motto);
typedef std::string ToyValuesMottoFn(const void* player);
typedef void ToyValuesSetBigFn(const void* plot, __int64 big);
typedef __int64 ToyValuesBigFn(const void* plot);
typedef void ToyValuesSetSpeedFn(const void* unit, float speed);
typedef float ToyValuesSpeedFn(const void* unit);
typedef void ToyValuesSetShortFn(const void* unit, unsigned short n);
typedef unsigned short ToyValuesShortFn(const void* unit);
// Kills on the new unit, as Toy Values read it inside its UnitReplaced hook; -1 before the hook ran.
typedef int ToyValuesKillsWhenReplacedFn();
typedef void ToyValuesSetWideFn(const void* unit, unsigned int n);
typedef unsigned int ToyValuesWideFn(const void* unit);
// What the reader found of Toy Values' values, in toy_plugins.cpp's order.
typedef int ToyReaderFoundFn(int attempt);
typedef int ToyReaderKillsFn(const void* unit);
typedef bool ToyReaderSetKillsFn(const void* unit, int kills);
typedef std::string ToyReaderMottoFn(const void* player);
typedef int ToyReaderReadIntFn(int value, const void* unit);
// The results of the functions its entry function tried to publish, in toy_plugins.cpp's order.
typedef int ToyValuesPublishedFn(int attempt);
typedef int ToyValuesPublishLateFn();
// What the reader found of Toy Values' functions, in toy_plugins.cpp's order.
typedef int ToyReaderFunctionFoundFn(int attempt);
// Whether a function that takes and returns an int is published under that mod's ID, plugin ID and name.
typedef bool ToyReaderFindsFn(const char* modId, const char* pluginId, const char* name);
typedef int ToyReaderDoubledFn(int n, bool* called);
// Calls Toy Values' function with that many parameters, 0, 2, 3 or 4, handing it 1, 2, 3 and 4 in order.
typedef int ToyReaderDigitsFn(int count);
typedef void ToyReaderGreetFn(const char* who);
typedef int ToyReaderCrashFn(bool* called);
typedef int ToyReaderCallUnfoundFn(bool* called);
typedef bool ToyReaderFindDoubledNowFn();
typedef int ToyKeptCallerDoubledFn(bool* called);
