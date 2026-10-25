# What do you want to do?

Each goal below names the game functions to hook for it, and a Lua event when a Lua mod alone can do it. A function's page shows its code, what calls it, and the hook declarations to copy. The plugin-writing guide in the SDK explains how to write and register a hook.

## Every turn

### Do something at the start of each player's turn

- Hook [[CvPlayer::doTurn]], which runs when a player's turn starts, for every player, including the ones the game plays.
- A Lua mod alone can use `GameEvents.PlayerDoTurn`.

## Combat

### Change how strong units are in combat

- After-hooks on [[CvUnit::GetMaxAttackStrength]] for melee attacks, [[CvUnit::GetMaxDefenseStrength]] for defending, and [[CvUnit::GetMaxRangedCombatStrength]] for ranged attacks and air strikes. A land unit with a ranged attack of its own defends against ranged attacks with [[CvUnit::GetMaxRangedCombatStrength]] instead.
- The same numbers decide the real fight, the odds the player sees before attacking and the AI's plans, so all three stay in step.

### React to a unit dying

- [[CvUnit::kill]] runs whenever a unit leaves play, which also happens when it is upgraded, used up (a settler founding a city, a great person spent) or disbanded, and nothing in its parameters says why.
- For deaths in combat only, hook [[CvPlayer::DoUnitKilledCombat]], which runs for the player whose unit did the killing.
- Lua: `GameEvents.UnitPrekill` fires in [[CvUnit::kill]], and `GameEvents.UnitKilledInCombat` fires for deaths in combat only.

## Cities

### Change how fast cities grow

- An after-hook on [[CvCity::growthThreshold]]: the food a city needs for its next citizen. The city screen and its turns-to-grow count use the same number.

### Change a city's yields

- An after-hook on [[CvCity::getYieldRateTimes100]]: a city's total food, production, gold, science, culture or faith per turn, in hundredths.

### Change a tile's yields

- An after-hook on [[CvPlot::calculateYield]]. The game stores each tile's yields and works them out again only when something about the tile changes, so a new rule shows on a tile from its next such change.

### Change what a city can build

- A before-hook on [[CvCity::canTrain(UnitTypes, bool, bool, bool, bool, CvString *) const]] (units) or [[CvCity::canConstruct]] (buildings) that returns true vetoes the call, and the game's answer becomes no.
- To allow something the game forbids, use an after-hook that sets the result to true.
- Lua: `GameEvents.CityCanTrain` and `GameEvents.CityCanConstruct`; the answer is yes only if every handler returns true.

### Change what things cost to build

- After-hooks on [[CvCity::getProductionNeeded(UnitTypes) const]], [[CvCity::getProductionNeeded(BuildingTypes) const]] and [[CvCity::getProductionNeeded(ProjectTypes) const]]. The prices to buy with gold and to hurry production are worked out from the same numbers.

### React to a city changing hands

- [[CvPlayer::acquireCity]] runs for every city a player takes over: captured, traded, bought or annexed from a city-state, or gained in a revolt or a liberation. Its `bConquest` parameter is true when the city was captured.
- Lua: `GameEvents.CityCaptureComplete` fires in it.

## Empire

### Change gold income

- An after-hook on [[CvTreasury::CalculateGrossGold]]: a player's gold per turn before costs such as unit and building upkeep.

### Change happiness

- An after-hook on [[CvPlayer::GetExcessHappiness]]: happiness minus unhappiness. Golden age progress and the penalties for an unhappy empire read it.

### Change research costs

- [[CvTeamTechs::GetResearchCost]] is a tech's base cost for a whole team, and [[CvPlayer::calculateResearchModifier]] is one player's modifier on top of it. The game decides when research is done from these two, so hook either.
- [[CvPlayerTechs::GetResearchCost]] feeds what the screen shows, the turns left, the AI's plans and a few other rules, such as how long a spy takes to steal a tech. Hooking it alone does not change when a tech is done.

### React to a new tech or policy

- Techs: [[CvTeamTechs::SetHasTech]], for every way a team gets or loses a tech, including a Lua mod's `TeamTechs:SetHasTech`. Lua: `GameEvents.TeamSetHasTech` fires in it. Neither runs for a tech that can be researched again, such as Future Tech; [[CvTeam::setHasTech]] runs for those too.
- Policies: [[CvPlayer::setHasPolicy]], for every way a player gets or loses a policy. Lua: `GameEvents.PlayerAdoptPolicy` fires only when a player adopts one.

## Units

### React to a unit being created

- An after-hook on [[CvUnit::initWithNameOffset]], which sets up every new unit, including ones a Lua mod creates; `self` is the new unit.
- Lua: `GameEvents.UnitCreated`, a VMC event that fires in it: switch on its `EVENTS_UNIT_CREATED` option in your mod's SQL.

### Change how far units move

- An after-hook on [[CvUnit::maxMoves]]. Moves are counted in parts of a move set by the `MOVE_DENOMINATOR` define, 60 in the base game, so a unit with 2 moves returns 120. For a Great General it returns a value worked out from the units it moves with.

### React to a great person being born

- [[CvCityCitizens::DoSpawnGreatPerson]] runs for every great person a city produces, earned or chosen. The hand-placed hook [[PopupRaised]] also announces it, as `BUTTONPOPUP_GREAT_PERSON_REWARD`.

## AI and diplomacy

### Change how the AI feels about a player

- An after-hook on [[CvDiplomacyAI::GetMajorCivOpinion]] changes what every part of the AI reads as its opinion of another major civilization.
- That opinion is worked out each turn from a score, [[CvDiplomacyAI::GetMajorCivOpinionWeight]]; hook that to change the score instead.

### Change which trades the AI accepts

- [[CvDealAI::IsDealWithHumanAcceptable]] decides whether the AI accepts a trade a human player offers. [[CvDealAI::GetDealValue]] is what the AI thinks a whole deal is worth, and it also uses it to build its own offers.

## Bazaar's own tools

### Add your own Lua functions

- An after-hook on [[CvLuaGame::RegisterMembers]] adds functions to Lua's `Game` table. The plugin-writing guide's "Adding a Lua function" section shows how.

### Watch notifications and popups

- The hand-placed hook [[NotificationAdded]] announces each notification a human player gets, and [[PopupRaised]] the reward and announcement popups listed on its page, for every player.
