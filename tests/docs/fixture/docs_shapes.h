#pragma once

class Shape
{
public:
	virtual int Area() const = 0;
};

class Square : public Shape
{
public:
	virtual int Area() const;
};
