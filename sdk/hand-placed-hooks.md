# Hand-placed hooks

A hand-placed hook is a spot inside an engine function where Bazaar calls plugins. A plugin registers for one in its entry function with `RegisterHandHook(pluginIndex, hook, function)`, using a `CIV_HAND_*` number and a function of the type `CivPluginApi.h` names for it. Plugins are called in load order. A question stops at the first plugin that answers yes. An announcement reaches every plugin that registered for it.

A replacement that does not run the original also stops the spots inside it from running. When that could happen between two plugins, Bazaar holds one of them back; see "What a replacement skips" in the plugin guide.

## IsPluginControlledPlayer

A question: does a plugin play this player, rather than the person at the keyboard? A yes changes two things. When a unit still has moves left after its automatic orders, the player's turn is not ended for them, just as for the person at the keyboard. And the advisor's warning before a risky attack, which the person at the keyboard gets, is not shown for their units.

## KeepDeadSlotOpen

A question, asked when a player has just been eliminated: should their slot stay open? A yes stops the game from closing it.

## PopupRaised

An announcement: the game raised a popup for this player, or would have if they were at the keyboard. It also runs for players the game plays itself. A popup for a team reaches each of the team's living players. A value a popup does not have, or that names the player at the keyboard, is -1, and the text is empty unless the table gives one.

| Popup | data1 | data2 | data3 | option1 | option2 | text |
|---|---|---|---|---|---|---|
| `BUTTONPOPUP_WONDER_COMPLETED_ACTIVE_PLAYER` | the wonder | | | | | |
| `BUTTONPOPUP_GREAT_PERSON_REWARD` | the unit type | the city's ID | | | | |
| `BUTTONPOPUP_CITY_STATE_GREETING` | the city-state | the gift | the friendship gained | first to meet it | | the kind of gift |
| `BUTTONPOPUP_CITY_CAPTURED` | the city's ID | the gold taken | the culture taken | bought from a city-state | taken by conquest | |
| `BUTTONPOPUP_GOODY_HUT_REWARD` | the goody type | the gold, culture or faith found, or 0 | | | | what the hut gave |
| `BUTTONPOPUP_GOLDEN_AGE_REWARD` | | | | | | |
| `BUTTONPOPUP_NATURAL_WONDER_REWARD`, for a team | x | y | the gold for finding it | first to find it | | |
| `BUTTONPOPUP_TECH_AWARD`, for a team | | 0 | the tech | | | |
| `BUTTONPOPUP_NEW_ERA`, for a team | the era | | | | | |
| `BUTTONPOPUP_BARBARIAN_CAMP_REWARD` | the gold | | | | | |

The city-state greeting depends on VMC's `GLOBAL_CS_GIFTS` option. With it on, the values are as in the table, and the text is the kind of gift: CULTURE, FAITH, GOLD, FOOD or UNIT, or UNKNOWN when none of those applies. With it off, data2 is the gold given, data3 is the faith given, and the text is empty.

## NotificationAdded

An announcement: a notification was added to this player's list. The values are the ones the game's `CvNotifications::Add` received: the notification type, the message, the summary, the plot's x and y, and its two data values. The game keeps notifications only for human players, so it runs only for them.

## DealResolved

An announcement: a proposed deal was accepted or turned down. The values are the player who proposed it, the player it was proposed to, the player who answered, whether it was accepted, and whether the game carried it out. A deal can be accepted and still not be carried out, for example when it is no longer valid. It runs only for deals between two human players, which includes any player a plugin plays. Deals with a computer player do not run it, even when you accept a computer player's offer.

## UnitOrdersCancelled

An announcement: the game cancelled a unit's orders. The values are the unit and one of these reasons. It runs before the game clears the unit's orders, so you can still read them inside it; give the unit new orders later rather than from inside it.

| Reason | Why |
|---|---|
| `CIV_ORDERS_PROMOTION_READY` | the unit earned a promotion |
| `CIV_ORDERS_CANNOT_LAND` | an air unit can no longer move to its target |
| `CIV_ORDERS_NO_ROUTE_TO_BUILD` | no road can be built that way any more |
| `CIV_ORDERS_ROUTE_BLOCKED` | the next tile on the road being built can no longer be entered |
| `CIV_ORDERS_NO_PATH` | no path leads to the destination any more |
| `CIV_ORDERS_PATH_LONGER` | the way there now takes more than two turns longer than when the move began |
| `CIV_ORDERS_DESTINATION_BLOCKED` | the unit would end this turn on its destination, which it can no longer enter, on a move ordered before this turn |
