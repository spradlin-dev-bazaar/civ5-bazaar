#pragma once

#include <string.h>

#include <string>

inline void CivPutBytes(std::string* part, const void* data, size_t size)
{
	part->append(static_cast<const char*>(data), size);
}

inline void CivPutNumber(std::string* part, unsigned int n)
{
	CivPutBytes(part, &n, sizeof(n));
}

inline void CivPutNumber(std::string* part, __int64 n)
{
	CivPutBytes(part, &n, sizeof(n));
}

inline void CivPutNumber(std::string* part, double n)
{
	CivPutBytes(part, &n, sizeof(n));
}

inline void CivPutText(std::string* part, const std::string& text)
{
	CivPutNumber(part, (unsigned int)text.size());
	part->append(text);
}

class CivPartReader
{
public:
	explicit CivPartReader(const std::string& part) : m_part(part), m_at(0) {}

	bool Number(unsigned int* n) { return Bytes(n, sizeof(*n)); }
	bool Number(__int64* n) { return Bytes(n, sizeof(*n)); }
	bool Number(double* n) { return Bytes(n, sizeof(*n)); }

	bool Text(std::string* text)
	{
		unsigned int size = 0;
		if (!Number(&size) || m_part.size() - m_at < size)
			return false;
		text->assign(m_part, m_at, size);
		m_at += size;
		return true;
	}

private:
	bool Bytes(void* out, size_t size)
	{
		if (m_part.size() - m_at < size)
			return false;
		memcpy(out, m_part.data() + m_at, size);
		m_at += size;
		return true;
	}

	const std::string& m_part;
	size_t m_at;
};
