<#
.SYNOPSIS
Makes a release of this mod: sets its version from VERSION, builds it with build.cmd, checks the package and keeps it
in Releases\<release>.

.DESCRIPTION
Run it with release.cmd. VERSION names the release, either as a whole number, which is also the mod's version, or as a
semantic version such as 1.2.0, with a 'mod' line the script keeps above every released mod version; and, on a
'bazaar' line, the oldest Bazaar release the mod needs. Before building, the script writes the version into VERSION,
the .civ5proj's <ModVersion> and, for a plugin, src\PluginVersion.h. Releases\ is the record of what was released, so
keep it. Uploading the package to the Steam Workshop stays a step in ModBuddy.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$templateIds = @('63a9bd4c-c9fc-4d26-97c7-9a8a86e331be', 'f4d85239-ecea-43dc-b4ff-e64e23ad91b4')
# Split so the scaffold scripts, which put a new mod's names in place of the template's in every file, leave these.
$templateNames = @(('Template' + ' Plugin'), ('Template' + ' Lua Mod'))
$templateDll = 'Template' + 'Plugin.dll'
$templateTeasers = @('A minimal plugin for the Bazaar Multi-DLL Mod Loader.', 'A minimal Lua mod for the Bazaar Multi-DLL Mod Loader.')
# Latin-1 maps every byte to one character and back, so files keep their encoding and line endings.
$latin1 = [Text.Encoding]::GetEncoding(28591)
$number = '(?:0|[1-9][0-9]{0,8})'
$wholeNumberPattern = '^[1-9][0-9]{0,8}$'
$identifiers = '[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*'
$semanticVersionPattern = "^$number\.$number\.$number(?:-$identifiers)?(?:\+$identifiers)?$"
$bazaarReleasePattern = "^($number)\.($number)\.($number)$"
$versionDefine = '(#define\s+PLUGIN_VERSION\s+")[^"]*(")'
$tar = Join-Path $env:SystemRoot 'System32\tar.exe'
$rerunNote = 'VERSION and the project files already have the new version, so run release.cmd again once it is fixed.'

function Stop-Release([string] $message) {
    [Console]::Error.WriteLine("release: $message")
    exit 1
}

function Read-RawText([string] $path) {
    return $latin1.GetString([IO.File]::ReadAllBytes($path))
}

function Write-RawText([string] $path, [string] $content) {
    [IO.File]::WriteAllBytes($path, $latin1.GetBytes($content))
}

function Set-FileText([string] $path, [string] $content) {
    if ((Read-RawText $path) -ne $content) {
        Write-RawText $path $content
    }
}

# For the files an author edits by hand, which some editors save with a byte order mark.
function Read-TextFile([string] $path) {
    $text = Read-RawText $path
    if ($text.StartsWith([string] [char] 0xFF + [char] 0xFE) -or $text.StartsWith([string] [char] 0xFE + [char] 0xFF)) {
        Stop-Release "$(Split-Path -Leaf $path) is saved as UTF-16. Save it as plain text (UTF-8 or ANSI)."
    }
    if ($text.StartsWith([string] [char] 0xEF + [char] 0xBB + [char] 0xBF)) {
        return $text.Substring(3)
    }
    return $text
}

# Not run with &: in Windows PowerShell, a program's error output can become errors that stop this script.
function Invoke-Program([string] $file, [string] $arguments) {
    $start = New-Object Diagnostics.ProcessStartInfo $file, $arguments
    $start.UseShellExecute = $false
    $process = [Diagnostics.Process]::Start($start)
    $process.WaitForExit()
    return $process.ExitCode
}

function Get-ProjectElement([string] $text, [string] $element) {
    $found = [regex]::Match($text, "<$element>([^<]*)</$element>")
    if (-not $found.Success) {
        Stop-Release "The .civ5proj has no <$element> line."
    }
    return $found.Groups[1].Value
}

function Read-VersionFile([string] $path) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Stop-Release "There is no VERSION file. Make one with a line 'release 1' and a line naming the oldest Bazaar release the mod needs, such as 'bazaar 0.4.0'."
    }
    $fields = @{}
    foreach ($line in ((Read-TextFile $path) -split "`r?`n")) {
        if (-not $line.Trim()) {
            continue
        }
        $parsed = [regex]::Match($line, '^(release|mod|bazaar) +(\S+) *$')
        if (-not $parsed.Success) {
            Stop-Release "VERSION's line '$line' should look like 'release 2', 'mod 3' or 'bazaar 0.4.0'."
        }
        $key = $parsed.Groups[1].Value
        if ($fields.ContainsKey($key)) {
            Stop-Release "VERSION has two '$key' lines."
        }
        $fields[$key] = $parsed.Groups[2].Value
    }
    foreach ($key in @('release', 'bazaar')) {
        if (-not $fields.ContainsKey($key)) {
            Stop-Release "VERSION has no '$key' line."
        }
    }
    $release = $fields['release']
    $isWholeNumber = $release -match $wholeNumberPattern
    if (-not $isWholeNumber -and $release -notmatch $semanticVersionPattern) {
        Stop-Release "VERSION's release, '$release', is neither a whole number, such as 3, nor a semantic version, such as 1.2.0."
    }
    if ($fields['bazaar'] -notmatch $bazaarReleasePattern) {
        Stop-Release "VERSION's bazaar line, '$($fields['bazaar'])', is not a Bazaar release number, such as 0.4.0."
    }
    $mod = $null
    if ($fields.ContainsKey('mod')) {
        if ($isWholeNumber) {
            Stop-Release "VERSION has a 'mod' line, but a whole-number release is the mod's version itself. Remove the 'mod' line."
        }
        if ($fields['mod'] -notmatch $wholeNumberPattern) {
            Stop-Release "VERSION's mod line, '$($fields['mod'])', is not a whole number above 0."
        }
        $mod = [int] $fields['mod']
    }
    return @{ Release = $release; Mod = $mod; Bazaar = $fields['bazaar']; IsWholeNumber = $isWholeNumber }
}

function Read-Project([string] $root) {
    $files = @(Get-ChildItem -LiteralPath (Join-Path $root 'mod') -Filter '*.civ5proj' -File -ErrorAction SilentlyContinue)
    if ($files.Count -ne 1) {
        Stop-Release "Expected one .civ5proj in the mod folder, found $($files.Count)."
    }
    $text = Read-RawText $files[0].FullName
    $modVersion = (Get-ProjectElement $text 'ModVersion').Trim()
    if ($modVersion -notmatch $wholeNumberPattern) {
        Stop-Release "The .civ5proj's <ModVersion> is '$modVersion', not a whole number above 0."
    }
    return @{
        File       = $files[0].FullName
        Text       = $text
        Name        = Get-ProjectElement $text 'Name'
        Id          = (Get-ProjectElement $text 'Guid').Trim().ToLowerInvariant()
        Authors     = (Get-ProjectElement $text 'Authors').Trim()
        Teaser      = [regex]::Match($text, '<Teaser>([^<]*)</Teaser>').Groups[1].Value
        Description = [regex]::Match($text, '<Description>([^<]*)</Description>').Groups[1].Value
        ModVersion  = [int] $modVersion
    }
}

function Assert-NoTemplateLeftovers($project, [string] $root) {
    if ($templateIds -contains $project.Id) {
        Stop-Release "The .civ5proj still has the template's mod ID. Give the mod its own: put a new GUID on the <Guid> line (PowerShell's New-Guid makes one)."
    }
    if ($templateNames -contains $project.Name.Trim()) {
        Stop-Release "The mod is still called '$($project.Name)', the template's name. Change the .civ5proj's <Name> line."
    }
    if ($project.Authors -eq 'Your name') {
        Stop-Release "The .civ5proj's author is still 'Your name'. Change its <Authors> line."
    }
    foreach ($teaser in $templateTeasers) {
        if ($project.Teaser.Contains($teaser) -or $project.Description.Contains($teaser)) {
            Stop-Release "The .civ5proj's <Teaser> or <Description> still has the template's text '$teaser'. Describe your mod there."
        }
    }
    foreach ($sql in Get-ChildItem -LiteralPath (Join-Path $root 'mod') -Filter '*.sql' -File) {
        if (@(Get-DllPluginRows (Read-RawText $sql.FullName)) -contains $templateDll) {
            Stop-Release "mod\$($sql.Name) still adds the template's DLL, $templateDll, to DllPlugins. Rename the DLL and its row as the guide's Step 2 says: no two plugins may ship a DLL with the same name."
        }
    }
}

function Assert-WorkshopDescription([string] $root, [string] $bazaar) {
    $path = Join-Path $root 'workshop-description.txt'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Stop-Release "There is no workshop-description.txt, the description to paste into ModBuddy. Make one that says 'Requires Bazaar $bazaar or newer.'"
    }
    $text = Read-TextFile $path
    foreach ($leftover in $templateNames + $templateTeasers) {
        if ($text.Contains($leftover)) {
            Stop-Release "workshop-description.txt still has the template's text '$leftover'. Write your mod's own description there."
        }
    }
    $requires = @([regex]::Matches($text, 'Requires Bazaar (\S+) or newer\.') | ForEach-Object { $_.Groups[1].Value })
    if (-not $requires.Count) {
        Stop-Release "workshop-description.txt does not say 'Requires Bazaar $bazaar or newer.'"
    }
    foreach ($named in $requires) {
        if ($named -ne $bazaar) {
            Stop-Release "workshop-description.txt says 'Requires Bazaar $named or newer.', but VERSION names Bazaar $bazaar."
        }
    }
}

function Get-ReleasedModVersions([string] $releases) {
    Get-ChildItem -LiteralPath $releases -Recurse -File -ErrorAction SilentlyContinue |
        ForEach-Object { [regex]::Match($_.Name, '\(v (\d+)\)\.civ5mod$') } |
        Where-Object { $_.Success } |
        ForEach-Object { [int] $_.Groups[1].Value }
}

function Test-Released([string] $releases, [string] $release) {
    $packages = @(Get-ChildItem -LiteralPath (Join-Path $releases $release) -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -eq '.civ5mod' })
    return $packages.Count -gt 0
}

function Test-ReleaseBelow([string] $release, [string] $other) {
    $mine = [regex]::Match($release, '^(\d+)\.(\d+)\.(\d+)')
    $theirs = [regex]::Match($other, '^(\d+)\.(\d+)\.(\d+)')
    for ($part = 1; $part -le 3; $part++) {
        $difference = [long] $mine.Groups[$part].Value - [long] $theirs.Groups[$part].Value
        if ($difference) {
            return $difference -lt 0
        }
    }
    return $false
}

function Assert-NotBelowReleased([string] $releases, $version) {
    if ($version.IsWholeNumber) {
        return
    }
    $released = Get-ChildItem -LiteralPath $releases -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match $semanticVersionPattern -and (Test-Released $releases $_.Name) }
    foreach ($folder in $released) {
        if (Test-ReleaseBelow $version.Release $folder.Name) {
            Stop-Release "$($version.Release) is below $($folder.Name), which is already released. Raise the release in VERSION above it."
        }
    }
}

function Resolve-ModVersion($version, $project, [int[]] $releasedModVersions) {
    $highest = 0
    if ($releasedModVersions.Count) {
        $highest = ($releasedModVersions | Measure-Object -Maximum).Maximum
    }
    if ($version.IsWholeNumber) {
        $modVersion = [int] $version.Release
        if ($modVersion -le $highest) {
            Stop-Release "Mod version $highest is already released, and a release's whole number is its mod version. Raise the release in VERSION above $highest."
        }
        if ($modVersion -lt $project.ModVersion) {
            Stop-Release "The .civ5proj's mod version is $($project.ModVersion), and a release's whole number is its mod version, so release $modVersion would go below it. Raise the release in VERSION to $($project.ModVersion) or more."
        }
        return $modVersion
    }
    $modVersion = [Math]::Max($highest + 1, $project.ModVersion)
    if ($null -ne $version.Mod) {
        $modVersion = [Math]::Max($modVersion, $version.Mod)
    }
    return [int] $modVersion
}

function Get-SdkApiVersion([string] $root) {
    $sdk = if ($env:BAZAAR_SDK) { $env:BAZAAR_SDK } else { Split-Path $root }
    if (-not (Test-Path -LiteralPath (Join-Path $sdk 'CivPlugin.vsprops') -PathType Leaf)) {
        Stop-Release 'Set BAZAAR_SDK to the Bazaar SDK folder.'
    }
    $header = Join-Path $sdk 'include\CivPluginApi.h'
    if (-not (Test-Path -LiteralPath $header -PathType Leaf)) {
        Stop-Release "The SDK has no include\CivPluginApi.h."
    }
    $text = Read-RawText $header
    $major = [regex]::Match($text, '#define CIV_HOST_API_MAJOR (\d+)')
    $minor = [regex]::Match($text, '#define CIV_HOST_API_MINOR (\d+)')
    if (-not $major.Success -or -not $minor.Success) {
        Stop-Release "The SDK's include\CivPluginApi.h names no API version."
    }
    return '{0}.{1}' -f [int] $major.Groups[1].Value, [int] $minor.Groups[1].Value
}

# Bazaar refuses a plugin built for another major version or a newer minor one.
function Assert-SdkFitsBazaar([string] $api, [string] $bazaar) {
    $built = [regex]::Match($api, '^(\d+)\.(\d+)$')
    $needs = [regex]::Match($bazaar, $bazaarReleasePattern)
    if ([int] $built.Groups[1].Value -ne [int] $needs.Groups[1].Value -or [int] $built.Groups[2].Value -gt [int] $needs.Groups[2].Value) {
        Stop-Release "This SDK builds plugins for Bazaar's API $api, which Bazaar $bazaar refuses. Change the bazaar line in VERSION, and the 'Requires Bazaar ... or newer.' sentence in workshop-description.txt, to $api.0, or build with the SDK of Bazaar $bazaar."
    }
}

function Assert-PluginVersionHeader([string] $root, [string] $header) {
    if (-not (Test-Path -LiteralPath $header -PathType Leaf) -or (Read-RawText $header) -notmatch $versionDefine) {
        Stop-Release "src\PluginVersion.h is missing or has no line '#define PLUGIN_VERSION `"<version>`"'. Copy it from the SDK's plugin template."
    }
    $users = @(Get-ChildItem -LiteralPath (Join-Path $root 'src') -Recurse -File |
            Where-Object { $_.Extension -in '.cpp', '.h' -and $_.Name -ne 'PluginVersion.h' } |
            Where-Object { (Read-RawText $_.FullName) -match '\bPLUGIN_VERSION\b' })
    if (-not $users.Count) {
        Stop-Release 'No file in src uses PLUGIN_VERSION, so the plugin would report a version of its own. Include PluginVersion.h and set the plugin''s version to PLUGIN_VERSION in CivPluginEntry, as the template does.'
    }
}

function Test-ChangesSection([string] $root, [string] $release) {
    $path = Join-Path $root 'CHANGES.txt'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return $false
    }
    $heading = '(?im)^[ \t]*\[(b|h1|h2|h3)\]v?' + [regex]::Escape($release) + '\[/\1\][ \t]*\r?$'
    return (Read-TextFile $path) -match $heading
}

function Write-Versions($version, [int] $modVersion, $project, [string] $versionFile, [string] $header) {
    $modLine = if ($version.IsWholeNumber) { '' } else { "mod $modVersion`n" }
    Set-FileText $versionFile ("release $($version.Release)`n" + $modLine + "bazaar $($version.Bazaar)`n")
    $element = [regex] '<ModVersion>[^<]*</ModVersion>'
    Set-FileText $project.File ($element.Replace($project.Text, "<ModVersion>$modVersion</ModVersion>", 1))
    if ($header) {
        $text = Read-RawText $header
        Set-FileText $header ([regex]::Replace($text, $versionDefine, "`${1}$($version.Release)`${2}"))
    }
}

function Get-BuiltPackages([string] $root, [int] $modVersion) {
    Get-ChildItem -LiteralPath (Join-Path $root 'Packages') -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name.EndsWith(" (v $modVersion).civ5mod", [StringComparison]::OrdinalIgnoreCase) }
}

function Invoke-Build([string] $root, [int] $modVersion) {
    Get-BuiltPackages $root $modVersion | Remove-Item -Force
    if ((Invoke-Program $env:ComSpec "/d /s /c `"`"$(Join-Path $root 'build.cmd')`" 2>&1`"") -ne 0) {
        Stop-Release "build.cmd stopped; its messages are above. Nothing was released. $rerunNote"
    }
    $built = @(Get-BuiltPackages $root $modVersion)
    if ($built.Count -ne 1) {
        Stop-Release "build.cmd made $($built.Count) packages ending in '(v $modVersion).civ5mod' in Packages, not one. Nothing was released. $rerunNote"
    }
    return $built[0].FullName
}

function Get-DllPluginRows([string] $sql) {
    # Quoted text is matched first and kept, so '--' inside a DLL's name is not taken for a comment.
    $code = [regex]::Replace($sql, "'[^']*'|--[^\r\n]*|/\*[\s\S]*?\*/", { param($found) if ($found.Value[0] -eq "'") { $found.Value } else { '' } })
    foreach ($insert in [regex]::Matches($code, '(?i)(?:INSERT\s+(?:OR\s+\w+\s+)?|REPLACE\s+)INTO\s+["`\[]?DllPlugins\b[^;]*')) {
        foreach ($value in [regex]::Matches($insert.Value, "'([^']+)'")) {
            $value.Groups[1].Value
        }
    }
}

# $null means no such export; a file that is not a 32-bit DLL throws. Offsets: Microsoft's PE format specification.
# CivPluginApiVersion's address holds two ints, the major and minor API version (CivPluginApi.h).
function Get-ExportedApiVersion([byte[]] $data) {
    $peHeader = [BitConverter]::ToInt32($data, 0x3C)
    if ($peHeader -lt 0 -or [BitConverter]::ToUInt32($data, $peHeader) -ne 0x4550) {
        throw 'No PE header.'
    }
    $sectionCount = [BitConverter]::ToUInt16($data, $peHeader + 6)
    $optionalHeaderSize = [BitConverter]::ToUInt16($data, $peHeader + 20)
    $optionalHeader = $peHeader + 24
    if ([BitConverter]::ToUInt16($data, $optionalHeader) -ne 0x10B) {
        throw 'Not a 32-bit DLL.'
    }
    $sections = @(for ($i = 0; $i -lt $sectionCount; $i++) {
            $entry = $optionalHeader + $optionalHeaderSize + 40 * $i
            [pscustomobject]@{
                Size    = [Math]::Max([BitConverter]::ToUInt32($data, $entry + 8), [BitConverter]::ToUInt32($data, $entry + 16))
                Address = [long] [BitConverter]::ToUInt32($data, $entry + 12)
                Start   = [long] [BitConverter]::ToUInt32($data, $entry + 20)
            }
        })
    $toFilePosition = {
        param([long] $address)
        foreach ($section in $sections) {
            if ($address -ge $section.Address -and $address -lt $section.Address + $section.Size) {
                return $section.Start + $address - $section.Address
            }
        }
        throw "No section holds address $address."
    }
    $exportTableAddress = [BitConverter]::ToUInt32($data, $optionalHeader + 96)
    if ($exportTableAddress -eq 0) {
        return $null
    }
    $exportTable = & $toFilePosition $exportTableAddress
    $nameCount = [BitConverter]::ToUInt32($data, $exportTable + 24)
    $functions = & $toFilePosition ([BitConverter]::ToUInt32($data, $exportTable + 28))
    $names = & $toFilePosition ([BitConverter]::ToUInt32($data, $exportTable + 32))
    $ordinals = & $toFilePosition ([BitConverter]::ToUInt32($data, $exportTable + 36))
    for ($i = 0; $i -lt $nameCount; $i++) {
        $nameStart = & $toFilePosition ([BitConverter]::ToUInt32($data, $names + 4 * $i))
        $nameEnd = [Array]::IndexOf($data, [byte] 0, [int] $nameStart)
        if ([Text.Encoding]::ASCII.GetString($data, $nameStart, $nameEnd - $nameStart) -ceq 'CivPluginApiVersion') {
            $ordinal = [BitConverter]::ToUInt16($data, $ordinals + 2 * $i)
            $value = & $toFilePosition ([BitConverter]::ToUInt32($data, $functions + 4 * $ordinal))
            return '{0}.{1}' -f [BitConverter]::ToInt32($data, $value), [BitConverter]::ToInt32($data, $value + 4)
        }
    }
    return $null
}

function Get-UnpackedModProblems([string] $folder, [int] $modVersion, [bool] $isPlugin, [string] $sdkApi) {
    $problems = New-Object 'System.Collections.Generic.List[string]'
    $modinfo = @(Get-ChildItem -LiteralPath $folder -Filter '*.modinfo' -File)
    if ($modinfo.Count -ne 1) {
        $problems.Add("it has $($modinfo.Count) mod descriptions (.modinfo files), not one")
        return $problems
    }
    $text = Read-RawText $modinfo[0].FullName
    $packaged = [regex]::Match($text, '<Mod [^>]*\bversion="(\d+)"')
    if (-not $packaged.Success -or [int] $packaged.Groups[1].Value -ne $modVersion) {
        $shown = if ($packaged.Success) { $packaged.Groups[1].Value } else { 'missing' }
        $problems.Add("its mod version is $shown, not $modVersion")
    }
    $updates = @([regex]::Matches($text, '<UpdateDatabase>([^<]+)</UpdateDatabase>') | ForEach-Object { $_.Groups[1].Value })
    if ($updates.Count -and $text -notmatch '<AffectsSavedGames>1</AffectsSavedGames>') {
        $problems.Add('it changes the game''s database but does not affect saved games, so a loaded save would leave those changes out')
    }
    $dlls = @(foreach ($update in $updates) {
            $sql = Join-Path $folder $update
            if (Test-Path -LiteralPath $sql -PathType Leaf) {
                Get-DllPluginRows (Read-RawText $sql)
            }
        })
    if (-not $isPlugin) {
        if ($dlls.Count -or @(Get-ChildItem -LiteralPath $folder -Filter '*.dll' -Recurse -File).Count) {
            $problems.Add('it holds a DLL, but this project has no src\*.vcproj, so it was checked as a Lua mod, without the plugin checks. A plugin keeps its Visual C++ project in src, as the template does')
        }
        return $problems
    }
    if (-not $dlls.Count) {
        $problems.Add('no database update in it adds the plugin''s DLL to the DllPlugins table, so Bazaar would never load it (the script reads rows written as INSERT INTO DllPlugins (File) VALUES (''Name.dll''), as the template does)')
    }
    foreach ($dll in $dlls) {
        $path = Join-Path $folder $dll
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $problems.Add("it has no $dll, which its DllPlugins row names")
            continue
        }
        try {
            $api = Get-ExportedApiVersion ([IO.File]::ReadAllBytes($path))
        } catch {
            $problems.Add("$dll could not be read as a 32-bit Windows DLL, which Civilization V needs")
            continue
        }
        if (-not $api) {
            $problems.Add("$dll declares no API version: one of its .cpp files needs the line CIV_PLUGIN_EXPORT_API_VERSION;")
        } elseif ($api -ne $sdkApi) {
            $problems.Add("$dll declares API $api, but this SDK's is $sdkApi")
        }
    }
    return $problems
}

function Get-PackageProblems([string] $package, [int] $modVersion, [bool] $isPlugin, [string] $sdkApi) {
    $unpacked = Join-Path ([IO.Path]::GetTempPath()) ('release-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $unpacked | Out-Null
    try {
        if ((Invoke-Program $tar "-xf `"$package`" -C `"$unpacked`"") -ne 0) {
            return "Windows' tar could not unpack it"
        }
        return (Get-UnpackedModProblems $unpacked $modVersion $isPlugin $sdkApi)
    } finally {
        Remove-Item -LiteralPath $unpacked -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$versionFile = Join-Path $root 'VERSION'
$releases = Join-Path $root 'Releases'
$version = Read-VersionFile $versionFile
$project = Read-Project $root
Assert-NoTemplateLeftovers $project $root
Assert-WorkshopDescription $root $version.Bazaar
if (Test-Released $releases $version.Release) {
    Stop-Release "$($version.Release) is already released, in Releases\$($version.Release). Raise the release in VERSION."
}
Assert-NotBelowReleased $releases $version
$releasedModVersions = @(Get-ReleasedModVersions $releases)
$modVersion = Resolve-ModVersion $version $project $releasedModVersions
$isPlugin = [bool] @(Get-ChildItem -LiteralPath (Join-Path $root 'src') -Filter '*.vcproj' -File -ErrorAction SilentlyContinue).Count
$sdkApi = $null
$header = $null
if ($isPlugin) {
    $sdkApi = Get-SdkApiVersion $root
    Assert-SdkFitsBazaar $sdkApi $version.Bazaar
    $header = Join-Path $root 'src\PluginVersion.h'
    Assert-PluginVersionHeader $root $header
}
if (-not (Test-Path -LiteralPath $tar -PathType Leaf)) {
    Stop-Release "Windows' tar.exe, which checks the package, is not at $tar. It comes with Windows 10 version 1803 and later."
}
$hasChangesSection = Test-ChangesSection $root $version.Release

Write-Versions $version $modVersion $project $versionFile $header
if (-not $releasedModVersions.Count) {
    Write-Output "release: no earlier release is in Releases, so this one is taken as the first, with mod version $modVersion."
}
Write-Output "release: building $($project.Name) $($version.Release), mod version $modVersion"
$package = Invoke-Build $root $modVersion
$problems = @(Get-PackageProblems $package $modVersion $isPlugin $sdkApi)
if ($problems.Count) {
    Stop-Release ("The package was not released, because:`n" + (($problems | ForEach-Object { "  - $_" }) -join "`n") + "`n$rerunNote")
}

$target = Join-Path $releases $version.Release
New-Item -ItemType Directory -Path $target -Force | Out-Null
Copy-Item -LiteralPath $package -Destination $target
$packageName = Split-Path -Leaf $package
Write-Output "release: released $($project.Name) $($version.Release), mod version $modVersion, for Bazaar $($version.Bazaar) or newer:"
Write-Output "  Releases\$($version.Release)\$packageName"
if (-not $hasChangesSection) {
    Write-Output "release: warning: CHANGES.txt has no section for $($version.Release). Add one that starts with the line [b]$($version.Release)[/b] and says what changed, to paste as the Workshop change note."
}
Write-Output 'Upload it with ModBuddy, under Tools > Upload to Steam Workshop. Paste workshop-description.txt as the description, and the section of CHANGES.txt for this release as the change note.'
exit 0
