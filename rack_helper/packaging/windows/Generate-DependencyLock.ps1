[CmdletBinding()]
param([string]$Python = 'py')

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    -not [Environment]::Is64BitOperatingSystem) {
    throw 'Windows x64 is required to generate this platform lock.'
}
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pythonArguments = @()
if ($Python -eq 'py') { $pythonArguments += '-3.12' }
$pythonPlatform = & $Python @pythonArguments -c 'import struct,sys; print(f"{sys.version_info.major}.{sys.version_info.minor}:{struct.calcsize(chr(80)) * 8}")'
if ($LASTEXITCODE -ne 0 -or $pythonPlatform.Trim() -ne '3.12:64') {
    throw 'A 64-bit CPython 3.12 interpreter is required.'
}
Push-Location $root
try {
    & $Python @pythonArguments -m piptools compile --allow-unsafe --generate-hashes --resolver=backtracking --strip-extras --upgrade `
        --output-file requirements-windows-x64.lock requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Windows dependency lock generation failed.' }
} finally {
    Pop-Location
}
