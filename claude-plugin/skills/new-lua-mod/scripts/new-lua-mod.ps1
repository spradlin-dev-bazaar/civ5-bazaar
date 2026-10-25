<#
.SYNOPSIS
Makes a new Bazaar Lua mod folder from this skill's Lua mod template.

.DESCRIPTION
Copies the template without its build output, renames its files, puts the new names into its text files, gives the
mod a new ID on the .civ5proj's <Guid> line (the <ProjectGuid> line stays), sets the teaser, description and authors,
and writes the SQL that switches on the VMC options named in -Options. Files are changed byte for byte, so their
encoding and line endings stay as the template has them.

.EXAMPLE
new-lua-mod.ps1 -DisplayName "Turn Logger" -Options EVENTS_PLAYER_TURN

.EXAMPLE
new-lua-mod.ps1 -DisplayName "City Namer" -Options none -Destination C:\mods -Description "Logs each new city." -Author "Jane Doe"
#>
[CmdletBinding()]
param(
    # What players see: the mod's name, the Build folder's and the package's name.
    [Parameter(Mandatory = $true)] [string] $DisplayName,
    # VMC options to switch on, comma-separated, or "none".
    [Parameter(Mandatory = $true)] [string] $Options,
    # The mod's file names, with no spaces. Made from the display name when left out.
    [string] $FileName,
    # The folder to make the mod folder in.
    [string] $Destination = (Get-Location).Path,
    [string] $Description,
    # Left out, the template's "Your name" stays.
    [string] $Author
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\..\scripts\scaffold.ps1')

try {
    $DisplayName, $FileName = Get-ScaffoldNames $DisplayName $FileName @('TemplateLuaMod', 'Template Lua Mod')
    Assert-PlainText @($Description, $Author)

    # Option names are case-sensitive: the SQL matches them exactly.
    $known = New-Object 'System.Collections.Generic.Dictionary[string,string]'
    foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot '..\references\vmc-options.txt')) {
        $name, $kind = $line -split "`t"
        $known[$name] = $kind
    }
    $switchOn = @()
    if ($Options.Trim() -ne 'none') {
        foreach ($option in ($Options -split '[,\s]+' | Where-Object { $_ })) {
            if (-not $known.ContainsKey($option)) {
                Fail "'$option' is not one of VMC's options (names are case-sensitive); see references\vmc-events.md for their names."
            }
            if ($known[$option] -ne 'switch') {
                Fail "'$option' holds a number, not on or off. Set it in the .sql by hand: UPDATE CustomModOptions SET Value = <number> WHERE Name = '$option';"
            }
            if ($switchOn -cnotcontains $option) {
                $switchOn += $option
            }
        }
    }

    $target = Resolve-UserPath (Join-Path $Destination $FileName)
    if (Test-Path -LiteralPath $target) {
        Fail "'$target' already exists."
    }

    $guid = [guid]::NewGuid().ToString()
    $teaser = if ($Description) { $Description } else { "$DisplayName, a Lua mod for the Bazaar Multi-DLL Mod Loader." }
    $fields = @{ Teaser = $teaser; Description = $teaser }
    if ($Author) { $fields.Authors = $Author }
    Copy-Template (Join-Path $PSScriptRoot '..\template') $target @{ 'Template Lua Mod' = $DisplayName; 'TemplateLuaMod' = $FileName } $guid $fields

    # The template's first line explains the file; the rest is its example option.
    $sql = Join-Path $target "mod\$FileName.sql"
    $header = ((Read-RawText $sql) -split "`n")[0] + "`n"
    $updates = $switchOn | ForEach-Object { "UPDATE CustomModOptions SET Value = 1 WHERE Name = '$_';`n" }
    Write-RawText $sql ($header + ($updates -join ''))
} catch {
    Fail "The script stopped: $($_.Exception.Message)"
}

Write-Output "Made $target"
Write-Output "  Display name:     $DisplayName"
Write-Output "  File name:        $FileName"
Write-Output "  Mod ID:           $guid"
Write-Output "  VMC options on:   $(if ($switchOn.Count) { $switchOn -join ', ' } else { 'none' })"
Write-Output "Next: write the mod's Lua in mod\$FileName.lua, then run build.cmd."
