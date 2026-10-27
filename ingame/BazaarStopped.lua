-- Shown after a plugin crashes. The game may be damaged, so the only way on is the main menu.

local leaving = false

-- The screen stays up until the game is gone, so it keeps taking keys while the game exits.
local function ReturnToMainMenu()
	if leaving then
		return
	end
	leaving = true
	UIManager:SetUICursor(1)
	Events.ExitToMainMenu()
end

GameEvents.BazaarPluginStopped.Add(function(text)
	if ContextPtr:IsHidden() then
		Controls.Message:LocalizeAndSetText(text)
		Controls.Grid:DoAutoSize()
		UIManager:QueuePopup(ContextPtr, PopupPriority.InGameUtmost)
	end
	return true
end)

Controls.ReturnButton:RegisterCallback(Mouse.eLClick, ReturnToMainMenu)

-- While shown it takes every key, so no shortcut, such as a quicksave mod's, saves the damaged game.
ContextPtr:SetInputHandler(function(uiMsg, wParam)
	if ContextPtr:IsHidden() then
		return false
	end
	if uiMsg == KeyEvents.KeyDown and (wParam == Keys.VK_ESCAPE or wParam == Keys.VK_RETURN) then
		ReturnToMainMenu()
	end
	return true
end)

ContextPtr:SetHide(true)
