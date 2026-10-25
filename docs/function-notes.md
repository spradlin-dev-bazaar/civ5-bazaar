# Function notes

## CvUnit::kill

Runs whenever a unit leaves play: when it dies, and also when it is upgraded, used up (a settler founding a city, a great person spent) or disbanded. Nothing in its parameters says which. For deaths in combat only, hook [[CvPlayer::DoUnitKilledCombat]], which runs for the player whose unit did the killing.

## CvPlot::calculateYield

The game stores each tile's yields and calls this to work them out again only when something about the tile changes, so a new rule hooked here shows on a tile from its next such change. [[CvPlot::getYield(YieldTypes) const|CvPlot::getYield]] reads the stored yields.

## CvPlayer::doTurn

Runs at the start of each player's turn, for every player, including the ones the game plays. The player's cities take their turns later, in [[CvPlayer::doTurnPostDiplomacy]], and its units in [[CvPlayer::doTurnUnits]].
