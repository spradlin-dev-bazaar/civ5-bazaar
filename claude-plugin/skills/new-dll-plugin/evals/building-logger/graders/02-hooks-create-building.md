---
type: llm
focus: trace
weight: 1
---

The plugin hooks a function that runs when a city completes a building (for example an after-hook on CvCity::CreateBuilding, or a before-hook on CvCity::popOrder that checks bFinish), with a parameter list that matches that function's block in CivHooks.h.
