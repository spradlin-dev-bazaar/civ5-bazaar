#include "CivHostFunctions.h"
#include "CivHostRuntime.h"

#include <vector>

namespace
{
	struct Function
	{
		int plugin;
		std::string modId;
		std::string pluginId;
		std::string name;
		std::string signature;
		void* fn;
	};

	// Published only while plugins load, which never happens during a game, so nothing here needs a lock.
	std::vector<Function> s_functions;
	std::vector<Function> s_pending;

	const char* OrEmpty(const char* text)
	{
		return text ? text : "";
	}
}

bool CivFunctionsPublish(int plugin, const char* name, const char* signature, void* fn, std::string* problem)
{
	Function f;
	f.plugin = plugin;
	f.name = OrEmpty(name);
	f.signature = OrEmpty(signature);
	f.fn = fn;
	if (f.name.empty())
		*problem = "it has no name";
	else if (!fn)
		*problem = "no function was given";
	for (size_t i = 0; i < s_pending.size() && problem->empty(); ++i)
		if (s_pending[i].name == f.name)
			*problem = "the plugin already publishes a function of that name";
	if (!problem->empty())
		return false;
	s_pending.push_back(f);
	return true;
}

void CivFunctionsCommitPending(const std::string& modId, const std::string& pluginId)
{
	for (size_t i = 0; i < s_pending.size(); ++i)
	{
		s_pending[i].modId = modId;
		s_pending[i].pluginId = pluginId;
	}
	s_functions.insert(s_functions.end(), s_pending.begin(), s_pending.end());
	s_pending.clear();
}

void CivFunctionsDiscardPending()
{
	s_pending.clear();
}

void CivFunctionsForgetAll()
{
	s_functions.clear();
	s_pending.clear();
}

bool CivFunctionsPending()
{
	return !s_pending.empty();
}

bool CivFunctionsPublishedBy(int plugin)
{
	for (size_t i = 0; i < s_functions.size(); ++i)
		if (s_functions[i].plugin == plugin)
			return true;
	return false;
}

int CivFunctionsFind(int, const char* modId, const char* pluginId, const char* name, const char* signature)
{
	for (size_t i = 0; i < s_functions.size(); ++i)
	{
		const Function& f = s_functions[i];
		if (f.name == OrEmpty(name) && f.signature == OrEmpty(signature)
			&& CivSameSaveKey(f.modId, f.pluginId, OrEmpty(modId), OrEmpty(pluginId)))
			return (int)i;
	}
	return -1;
}

bool CivFunctionsGet(int function, int* plugin, void** fn)
{
	if (function < 0 || function >= (int)s_functions.size())
		return false;
	*plugin = s_functions[function].plugin;
	*fn = s_functions[function].fn;
	return true;
}

const char* CivFunctionsName(int function)
{
	return function >= 0 && function < (int)s_functions.size() ? s_functions[function].name.c_str() : "";
}
