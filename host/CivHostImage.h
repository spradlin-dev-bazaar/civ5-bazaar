#pragma once

#include "CivPluginApi.h"

#include <windows.h>

#include <string>

enum CivExportRead
{
	CIV_EXPORT_FOUND,
	CIV_EXPORT_MISSING,
	CIV_EXPORT_64_BIT,
	CIV_EXPORT_NOT_OPENED,
};

// builtRelease is read only when the version is found. openError is Windows' error when the file could not be opened.
CivExportRead CivImageReadApi(const std::string& path, CivApiVersion* built, int* builtRelease, DWORD* openError);
bool CivImageThreadInside(HMODULE module);
