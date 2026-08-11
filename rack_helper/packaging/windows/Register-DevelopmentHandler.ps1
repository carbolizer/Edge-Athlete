[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonwPath,
    [Parameter(Mandatory = $true)]
    [string]$EntryScriptPath
)

$ErrorActionPreference = 'Stop'
$pythonw = (Resolve-Path -LiteralPath $PythonwPath).Path
$entryScript = (Resolve-Path -LiteralPath $EntryScriptPath).Path
if (-not [System.IO.Path]::IsPathFullyQualified($pythonw) -or
    -not [System.IO.Path]::IsPathFullyQualified($entryScript)) {
    throw 'Both paths must be absolute.'
}
if ([System.IO.Path]::GetFileName($pythonw) -ne 'pythonw.exe') {
    throw 'PythonwPath must name pythonw.exe.'
}
$controlCharacters = [char[]](0..31)
if ($pythonw.Contains('"') -or $entryScript.Contains('"') -or
    $pythonw.Contains('%') -or $entryScript.Contains('%') -or
    $pythonw.IndexOfAny($controlCharacters) -ge 0 -or
    $entryScript.IndexOfAny($controlCharacters) -ge 0) {
    throw 'Paths containing quote, percent, or control characters are unsupported.'
}

$schemeKey = 'HKCU:\Software\Classes\edgeathlete-rack'
$commandKey = Join-Path $schemeKey 'shell\open\command'
New-Item -Path $commandKey -Force | Out-Null
Set-Item -LiteralPath $schemeKey -Value 'URL:Edge Athlete Rack Helper Development Protocol'
New-ItemProperty -LiteralPath $schemeKey -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
$command = '"{0}" "{1}" "%1"' -f $pythonw, $entryScript
Set-Item -LiteralPath $commandKey -Value $command
Write-Output "Registered development handler in $schemeKey"
