---
type: llm
focus: trace
weight: 1
---

The after-hook pushes a C function with lua_pushcclosure or lua_pushcfunction and stores it in the Game table with lua_setfield(L, -2, "CountMyCities").
