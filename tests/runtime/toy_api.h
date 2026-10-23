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
