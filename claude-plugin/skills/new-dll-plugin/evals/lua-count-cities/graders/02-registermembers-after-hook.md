---
type: llm
focus: trace
weight: 1
---

The plugin registers an after-hook on CivHooks::CvLuaGame_RegisterMembers (with CivRegisterAfter, or with RegisterHook and CIV_HOOK_AFTER) whose function takes only a lua_State* and returns void.
