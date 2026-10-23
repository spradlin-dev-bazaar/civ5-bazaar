----------------------------------------------------
-- Bazaar Plugins screen: the plugins Bazaar found when the mods were switched on
----------------------------------------------------
include( "InstanceManager" );

local g_InstanceManager = InstanceManager:new( "PluginInstance", "Root", Controls.PluginStack );

-- Rows come from WritePluginReport in host/CivHostEngine.cpp; nil means the table is missing or unreadable.
local function PluginRows()
	local rows = nil;
	local ok, err = pcall(function()
		for _ in DB.Query("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'BazaarPlugins'") do
			rows = {};
		end
		if rows then
			for row in DB.Query("SELECT Name, Version, Status, Problems, Failed FROM BazaarPlugins ORDER BY Position") do
				table.insert(rows, { Name = row.Name, Version = row.Version, Status = row.Status, Problems = row.Problems, Failed = row.Failed == 1 });
			end
		end
	end);
	if not ok then
		print("Could not read the BazaarPlugins table: " .. tostring(err));
		return nil;
	end
	return rows;
end

local function StatusText(row)
	local status = row.Status or "";
	local color = row.Failed and "[COLOR_NEGATIVE_TEXT]" or "[COLOR_YELLOW]";
	local lines = { row.Failed and ("[COLOR_NEGATIVE_TEXT]" .. status .. "[ENDCOLOR]") or status };
	for problem in string.gmatch(row.Problems or "", "[^\n]+") do
		table.insert(lines, color .. problem .. "[ENDCOLOR]");
	end
	return table.concat(lines, "[NEWLINE]");
end

local function Refresh()
	g_InstanceManager:ResetInstances();
	local rows = PluginRows();
	if rows == nil then
		Controls.EmptyLabel:SetText("Bazaar did not report its plugins, so this list is empty. Details may be in Logs\\Bazaar.log and Logs\\Lua.log.");
	else
		Controls.EmptyLabel:SetText("No plugins are enabled.");
	end
	Controls.EmptyLabel:SetHide(rows ~= nil and #rows > 0);

	for _, row in ipairs(rows or {}) do
		local entry = g_InstanceManager:GetInstance();
		local title = row.Name or "";
		if row.Version and row.Version ~= "" then
			title = title .. " " .. row.Version;
		end
		entry.Title:SetText(title);
		entry.Status:SetText(StatusText(row));
		entry.Root:CalculateSize();
	end
	Controls.PluginStack:CalculateSize();
	Controls.PluginStack:ReprocessAnchoring();
	Controls.PluginScrollPanel:CalculateInternalSize();
end

local function Close()
	UIManager:DequeuePopup( ContextPtr );
end
Controls.BackButton:RegisterCallback( Mouse.eLClick, Close );

ContextPtr:SetShowHideHandler(function(isHiding)
	if not isHiding then
		Refresh();
	end
end);

ContextPtr:SetInputHandler(function(uiMsg, wParam, lParam)
	if uiMsg == KeyEvents.KeyDown and wParam == Keys.VK_ESCAPE then
		Close();
	end
	return true;
end);
