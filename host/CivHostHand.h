#pragma once

#include "CivPluginApi.h"

#include <vector>

// The engine's calls to the hand-placed hooks, one per CivHandHook in CivPluginApi.h. The generator finds the calls by
// these names, so a new one is named CivHand plus its CivHandHook name in mixed case.
bool CivHandIsPluginControlledPlayer(int player);
bool CivHandKeepDeadSlotOpen(int player);
void CivHandPopupRaised(int player, int popupType, int data1, int data2, int data3, bool option1, bool option2, const char* text);
// For a popup raised for a team: each of the players runs the hook.
void CivHandPopupRaised(const std::vector<int>& players, int popupType, int data1, int data2, int data3, bool option1, bool option2,
	const char* text);
void CivHandNotificationAdded(int player, int notificationType, const char* message, const char* summary, int x, int y, int data1, int data2);
void CivHandDealResolved(int fromPlayer, int toPlayer, int actingPlayer, bool accepted, bool finalized);
void CivHandUnitOrdersCancelled(CvUnit* unit, int reason);
