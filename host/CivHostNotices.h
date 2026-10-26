#pragma once

#include <string>
#include <vector>

struct CivNotice
{
	CivNotice() : popup(false) {}

	std::string summary;
	std::string message;
	bool popup;
};

// Notices wait here until a game is running to show them.
void CivQueueNotice(const std::string& summary, const std::string& message);
// In the middle of the screen, where the player must close it, rather than in the list of notifications.
void CivQueuePopup(const std::string& message);
void CivReplaceNotices(const std::string& summary, const std::vector<std::string>& messages);
// Changes nothing, and returns false, when the messages are the ones last given for this summary, in any order, so a
// problem that lasts is named once.
bool CivReplaceNoticesOnce(const std::string& summary, const std::vector<std::string>& messages);
void CivForgetNamedNotices();
bool CivNoticesWaiting();
std::vector<CivNotice> CivTakeNotices();
