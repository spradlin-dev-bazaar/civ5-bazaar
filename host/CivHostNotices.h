#pragma once

#include <string>
#include <vector>

struct CivNotice
{
	std::string summary;
	std::string message;
	// Set for the pop-up after this plugin crashed, rather than a notification.
	std::string stoppedPlugin;
};

// Notices wait here until a game is running to show them.
void CivQueueNotice(const std::string& summary, const std::string& message);
// The pop-up that sends the player back to the main menu after pluginName crashed, rather than a notification.
void CivQueueStoppedPopup(const std::string& pluginName);
// At the main menu, where the game such a pop-up was for is over.
void CivDropStoppedPopups();
void CivReplaceNotices(const std::string& summary, const std::vector<std::string>& messages);
// Changes nothing, and returns false, when the messages are the ones last given for this summary, in any order, so a
// problem that lasts is named once.
bool CivReplaceNoticesOnce(const std::string& summary, const std::vector<std::string>& messages);
void CivForgetNamedNotices();
bool CivNoticesWaiting();
std::vector<CivNotice> CivTakeNotices();
