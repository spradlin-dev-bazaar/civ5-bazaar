# Shared by the skills' scaffold scripts, which dot-source it after setting $ErrorActionPreference = 'Stop'.

$script:madeTarget = $null
$script:reservedNames = @('CON', 'PRN', 'AUX', 'NUL') + (1..9 | ForEach-Object { "COM$_"; "LPT$_" })
$script:buildOutputFolders = @('Build', 'Packages', 'src\out')
$script:buildOutputExtensions = @('.dll', '.pdb', '.obj', '.idb', '.ilk', '.lib', '.exp', '.res', '.civ5mod', '.modinfo', '.user', '.ncb', '.suo', '.pyc')
$script:binaryExtensions = @('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.dds', '.tga', '.zip')
# Latin-1 maps every byte to one character and back, so a round trip changes only the replaced ASCII text.
$script:latin1 = [Text.Encoding]::GetEncoding(28591)
$script:utf8Bom = [string] [char] 0xEF + [char] 0xBB + [char] 0xBF

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
    # Names end up in XML, source strings, folder names and MSBuild properties (which split at a comma), and are written
    # byte for byte, so keep them to ASCII that none of those treat specially.
    $displayName = $displayName.Trim()
    if ($displayName -notmatch "^[A-Za-z0-9][A-Za-z0-9 _.'()-]*$" -or $displayName.EndsWith('.')) {
        Fail "The display name may use only letters, digits, spaces and _ . ' ( ) -, must start with a letter or digit, and must not end with a dot."
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

# XmlTextReader starts a new line at CRLF, LF and a lone CR alike.
function Get-TextOffset([string] $text, [int] $line, [int] $column) {
    if ($line -le 1) {
        return $column - 1
    }
    $break = [regex]::Matches($text, "\r\n|\r|\n")[$line - 2]
    return $break.Index + $break.Length + $column - 1
}

# For the first element of each name directly in the project's <PropertyGroup>: where its text starts and ends in $text
# (an empty one gets an empty span before its end tag), and what it says. Also how many <Guid> elements there are.
function Find-ElementTexts([string] $text, [string[]] $names, [string] $file) {
    $found = @{}
    $guids = 0
    $path = @{}
    $open = $null
    $reader = New-Object Xml.XmlTextReader (New-Object IO.StringReader $text)
    $reader.XmlResolver = $null
    try {
        while ($reader.Read()) {
            $type = $reader.NodeType
            if ($type -eq [Xml.XmlNodeType]::Element) {
                $path[$reader.Depth] = $reader.LocalName
                if ($reader.LocalName -ceq 'Guid') {
                    $guids++
                }
                $setting = $reader.Depth -eq 2 -and $path[0] -ceq 'Project' -and $path[1] -ceq 'PropertyGroup'
                if ($setting -and $names -ccontains $reader.LocalName -and -not $found.ContainsKey($reader.LocalName)) {
                    if ($reader.IsEmptyElement) {
                        Fail "$file has <$($reader.LocalName) />, with no room for text: write it as <$($reader.LocalName)></$($reader.LocalName)>."
                    }
                    $open = $reader.LocalName
                }
            } elseif ($open -and ($type -eq [Xml.XmlNodeType]::Text -or $type -eq [Xml.XmlNodeType]::Whitespace)) {
                $start = Get-TextOffset $text $reader.LineNumber $reader.LinePosition
                $found[$open] = @{ Start = $start; End = $text.IndexOf('<', $start); Value = $reader.Value }
                $open = $null
            } elseif ($open -and $type -eq [Xml.XmlNodeType]::EndElement) {
                # The reader points at the end tag's name, two characters after its '<'.
                $end = (Get-TextOffset $text $reader.LineNumber $reader.LinePosition) - 2
                $found[$open] = @{ Start = $end; End = $end; Value = '' }
                $open = $null
            }
        }
    } catch [Xml.XmlException] {
        Fail "$file is not valid XML: $($_.Exception.Message)"
    } finally {
        $reader.Close()
    }
    return @{ Texts = $found; Guids = $guids }
}

# Changes only the text of each element named in $values, found with an XML reader as the templates' release.ps1 does,
# so every other byte, a byte order mark included, stays as the template has it. Returns the new content and the
# template's teaser.
function Set-ProjectFields([string] $raw, [hashtable] $values, [string] $file) {
    $bom = if ($raw.StartsWith($script:utf8Bom)) { $script:utf8Bom } else { '' }
    $text = $raw.Substring($bom.Length)
    $result = Find-ElementTexts $text @($values.Keys) $file
    if ($result.Guids -ne 1) {
        Fail "Expected one <Guid> in $file, found $($result.Guids)."
    }
    foreach ($name in $values.Keys) {
        if (-not $result.Texts.ContainsKey($name)) {
            Fail "No <$name> in the <PropertyGroup> of $file."
        }
    }
    foreach ($name in @($values.Keys | Sort-Object { $result.Texts[$_].Start } -Descending)) {
        $span = $result.Texts[$name]
        $escaped = $values[$name].Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;')
        $text = $text.Substring(0, $span.Start) + $escaped + $text.Substring($span.End)
    }
    return @{ Content = $bom + $text; Teaser = ([string] $result.Texts['Teaser'].Value).Trim() }
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
# and text file. The .civ5proj gets the new mod ID in its one <Guid>, and each of $projectFields replaces the first
# element of that name; a new Teaser also replaces the template's in workshop-description.txt.
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
            $project = Set-ProjectFields $content (@{ Guid = $guid } + $projectFields) $relative
            $content = $project.Content
            $templateTeaser = $project.Teaser
        }
        Write-RawText $destination $content
    }
    $workshop = Join-Path $target 'workshop-description.txt'
    if ($projectFields.Teaser -and $templateTeaser -and (Test-Path -LiteralPath $workshop)) {
        Write-RawText $workshop ((Read-RawText $workshop).Replace($templateTeaser, $projectFields.Teaser))
    }
}
