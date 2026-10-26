#include "CivHostNotices.h"

#include <algorithm>
#include <map>

namespace
{
	std::vector<CivNotice> s_notices;
	std::map<std::string, std::vector<std::string> > s_named;
}

void CivQueueNotice(const std::string& summary, const std::string& message)
{
	CivNotice notice;
	notice.summary = summary;
	notice.message = message;
	s_notices.push_back(notice);
}

void CivReplaceNotices(const std::string& summary, const std::vector<std::string>& messages)
{
	for (size_t i = s_notices.size(); i-- > 0;)
		if (s_notices[i].summary == summary)
			s_notices.erase(s_notices.begin() + i);
	for (size_t i = 0; i < messages.size(); ++i)
		CivQueueNotice(summary, messages[i]);
}

bool CivReplaceNoticesOnce(const std::string& summary, const std::vector<std::string>& messages)
{
	std::vector<std::string> sorted = messages;
	std::sort(sorted.begin(), sorted.end());
	std::vector<std::string>& named = s_named[summary];
	if (sorted == named)
		return false;
	named = sorted;
	CivReplaceNotices(summary, messages);
	return true;
}

void CivForgetNamedNotices()
{
	s_named.clear();
}

bool CivNoticesWaiting()
{
	return !s_notices.empty();
}

std::vector<CivNotice> CivTakeNotices()
{
	std::vector<CivNotice> taken;
	taken.swap(s_notices);
	return taken;
}
