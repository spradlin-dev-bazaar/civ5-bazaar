<#
.SYNOPSIS
Makes a new Bazaar plugin folder from the Bazaar SDK's plugin template.

.DESCRIPTION
Copies the template without its build output, renames its files, puts the new names into its text files, gives the
mod a new ID on the .civ5proj's <Guid> line (the <ProjectGuid> line stays), and sets the teaser, description and
authors. Files are changed byte for byte, so their encoding and line endings stay as the template has them.

.EXAMPLE
new-dll-plugin.ps1 -DisplayName "Score Doubler"

.EXAMPLE
new-dll-plugin.ps1 -DisplayName "Score Doubler" -FileName ScoreDoubler -Destination C:\mods -Description "Doubles every player's score." -Author "Jane Doe"
#>
[CmdletBinding()]
param(
    # What players see: the mod's name, the Build folder's and the package's name, and the name the plugin reports.
    [Parameter(Mandatory = $true)] [string] $DisplayName,
    # The DLL's and the project's name, with no spaces. Made from the display name when left out.
    [string] $FileName,
    # The folder to make the plugin folder in.
    [string] $Destination = (Get-Location).Path,
    [string] $Sdk = $env:BAZAAR_SDK,
    [string] $Description,
    # Left out, the template's "Your name" stays.
    [string] $Author
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\..\scripts\scaffold.ps1')

try {
    $DisplayName, $FileName = Get-ScaffoldNames $DisplayName $FileName @('TemplatePlugin', 'Template Plugin')
    Assert-PlainText @($Description, $Author)

    if (-not $Sdk) {
        Fail 'Set BAZAAR_SDK to the Bazaar SDK folder, or pass -Sdk.'
    }
    $Sdk = Resolve-UserPath $Sdk
    $template = Join-Path $Sdk 'plugin-template'
    if (-not (Test-Path -LiteralPath (Join-Path $Sdk 'CivPlugin.vsprops')) -or -not (Test-Path -LiteralPath $template)) {
        Fail "'$Sdk' is not a Bazaar SDK folder: it has no CivPlugin.vsprops and plugin-template."
    }

    $target = Resolve-UserPath (Join-Path $Destination $FileName)
    if (($target + '\').StartsWith($Sdk.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Fail "'$target' is inside the SDK folder, which the SDK build deletes and rebuilds. Choose another -Destination."
    }
    if (Test-Path -LiteralPath $target) {
        Fail "'$target' already exists."
    }

    $guid = [guid]::NewGuid().ToString()
    $teaser = if ($Description) { $Description } else { "$DisplayName, a plugin for the Bazaar Multi-DLL Mod Loader." }
    $fields = @{ Teaser = $teaser; Description = $teaser }
    if ($Author) { $fields.Authors = $Author }
    Copy-Template $template $target @{ 'Template Plugin' = $DisplayName; 'TemplatePlugin' = $FileName } $guid $fields
} catch {
    Fail "The script stopped: $($_.Exception.Message)"
}

Write-Output "Made $target"
Write-Output "  Display name: $DisplayName"
Write-Output "  File name:    $FileName ($FileName.dll)"
Write-Output "  Mod ID:       $guid"
Write-Output "Next: write the hooks in src\$FileName.cpp, then run build.cmd with BAZAAR_SDK set to $Sdk."
