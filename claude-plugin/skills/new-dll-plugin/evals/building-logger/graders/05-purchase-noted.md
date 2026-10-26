---
type: llm
focus: trace
weight: 1
---

If buying a building reaches the hooked function (CvCity::CreateBuilding, or anything it calls), the run tells the user that the hook also runs when a building is bought, not only when production finishes it. A hook that buying does not reach, such as one on CvCity::popOrder, passes without that note.
