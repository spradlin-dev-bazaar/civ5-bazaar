#include "CivHostNotices.h"
#include "CivHostLock.h"

#include <algorithm>
#include <map>

namespace
{
	std::vector<CivNotice> s_notices;
	std::map<std::string, std::vector<std::string> > s_named;
	CivLock s_lock;
}

void CivQueueNotice(const std::string& summary, const std::string& message)
{
	CivNotice notice;
	notice.summary = summary;
	notice.message = message;
	CivLockHold hold(s_lock);
	s_notices.push_back(notice);
}

void CivQueueStoppedPopup(const std::string& pluginName)
{
	CivNotice notice;
	notice.stoppedPlugin = pluginName;
	CivLockHold hold(s_lock);
	s_notices.push_back(notice);
}

void CivDropStoppedPopups()
{
	CivLockHold hold(s_lock);
	for (size_t i = s_notices.size(); i-- > 0;)
		if (!s_notices[i].stoppedPlugin.empty())
			s_notices.erase(s_notices.begin() + i);
}

void CivReplaceNotices(const std::string& summary, const std::vector<std::string>& messages)
{
	CivLockHold hold(s_lock);
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
	CivLockHold hold(s_lock);
	std::vector<std::string>& named = s_named[summary];
	if (sorted == named)
		return false;
	named = sorted;
	CivReplaceNotices(summary, messages);
	return true;
}

void CivForgetNamedNotices()
{
	CivLockHold hold(s_lock);
	s_named.clear();
}

bool CivNoticesWaiting()
{
	CivLockHold hold(s_lock);
	return !s_notices.empty();
}

std::vector<CivNotice> CivTakeNotices()
{
	std::vector<CivNotice> taken;
	CivLockHold hold(s_lock);
	taken.swap(s_notices);
	return taken;
}
