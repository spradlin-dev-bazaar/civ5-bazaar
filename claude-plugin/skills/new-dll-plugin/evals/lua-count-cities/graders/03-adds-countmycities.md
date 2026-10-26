---
type: llm
focus: trace
weight: 1
---

The after-hook pushes a C function with the host's PushLuaFunction and stores it in the Game table with lua_setfield(L, -2, "CountMyCities").
