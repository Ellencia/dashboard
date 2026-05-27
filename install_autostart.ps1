# Project Dashboard - register auto-start at Windows logon.
# Console messages are kept ASCII on purpose (avoids PS 5.1 encoding issues).
$ErrorActionPreference = 'Stop'
$dash = $PSScriptRoot
$main = Join-Path $dash 'main.py'

Write-Host ""
Write-Host "=== Project Dashboard - install auto-start ==="

if (-not (Test-Path $main)) {
    Write-Host ("ERROR: main.py not found at " + $main)
    return
}

# Read config to see whether tray mode is used (needs pystray/pillow).
$cfg = Join-Path $dash 'config.json'
$needTray = $true
if (Test-Path $cfg) {
    try {
        $j = Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($j.display_mode -and $j.display_mode -ne 'tray') { $needTray = $false }
    } catch { }
}

# Test whether a pythonw can actually run the dashboard with its deps.
# pythonw.exe is a GUI subsystem app that doesn't return an exit code to the
# shell, so test the matching python.exe (same Scripts folder = same packages).
function Test-Pythonw([string]$exe, [bool]$needTray) {
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    $py = $exe -replace 'pythonw\.exe$', 'python.exe'
    if (-not (Test-Path $py)) { $py = $exe }
    $imports = if ($needTray) { 'import tkinter, pystray, PIL' } else { 'import tkinter' }
    & $py -c $imports 1>$null 2>$null
    return ($LASTEXITCODE -eq 0)
}

# Build candidate list in priority order:
#   1) currently-running dashboard's pythonw (most reliable — proven to work)
#   2) any *\Scripts\pythonw.exe found within 3 levels of dashboard / workspace
#   3) pythonw from PATH
$cands = New-Object System.Collections.Generic.List[string]

# 1) Running dashboard?
try {
    $running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*main.py*' } |
        Select-Object -First 1
    if ($running -and $running.ExecutablePath) {
        $cands.Add($running.ExecutablePath) | Out-Null
    }
} catch { }

# 2) Recursive venv search (depth 3) — covers nested layouts like PPS\pps_venv
$work = Split-Path $dash -Parent
$ws2  = if ($work) { Split-Path $work -Parent } else { $null }
function Find-Pythonws([string]$base, [int]$maxDepth) {
    if (-not $base -or -not (Test-Path $base)) { return @() }
    $found = @()
    function Walk([string]$dir, [int]$depth) {
        if ($depth -gt $maxDepth) { return }
        $hit = Join-Path $dir 'Scripts\pythonw.exe'
        if (Test-Path $hit) { $script:found += $hit; return }   # stop descending
        try { $kids = Get-ChildItem $dir -Directory -ErrorAction Stop } catch { return }
        foreach ($k in $kids) {
            $n = $k.Name
            if ($n.StartsWith('.') -or $n -eq 'node_modules' -or $n -eq '__pycache__') { continue }
            Walk $k.FullName ($depth + 1)
        }
    }
    $script:found = @()
    Walk $base 0
    return $script:found
}
foreach ($base in @($dash, $work, $ws2)) {
    foreach ($p in (Find-Pythonws $base 3)) { $cands.Add($p) | Out-Null }
}

# 3) pythonw from PATH
$onPath = Get-Command pythonw -ErrorAction SilentlyContinue
if ($onPath) { $cands.Add($onPath.Source) | Out-Null }

# De-dup while preserving order
$seen = @{}
$cands = @($cands | Where-Object { if ($seen.ContainsKey($_)) { $false } else { $seen[$_] = $true; $true } })

# Pick the first one that can import the required deps.
$pythonw = $null
foreach ($c in $cands) {
    if (Test-Pythonw $c $needTray) { $pythonw = $c; break }
}

if (-not $pythonw) {
    Write-Host ""
    Write-Host "ERROR: No working pythonw found."
    if ($needTray) {
        Write-Host "Tray mode needs pystray and pillow. Run setup.bat first, or:"
        Write-Host "    python -m pip install pystray pillow"
    } else {
        Write-Host "pythonw not found on PATH. Install Python (with tcl/tk) first."
    }
    return
}

# Create the Startup-folder shortcut.
$ws = New-Object -ComObject WScript.Shell
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'ProjectDashboard.lnk'
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = $pythonw
$sc.Arguments = '"' + $main + '"'
$sc.WorkingDirectory = $dash
$sc.Save()

Write-Host ""
Write-Host ("pythonw       : " + $pythonw)
Write-Host ("Registered    : " + $lnk)
Write-Host ""
Write-Host "Done. The dashboard will auto-start at next Windows logon."
Write-Host "(If it's already running, the next launch just pops up the existing window.)"
