# Pult: install or update on this computer (Windows). Safe to re-run. In PowerShell, in the Pult folder:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Code -> ~\.local\share\pult\ (PULT_HOME), a Python environment with the Agent SDK, the `pult` command in ~\.local\bin
# (added to the user's PATH), a Task Scheduler task that starts Pult at logon. Then `pult install` takes over: in a
# terminal it starts the setup if Pult isn't set up yet.
# Python 3.10+ is looked for with the py launcher and in PATH (not the Microsoft Store one); PULT_PYTHON picks one.
# This file is UTF-8 with a BOM: Windows PowerShell 5.1 reads a file without one in the system's code page.
$ErrorActionPreference = 'Stop'

$Src = $PSScriptRoot
$Dst = if ($env:PULT_HOME) { $env:PULT_HOME } else { Join-Path $HOME '.local\share\pult' }
$Bin = Join-Path $HOME '.local\bin'
$IsRu = (Get-UICulture).TwoLetterISOLanguageName -eq 'ru'

# PowerShell names ignore case: the parameters must not be called $en and $ru next to a global $Ru
function Say($textEn, $textRu) { if ($IsRu) { Write-Host $textRu } else { Write-Host $textEn } }

function Good($py, $pre) {
    # Python 3.10 to 3.x, real (not the Microsoft Store stub, which runs sandboxed and redirects AppData)
    try {
        # no double quotes inside: Windows PowerShell 5.1 passes them to programs unescaped
        $exe = & $py @pre -c 'import sys; v = sys.version_info[:2]; print(sys.executable if (3, 10) <= v < (4, 0) else str())' 2>$null
    } catch { return $null }
    if ($LASTEXITCODE -ne 0 -or -not $exe) { return $null }
    $exe = "$exe".Trim()
    if ($exe -like '*\WindowsApps\*') { return $null }
    return $exe
}

function Find-Python {
    if ($env:PULT_PYTHON) { return (Good $env:PULT_PYTHON @()) }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        # 3.12 first: every dependency has ready-made wheels for it
        foreach ($v in '3.12', '3.13', '3.11', '3.10', '3.14') {
            $p = Good 'py' @("-$v")
            if ($p) { return $p }
        }
    }
    foreach ($name in 'python', 'python3') {
        if (Get-Command $name -ErrorAction SilentlyContinue) {
            $p = Good $name @()
            if ($p) { return $p }
        }
    }
    return $null
}

New-Item -ItemType Directory -Force -Path $Dst | Out-Null
$VenvPy = Join-Path $Dst 'venv\Scripts\python.exe'

if (-not (Good $VenvPy @())) {
    $Py = Find-Python
    if (-not $Py) {
        Say 'Pult needs Python 3.10 or newer from python.org (not the Microsoft Store one): winget install Python.Python.3.12 - then run install.ps1 again.' `
            'Пульту нужен Python 3.10 или новее с python.org (не из Microsoft Store): winget install Python.Python.3.12 — и снова install.ps1.'
        exit 1
    }
    $venv = Join-Path $Dst 'venv'
    if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }   # left over from a Python that is gone
    Say "Python: $Py" "Python: $Py"
    & $Py -m venv $venv
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

# Updating restarts the service, and that cuts off what Pult's own sessions are doing - a turn, a background task or
# subagent. In a console `pult install` asks before the restart; without one (a script, an agent) nothing is changed
# while they run. $env:PULT_FORCE = '1' - anyway.
if ([Console]::IsInputRedirected -and $env:PULT_FORCE -ne '1' -and (Test-Path (Join-Path $Dst 'pultd.py'))) {
    $busy = & $VenvPy -X utf8 (Join-Path $Src 'src\pultctl.py') busy
    if ($LASTEXITCODE -ne 0) {
        $busy | ForEach-Object { Write-Host $_ }
        Say "Nothing changed. Wait until they finish (pult busy shows what is left), or anyway: `$env:PULT_FORCE = '1' before install.ps1" `
            "Ничего не менял. Подожди, пока закончат (pult busy покажет, что осталось), или всё равно: `$env:PULT_FORCE = '1' перед install.ps1"
        exit 1
    }
}

# the same files install.sh copies (tests/test_setup.py checks both lists)
$files = 'src/pultd.py', 'src/pult_hook.py', 'src/pult_render.py', 'src/pult_web.py', 'src/pult_i18n.py', 'src/pult_stt.py',
         'src/pult_load.py', 'src/pult_new.py', 'src/pult_files.py', 'src/pult_spend.py', 'src/pult_attn.py', 'src/pult_brief.py', 'src/pult_os.py', 'src/pult_setup.py', 'src/pult_update.py', 'src/pultctl.py',
         'src/pult_tab.py', 'requirements.txt'
foreach ($f in $files) { Copy-Item -Force (Join-Path $Src $f) $Dst }

Say 'Installing dependencies...' 'Ставлю зависимости…'
& $VenvPy -m pip install -q --disable-pip-version-check -r (Join-Path $Dst 'requirements.txt')
if ($LASTEXITCODE -ne 0) { exit 1 }

# the pult command: ~\.local\bin in the user's PATH (Claude Code's own installer puts claude.exe there too). The
# registry value keeps its kind and its %VARIABLES%; a variable set and unset tells new windows the PATH changed.
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
$key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
$raw = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
$have = ($raw -split ';') | ForEach-Object { [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\') }
if (-not ($have -contains $Bin.TrimEnd('\'))) {
    $key.SetValue('Path', ((@($raw.TrimEnd(';'), $Bin) | Where-Object { $_ }) -join ';'),
                  [Microsoft.Win32.RegistryValueKind]::ExpandString)
    [Environment]::SetEnvironmentVariable('PULT_INSTALLING', '1', 'User')
    [Environment]::SetEnvironmentVariable('PULT_INSTALLING', $null, 'User')
    Say "Added $Bin to your PATH: new terminal windows will find the pult command." `
        "$Bin добавлен в PATH: в новых окнах терминала будет команда pult."
}
$key.Close()
$env:Path = "$Bin;$env:Path"

$env:PULT_SRC = $Src          # where the files came from: kept with the install history
& $VenvPy -X utf8 (Join-Path $Dst 'pultctl.py') install
exit $LASTEXITCODE
