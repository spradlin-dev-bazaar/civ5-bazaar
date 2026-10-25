# Shared by the skills' scaffold scripts, which dot-source it after setting $ErrorActionPreference = 'Stop'.

$script:madeTarget = $null
$script:reservedNames = @('CON', 'PRN', 'AUX', 'NUL') + (1..9 | ForEach-Object { "COM$_"; "LPT$_" })
$script:buildOutputFolders = @('Build', 'Packages', 'src\out')
$script:buildOutputExtensions = @('.dll', '.pdb', '.obj', '.idb', '.ilk', '.lib', '.exp', '.res', '.civ5mod', '.modinfo', '.user', '.ncb', '.suo')
$script:binaryExtensions = @('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.dds', '.tga', '.zip')
# Latin-1 maps every byte to one character and back, so a round trip changes only the replaced ASCII text.
$script:latin1 = [Text.Encoding]::GetEncoding(28591)

function Fail([string] $message) {
    [Console]::Error.WriteLine($message)
    if ($script:madeTarget -and (Test-Path -LiteralPath $script:madeTarget)) {
        Remove-Item -LiteralPath $script:madeTarget -Recurse -Force
    }
    exit 1
}

# Relative paths count from PowerShell's current folder, which .NET does not follow.
function Resolve-UserPath([string] $path) {
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($path)
}

# Checks the display name, makes the file name from it when none is given, and returns both.
function Get-ScaffoldNames([string] $displayName, [string] $fileName, [string[]] $templateNames) {
    # Names end up in XML, source strings and folder names, and are written byte for byte, so keep them to ASCII that
    # none of those treat specially.
    $displayName = $displayName.Trim()
    if ($displayName -notmatch "^[A-Za-z0-9][A-Za-z0-9 _.,'()-]*$" -or $displayName.EndsWith('.')) {
        Fail "The display name may use only letters, digits, spaces and _ . , ' ( ) -, must start with a letter or digit, and must not end with a dot."
    }
    if (-not $fileName) {
        $fileName = (($displayName -split '[^A-Za-z0-9]+' | Where-Object { $_ }) |
            ForEach-Object { $_.Substring(0, 1).ToUpperInvariant() + $_.Substring(1) }) -join ''
    }
    if ($fileName -notmatch '^[A-Za-z][A-Za-z0-9_-]*$') {
        Fail "The file name '$fileName' must start with a letter and use only letters, digits, _ and -. Pass -FileName."
    }
    foreach ($name in @($displayName, $fileName)) {
        if ($script:reservedNames -contains ($name -split '\.')[0].Trim()) {
            Fail "Windows keeps the name '$name' for a device, so no folder or file can have it. Choose another."
        }
        foreach ($token in $templateNames) {
            if ($name.Contains($token)) {
                Fail "Names may not contain '$token', the template's own name."
            }
        }
    }
    return $displayName, $fileName
}

function Assert-PlainText([string[]] $texts) {
    foreach ($text in $texts) {
        if ($text -and $text -notmatch '^[\x20-\x7E]+$') {
            Fail 'The description and author may use only plain ASCII characters.'
        }
    }
}

function Read-RawText([string] $path) {
    return $script:latin1.GetString([IO.File]::ReadAllBytes($path))
}

function Write-RawText([string] $path, [string] $content) {
    [IO.File]::WriteAllBytes($path, $script:latin1.GetBytes($content))
}

function Set-FirstElement([string] $content, [string] $element, [string] $value, [string] $file) {
    $match = [regex]::Match($content, "<$element>[^<]*</$element>")
    if (-not $match.Success) {
        Fail "No <$element> line in $file."
    }
    $escaped = $value.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;')
    return $content.Substring(0, $match.Index) + "<$element>$escaped</$element>" + $content.Substring($match.Index + $match.Length)
}

function Test-BuildOutput([string] $relative) {
    if ($script:buildOutputExtensions -contains [IO.Path]::GetExtension($relative).ToLowerInvariant()) {
        return $true
    }
    foreach ($folder in $script:buildOutputFolders) {
        if ($relative.StartsWith($folder + '\', [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Rename-Tokens([string] $text, [hashtable] $names) {
    foreach ($token in $names.Keys) {
        $text = $text.Replace($token, $names[$token])
    }
    return $text
}

# Copies the template without its build output, putting the new names in place of the template's in every file name
# and text file. The .civ5proj gets the new mod ID on its one <Guid> line, and each of $projectFields replaces the
# first element of that name; a new Teaser also replaces the template's in workshop-description.txt.
function Copy-Template([string] $template, [string] $target, [hashtable] $names, [string] $guid, [hashtable] $projectFields) {
    $root = [IO.Path]::GetFullPath($template).TrimEnd('\') + '\'
    New-Item -ItemType Directory -Path $target | Out-Null
    $script:madeTarget = $target
    $templateTeaser = $null
    foreach ($file in Get-ChildItem -LiteralPath $root -Recurse -File) {
        $relative = $file.FullName.Substring($root.Length)
        if (Test-BuildOutput $relative) { continue }

        $renamed = Rename-Tokens $relative $names
        $destination = Join-Path $target $renamed
        New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
        if ($script:binaryExtensions -contains $file.Extension.ToLowerInvariant()) {
            Copy-Item -LiteralPath $file.FullName -Destination $destination
            continue
        }

        $content = Rename-Tokens (Read-RawText $file.FullName) $names
        if ($file.Extension -ieq '.civ5proj') {
            $guidLines = [regex]::Matches($content, '<Guid>[^<]*</Guid>').Count
            if ($guidLines -ne 1) {
                Fail "Expected one <Guid> line in $relative, found $guidLines."
            }
            $templateTeaser = [regex]::Match($content, '<Teaser>([^<]*)</Teaser>').Groups[1].Value
            $content = Set-FirstElement $content 'Guid' $guid $relative
            foreach ($element in $projectFields.Keys) {
                $content = Set-FirstElement $content $element $projectFields[$element] $relative
            }
        }
        Write-RawText $destination $content
    }
    $workshop = Join-Path $target 'workshop-description.txt'
    if ($projectFields.Teaser -and $templateTeaser -and (Test-Path -LiteralPath $workshop)) {
        Write-RawText $workshop ((Read-RawText $workshop).Replace($templateTeaser, $projectFields.Teaser))
    }
}
