[CmdletBinding()]
param([string]$Python = 'py')

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
    -not [Environment]::Is64BitOperatingSystem) {
    throw 'Windows x64 is required for this development build.'
}
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$arguments = @()
if ($Python -eq 'py') { $arguments += '-3.12' }
function Invoke-Python {
    & $Python @arguments @args
    if ($LASTEXITCODE -ne 0) { throw "Python command failed: $args" }
}
$pythonPlatform = & $Python @arguments -c 'import struct,sys; print(f"{sys.version_info.major}.{sys.version_info.minor}:{struct.calcsize(chr(80)) * 8}")'
if ($LASTEXITCODE -ne 0 -or $pythonPlatform.Trim() -ne '3.12:64') {
    throw 'A 64-bit CPython 3.12 interpreter is required.'
}
Invoke-Python -m pip install --require-virtualenv --require-hashes -r (Join-Path $root 'requirements-windows-x64.lock')
Invoke-Python -m pip install --require-virtualenv --no-deps --no-build-isolation $root
Invoke-Python -m pip check
Invoke-Python -m unittest discover -s (Join-Path $root 'tests') -v
Invoke-Python -m pip_audit --require-hashes -r (Join-Path $root 'requirements-windows-x64.lock')
Push-Location $root
try { Invoke-Python -m PyInstaller --clean --noconfirm EdgeAthleteRackHelperDevelopment.spec }
finally { Pop-Location }
Invoke-Python -m cyclonedx_py requirements (Join-Path $root 'requirements-windows-x64.lock') `
    --output-file (Join-Path $root 'dist\EdgeAthleteRackHelperDevelopment.cdx.json')
