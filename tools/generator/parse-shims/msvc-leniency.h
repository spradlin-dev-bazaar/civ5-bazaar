// Parse-only definitions for names MSVC never checks in unused template default arguments.
// FFastVector's default memory pool is FMemHooks.h's, which the engine includes only later. A stand-in for it would
// make clang number the pools one lower than MSVC does, so the real one is read first, after the headers it needs,
// whenever the game's headers are on the include path.
#if __has_include("CvGameCoreDLLUtil_Win32Headers.h")
#include "CvGameCoreDLLUtil_Win32Headers.h"
#include <FireWorks/FDefNew.h>
#include <FireWorks/FFireTypes.h>
#include <FireWorks/FMemHooks.h>
#endif
static const bool bPODType = false;
