#include "DOCS_ENGINE.H"

int Second()
{
	return Thing::Get(1).Inline() + Thing::Get(0).Inline();
}

int Broken()
{
	return undeclared_name;
}
