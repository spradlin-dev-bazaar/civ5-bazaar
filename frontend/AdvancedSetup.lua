----------------------------------------------------
-- Bazaar's Plugins screen: the plugins Bazaar found when the mods were switched on, in the order they load.
-- It takes the Advanced Setup slot so it comes first on the way to a game, then opens the screen it replaced.
----------------------------------------------------
include( "InstanceManager" );

local g_InstanceManager = InstanceManager:new( "PluginInstance", "Root", Controls.PluginStack );

local GODS_AND_KINGS = "0E3751A1-F840-4e1b-9706-519BF484E59D";
local g_NextSetup = nil;

-- Bazaar's own notes, rows with no file, stay at the top and cannot be moved.
local g_Notes = {};
-- The plugins as shown, top first, with the player's moves and skips.
local g_Plugins = {};
-- The order and skips Bazaar last loaded.
local g_Loaded = {};

local function Lines(text)
	local lines = {};
	for line in string.gmatch(text or "", "[^\n]+") do
		table.insert(lines, line);
	end
	return lines;
end

local function HasFile(files, file)
	for _, f in ipairs(files) do
		if string.lower(f) == string.lower(file) then
			return true;
		end
	end
	return false;
end

-- Rows come from WritePluginReport in host/CivHostEngine.cpp; nil means the table is missing or unreadable.
local function PluginRows()
	local rows = nil;
	local ok, err = pcall(function()
		for _ in DB.Query("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'BazaarPlugins'") do
			rows = {};
		end
		if rows then
			for row in DB.Query("SELECT File, Name, Version, Status, Problems, Failed, Skipped, ConflictsWith, UseBothWith FROM BazaarPlugins ORDER BY Position") do
				table.insert(rows, { File = row.File or "", Name = row.Name, Version = row.Version, Status = row.Status, Problems = row.Problems,
					Failed = row.Failed == 1, Skip = row.Skipped == 1, ConflictsWith = Lines(row.ConflictsWith), UseBothWith = Lines(row.UseBothWith) });
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

local function Changed()
	if #g_Plugins ~= #g_Loaded then
		return true;
	end
	for i, row in ipairs(g_Plugins) do
		if row.File ~= g_Loaded[i].File or row.Skip ~= g_Loaded[i].Skip or table.concat(row.UseBothWith, "\n") ~= g_Loaded[i].UseBothWith then
			return true;
		end
	end
	return false;
end

local function UsesBoth(row)
	for _, file in ipairs(row.ConflictsWith) do
		if not HasFile(row.UseBothWith, file) then
			return false;
		end
	end
	return true;
end

local function PluginRow(file)
	for _, row in ipairs(g_Plugins) do
		if string.lower(row.File) == string.lower(file) then
			return row;
		end
	end
	return nil;
end

local function SetPair(row, file, useBoth)
	local kept = {};
	for _, f in ipairs(row.UseBothWith) do
		if string.lower(f) ~= string.lower(file) then
			table.insert(kept, f);
		end
	end
	if useBoth then
		table.insert(kept, file);
	end
	row.UseBothWith = kept;
end

-- A choice holds for both plugins, so it is set on both rows; the host would otherwise keep a pair the other row still lists.
local function SetUseBoth(row, useBoth)
	for _, file in ipairs(row.ConflictsWith) do
		SetPair(row, file, useBoth);
		local partner = PluginRow(file);
		if partner then
			SetPair(partner, row.File, useBoth);
		end
	end
end

local Render;

local function Move(index, step)
	g_Plugins[index], g_Plugins[index + step] = g_Plugins[index + step], g_Plugins[index];
	Render();
end

-- index is the row's place among the plugins, or nil for one of Bazaar's notes.
local function ShowRow(row, isFirst, index)
	local entry = g_InstanceManager:GetInstance();
	entry.Divider:SetHide(isFirst);
	local title = row.Name or "";
	if row.Version and row.Version ~= "" then
		title = title .. " " .. row.Version;
	end
	entry.Title:SetText(title);
	entry.Status:SetText(StatusText(row));
	entry.UseBox:SetHide(index == nil);
	entry.UpButton:SetHide(index == nil);
	entry.DownButton:SetHide(index == nil);
	entry.UseBothRow:SetHide(index == nil or #row.ConflictsWith == 0);
	if index then
		entry.UseBox:SetCheck(not row.Skip);
		entry.UseBox:RegisterCheckHandler(function(checked)
			row.Skip = not checked;
			Render();
		end);
		entry.UseBothBox:SetCheck(UsesBoth(row));
		entry.UseBothBox:RegisterCheckHandler(function(checked)
			SetUseBoth(row, checked);
			Render();
		end);
		entry.UpButton:SetDisabled(index == 1);
		entry.DownButton:SetDisabled(index == #g_Plugins);
		entry.UpButton:RegisterCallback(Mouse.eLClick, function() Move(index, -1); end);
		entry.DownButton:RegisterCallback(Mouse.eLClick, function() Move(index, 1); end);
	end
	entry.Root:CalculateSize();
end

Render = function()
	g_InstanceManager:ResetInstances();
	for i, row in ipairs(g_Notes) do
		ShowRow(row, i == 1, nil);
	end
	for i, row in ipairs(g_Plugins) do
		ShowRow(row, i == 1 and #g_Notes == 0, i);
	end
	Controls.ReloadButton:SetHide(not Changed());
	Controls.ActionStack:CalculateSize();
	Controls.ActionStack:ReprocessAnchoring();
	Controls.PluginStack:CalculateSize();
	Controls.PluginStack:ReprocessAnchoring();
	Controls.PluginScrollPanel:CalculateInternalSize();
end

local function Refresh()
	g_Notes, g_Plugins, g_Loaded = {}, {}, {};
	local rows = PluginRows();
	if rows == nil then
		Controls.EmptyLabel:SetText("Bazaar did not report its plugins, so this list is empty. Details may be in Logs\\Bazaar.log and Logs\\Lua.log.");
	else
		Controls.EmptyLabel:SetText("No plugins are enabled.");
	end
	Controls.EmptyLabel:SetHide(rows ~= nil and #rows > 0);
	for _, row in ipairs(rows or {}) do
		if row.File == "" then
			table.insert(g_Notes, row);
		else
			table.insert(g_Plugins, row);
			table.insert(g_Loaded, { File = row.File, Skip = row.Skip, UseBothWith = table.concat(row.UseBothWith, "\n") });
		end
	end
	Render();
end

local function Apply()
	local order = {};
	for i, row in ipairs(g_Plugins) do
		order[i] = { File = row.File, Skip = row.Skip, Name = row.Name, Version = row.Version, UseBothWith = row.UseBothWith };
	end
	-- Front-end Lua has no other way into Bazaar's DLL; see host/CivHostEngine.h.
	local ok, applied = pcall(UI.GetMapPreview, "bazaar:apply", order);
	if not ok or applied == nil then
		print("Bazaar did not answer the request to reload the plugins: " .. tostring(applied));
		Controls.ReloadNote:SetText("Bazaar did not answer, so the plugins were not reloaded.");
		return;
	end
	Controls.ReloadNote:SetText("");
	Refresh();
end
Controls.ReloadButton:RegisterCallback( Mouse.eLClick, Apply );

-- Bazaar copies the screen this one replaced, from another mod or the game, under a name of its own.
local function OpenNextSetup()
	if Changed() then
		Apply();
	end
	if g_NextSetup == nil then
		local ok, path = pcall(function()
			return UI.GetMapPreview("bazaar:nextsetup", Modding.GetActivatedMods(), ContentManager.IsActive(GODS_AND_KINGS, ContentType.GAMEPLAY));
		end);
		if not ok or type(path) ~= "string" then
			print("Bazaar could not open Advanced Setup: " .. tostring(path));
			Controls.ReloadNote:SetText("Bazaar could not open Advanced Setup. Details are in Logs\\Bazaar.log.");
			return;
		end
		local loaded, context = pcall(function() return ContextPtr:LoadNewContext(path); end);
		if not loaded or context == nil then
			print("Bazaar could not open Advanced Setup: " .. tostring(context));
			Controls.ReloadNote:SetText("Bazaar could not open Advanced Setup. Details are in Logs\\Lua.log.");
			return;
		end
		g_NextSetup = context;
		g_NextSetup:SetHide(true);
	end
	UIManager:QueuePopup(g_NextSetup, PopupPriority.AdvancedSetup + 1);
end
Controls.ContinueButton:RegisterCallback( Mouse.eLClick, OpenNextSetup );

local function Close()
	if Changed() then
		Apply();
	end
	UIManager:DequeuePopup( ContextPtr );
end
Controls.BackButton:RegisterCallback( Mouse.eLClick, Close );

ContextPtr:SetShowHideHandler(function(isHiding)
	if not isHiding then
		Controls.ReloadNote:SetText("");
		Refresh();
	end
end);

ContextPtr:SetInputHandler(function(uiMsg, wParam, lParam)
	if uiMsg == KeyEvents.KeyDown and wParam == Keys.VK_ESCAPE then
		Close();
	end
	return true;
end);
