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
