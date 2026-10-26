#pragma once

#include <string>
#include <vector>

struct CivNotice
{
	std::string summary;
	std::string message;
};

// Notices wait here until a game is running to show them.
void CivQueueNotice(const std::string& summary, const std::string& message);
void CivReplaceNotices(const std::string& summary, const std::vector<std::string>& messages);
// Changes nothing, and returns false, when the messages are the ones last given for this summary, in any order, so a
// problem that lasts is named once.
bool CivReplaceNoticesOnce(const std::string& summary, const std::vector<std::string>& messages);
void CivForgetNamedNotices();
bool CivNoticesWaiting();
std::vector<CivNotice> CivTakeNotices();
