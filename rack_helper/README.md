# Edge Athlete Rack Helper - Unsigned Development Build

This CPython 3.12 helper proves only OS-keyring identity, helper pairing and
activation, exact protocol launch consumption, and `no_sensor` status. It contains
no BLE calls, rep ingestion, MQTT, local listener, shell execution, update path, or
production installer. Do not distribute it to customers.

The process holds one user-local file lock for its full lifetime. A second launch
does not hand off arguments or open a listener; it exits with code 4 and the stable
error `single_instance_active`.

The application origin is fixed at build time in
`src/edgeathlete_rack_helper/config.py` as `https://edgeathlete.online`. Runtime
arguments, environment variables, and files cannot change it.

## Linux development

Secret Service must be available and unlocked. Plaintext, chained, and fallback
keyring backends are rejected.

```bash
cd rack_helper
python3.12 -m venv .venv
.venv/bin/python -m pip install pip==25.3 pip-tools==7.6.0
PYTHON=.venv/bin/python scripts/generate-linux-lock.sh
PYTHON=.venv/bin/python scripts/build-linux-development.sh
PYTHONPATH=src .venv/bin/python -m edgeathlete_rack_helper
PYTHONPATH=src .venv/bin/python -m edgeathlete_rack_helper edgeathlete-rack:launch
```

Register the source development handler. The generated `Exec` has the quoted
interpreter, quoted entry script, and one final `%u`; it uses no shell wrapper.

```bash
packaging/linux/register-development-handler.sh \
  "$PWD/.venv/bin/python" "$PWD/entrypoint.py"
```

## Windows x64 development

Run these commands from a CPython 3.12 x64 PowerShell session. Windows Credential
Locker must be available.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pip==25.3 pip-tools==7.6.0
.\packaging\windows\Generate-DependencyLock.ps1 -Python "$PWD\.venv\Scripts\python.exe"
.\packaging\windows\Build-Development.ps1 -Python "$PWD\.venv\Scripts\python.exe"
$env:PYTHONPATH = 'src'
.\.venv\Scripts\pythonw.exe -m edgeathlete_rack_helper
.\packaging\windows\Register-DevelopmentHandler.ps1 `
  -PythonwPath "$PWD\.venv\Scripts\pythonw.exe" `
  -EntryScriptPath "$PWD\entrypoint.py"
```

The PowerShell registration writes only
`HKCU\Software\Classes\edgeathlete-rack`. Its command quotes `pythonw.exe`, the
entry script, and exactly one final `"%1"`; it invokes no shell.

## Manual checks

1. Start without an argument and verify the UI stays inert with no network access.
2. Enter the Rack-displayed pairing code, compare all six words, and have a coach
   confirm before selecting **Check coach confirmation**.
3. Create a Rack launch intent and invoke exactly `edgeathlete-rack:launch`; verify
   the helper shows `no_sensor` only after consume.
4. Close and restart manually; verify no consume or heartbeat occurs.
5. Select **Disconnect and quit** and verify the process exits. There is no BLE
   connection to release in this development slice.
6. While one helper is open, launch it again and verify the second process shows
   `single_instance_active`, exits with code 4, and the first process is unchanged.

Both platform build scripts install only hash-locked dependencies, run unit tests,
audit dependencies, build the development-labeled one-folder bundle, and emit a
CycloneDX SBOM under `dist/`. The registration scripts are user-scoped development
handlers (`NoDisplay=true` on Linux and `HKCU` on Windows), not production catalog
or machine-wide installers.
