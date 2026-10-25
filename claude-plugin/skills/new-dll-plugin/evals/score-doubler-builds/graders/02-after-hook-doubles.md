---
type: llm
focus: trace
weight: 1
---

The plugin registers an after-hook (CIV_HOOK_AFTER) on CivHooks::CvPlayer_GetScore::ID whose function takes const CvPlayer*, bool, bool and int&, in that order, and multiplies the result by 2.
