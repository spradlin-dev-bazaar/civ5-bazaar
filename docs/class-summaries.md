# Class summaries

## CvGame

The game in progress. There is only one, and `GC.getGame()` returns it.

- **Turns:** [[CvGame::doTurn]] runs once every player has finished a turn: it runs each team's and each tile's turn, checks whether anyone has won and moves the turn number on. [[CvGame::getGameTurn]] gives the turn number.
- **The player at this computer:** [[CvGame::getActivePlayer]] gives that human player's ID.
- **Random numbers:** [[CvGame::getJonRandNum]] gives a random number from 0 up to one less than its first parameter. Use it for anything that changes the game, so every computer in a multiplayer game draws the same numbers. [[CvGame::getAsyncRandNum]] is for things only one player sees.
- **The map** is a separate object: `GC.getMap()` returns it, a [[CvMap]], and each of its tiles is a [[CvPlot]].
- **Everything else game-wide** is in objects the game owns:

| For | Function | Class |
|---|---|---|
| trades between players | [[CvGame::GetGameDeals]] | [[CvGameDeals]] |
| religions founded in the game | [[CvGame::GetGameReligions]] | [[CvGameReligions]] |
| great works | [[CvGame::GetGameCulture]] | [[CvGameCulture]] |
| the World Congress | [[CvGame::GetGameLeagues]] | [[CvGameLeagues]] |
| trade routes | [[CvGame::GetGameTrade]] | [[CvGameTrade]] |

## CvPlayer

One object for each player: every civilization, every city-state and the barbarians, whether a person or the game plays it. `GET_PLAYER(id)` returns the player with that ID. Each one is really a [[CvPlayerAI]], a class based on this one that adds the AI's choices.

- **Turns:** [[CvPlayer::doTurn]] starts each of its turns. [[CvPlayer::doTurnPostDiplomacy]] runs its cities' turns, and [[CvPlayer::doTurnUnits]] its units'.
- **Cities and units:** [[CvPlayer::firstCity(int *, bool)|CvPlayer::firstCity]] and [[CvPlayer::nextCity(int *, bool)|CvPlayer::nextCity]] go through its cities one at a time, and [[CvPlayer::firstUnit(int *, bool)|CvPlayer::firstUnit]] and [[CvPlayer::nextUnit(int *, bool)|CvPlayer::nextUnit]] through its units.
- **Its team:** [[CvPlayer::getTeam() const|CvPlayer::getTeam]] gives its team's ID. The techs it knows, and whom it is at war with, belong to the team, a [[CvTeam]].
- **Everything else** is in objects the player owns, each returned by one of its functions:

| For | Function | Class |
|---|---|---|
| gold | [[CvPlayer::GetTreasury]] | [[CvTreasury]] |
| research | [[CvPlayer::GetPlayerTechs]] | [[CvPlayerTechs]] |
| policies | [[CvPlayer::GetPlayerPolicies]] | [[CvPlayerPolicies]] |
| its civilization's unique ability | [[CvPlayer::GetPlayerTraits]] | [[CvPlayerTraits]] |
| religion | [[CvPlayer::GetReligions]] | [[CvPlayerReligions]] |
| tourism and great works | [[CvPlayer::GetCulture]] | [[CvPlayerCulture]] |
| spies | [[CvPlayer::GetEspionage]] | [[CvPlayerEspionage]] |
| trade routes | [[CvPlayer::GetTrade]] | [[CvPlayerTrade]] |
| notifications | [[CvPlayer::GetNotifications]] | [[CvNotifications]] |
| how the AI sees other players | [[CvPlayer::GetDiplomacyAI]] | [[CvDiplomacyAI]] |
| how the AI values a trade | [[CvPlayer::GetDealAI]] | [[CvDealAI]] |
| a city-state's friends, ally and quests | [[CvPlayer::GetMinorCivAI]] | [[CvMinorCivAI]] |
| the AI's aims: which victory, its economy, its military | [[CvPlayer::GetGrandStrategyAI]], [[CvPlayer::GetEconomicAI]], [[CvPlayer::GetMilitaryAI]] | [[CvGrandStrategyAI]], [[CvEconomicAI]], [[CvMilitaryAI]] |
| the AI's unit moves, in battle and everywhere else | [[CvPlayer::GetTacticalAI]], [[CvPlayer::GetHomelandAI]] | [[CvTacticalAI]], [[CvHomelandAI]] |

## CvTeam

One object for each team. Every player is on a team: alone in most games, with its teammates in a team game. City-states and the barbarians each have a team of their own. `GET_TEAM(id)` returns the team with that ID, and [[CvPlayer::getTeam() const|CvPlayer::getTeam]] gives a player's team ID.

- **Turns:** [[CvTeam::doTurn]] runs once a game turn for each living team, as the game turn ends.
- **Techs:** the team, not the player, knows techs. [[CvTeam::GetTeamTechs]] returns them, a [[CvTeamTechs]], and [[CvTeamTechs::HasTech]] tells whether the team knows one. The front page's "React to a new tech or policy" says where a tech is gained. [[CvTeam::GetCurrentEra]] gives the team's era.
- **Meeting:** [[CvTeam::isHasMet]] tells whether it has met another team, and [[CvTeam::meet]] records a first meeting for both teams.
- **War and peace:** [[CvTeam::isAtWar]] tells whether it is at war with another team. War starts in [[CvTeam::declareWar]] and ends in [[CvTeam::makePeace]] (a map made in WorldBuilder can also start a game at war).
- **Agreements:** [[CvTeam::HasEmbassyAtTeam]], [[CvTeam::IsAllowsOpenBordersToTeam]] and [[CvTeam::IsHasDefensivePact]].

## CvCity

One object for each city. Each one is really a [[CvCityAI]], a class based on this one that adds the AI's choices. [[CvCity::getOwner]] gives the owning player's ID, and [[CvCity::plot]] the tile it stands on.

- **Turns:** [[CvCity::doTurn]] runs once a turn for each city, during its owner's turn.
- **Production:** a city works through a queue of things to build. [[CvCity::pushOrder]] adds to the queue, and [[CvCity::popOrder]] takes an item off, finishing it when its `bFinish` parameter is true. Units and buildings the city finishes or buys are made in [[CvCity::CreateUnit]] and [[CvCity::CreateBuilding]].
- **Everything else** is in objects the city owns:

| For | Function | Class |
|---|---|---|
| its buildings | [[CvCity::GetCityBuildings]] | [[CvCityBuildings]] |
| the tiles its citizens work, its specialists and their great person points | [[CvCity::GetCityCitizens]] | [[CvCityCitizens]] |
| the religions its citizens follow | [[CvCity::GetCityReligions]] | [[CvCityReligions]] |
| tourism and great works | [[CvCity::GetCityCulture]] | [[CvCityCulture]] |
| the AI's choice of what to build | [[CvCity::GetCityStrategyAI]] | [[CvCityStrategyAI]] |

## CvUnit

One object for each unit. [[CvUnit::getOwner]] gives the owning player's ID, [[CvUnit::plot]] the tile it is on, and [[CvUnit::getUnitInfo]] its unit type's details from the game's database, a [[CvUnitEntry]].

- **Turns:** [[CvUnit::doTurn]] runs once a turn for each unit, during its owner's turn.
- **Moving:** [[CvUnit::setXY]] is the one place a unit's position changes, whatever moved it. [[CvUnit::getMoves]] gives the moves it has left and [[CvUnit::maxMoves]] its moves for a whole turn, both counted in parts of a move, as the front page's "Change how far units move" explains.
- **Orders:** a unit carries out a queue of missions, such as moving somewhere, fortifying or building an improvement. [[CvUnit::PushMission]] adds one.
- **Promotions:** [[CvUnit::isHasPromotion]] and [[CvUnit::setHasPromotion]].
- **Combat and dying:** see "Change how strong units are in combat" and "React to a unit dying" on the front page.

## CvPlot

One object for each tile of the map. `GC.getMap().plot(x, y)` returns the tile at those coordinates, or null when they are off the map.

- **What is on it:** [[CvPlot::getTerrainType]], [[CvPlot::getFeatureType]], [[CvPlot::getResourceType]], [[CvPlot::getImprovementType]] and [[CvPlot::getRouteType]] (roads and railroads). Given a team, [[CvPlot::getResourceType]] hides a resource that team cannot see yet; leave the team out to get the real one. [[CvPlot::getPlotCity]] gives the city on it, if there is one, and [[CvPlot::getNumUnits]] and [[CvPlot::getUnitByIndex]] its units.
- **Who has it:** [[CvPlot::getOwner]] gives the owning player's ID, and [[CvPlot::setOwner]] changes it. [[CvPlot::getWorkingCity]] gives the city whose citizens may work it.
- **Yields:** [[CvPlot::getYield(YieldTypes) const|CvPlot::getYield]] reads the yields the game stored, and [[CvPlot::calculateYield]] works them out again.
- **What each team sees:** [[CvPlot::isRevealed(TeamTypes) const|CvPlot::isRevealed]] is true once a team has seen the tile, and [[CvPlot::isVisible(TeamTypes) const|CvPlot::isVisible]] while the team can see it now.
- **Turns:** [[CvPlot::doTurn]] runs once a game turn for every tile, not once for each player.

## CvGameDeals

Every trade between two players, kept by the game: `GC.getGame().GetGameDeals()` returns it. Each trade is a [[CvDeal]]: the two players, and the items each gives, such as gold, a resource, open borders or a peace treaty, some of them for a number of turns. Deals are kept in three lists: proposed, current and past.

- [[CvGameDeals::FinalizeDealValidAndAccepted]] runs for each deal that is accepted and still valid, and puts its items into effect.
- [[CvGameDeals::DoEndTradedItem]] ends one item, when its turns run out or the deal is cancelled.
- The hand-placed hook [[DealResolved]] announces each answer to a deal between two human players.
- How the AI values a deal is in [[CvDealAI]], one for each player.

## CvDiplomacyAI

How a player's AI sees and treats every other player: [[CvPlayer::GetDiplomacyAI]] returns it. [[CvDiplomacyAI::DoTurn]] brings it up to date at the start of each major civilization's turn.

- **Opinion**, how it feels about another major civilization, from unforgivable to ally: [[CvDiplomacyAI::GetMajorCivOpinion]]. It is worked out from a score, [[CvDiplomacyAI::GetMajorCivOpinionWeight]].
- **Approach**, how it means to treat them (war, hostile, deceptive, guarded, afraid, friendly or neutral): [[CvDiplomacyAI::GetMajorCivApproach]].
- War and peace are decided here, but made on the team: [[CvTeam::declareWar]] and [[CvTeam::makePeace]].
- Close by: [[CvDealAI]] values trades, [[CvMinorCivAI]] is a city-state's side of diplomacy, and [[CvDiplomacyRequests]] carries the AI's messages to a human player.
