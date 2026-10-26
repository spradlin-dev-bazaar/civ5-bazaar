---
type: llm
focus: trace
weight: 1
---

The plugin registers an after-hook on CivHooks::CvPlayer_GetScore (with CivRegisterAfter, or with RegisterHook and CIV_HOOK_AFTER) whose function takes const CvPlayer*, bool, bool and int&, in that order, and multiplies the result by 2.
