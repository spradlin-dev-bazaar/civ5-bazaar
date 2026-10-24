-- PlayerDoneTurn is one of VMC's events, so it fires only once the mod's .sql switches on its option.
GameEvents.PlayerDoneTurn.Add(function(iPlayer)
	print("Template Lua Mod: player " .. iPlayer .. " finished a turn")
end)
