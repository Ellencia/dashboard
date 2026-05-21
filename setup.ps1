# Project Dashboard - one-time setup for a new work folder.
#   1) sets config.json "root" to the work folder
#   2) places the 4 AI instruction files at the work folder root
#   3) installs pystray / pillow (for tray mode)
# Console messages are kept ASCII on purpose (avoids PS 5.1 encoding issues).
$ErrorActionPreference = "Stop"

$dash = $PSScriptRoot                       # dashboard folder (this script's folder)
$work = Split-Path $dash -Parent            # work folder = dashboard's parent
$workFwd = $work -replace '\\', '/'

Write-Host ""
Write-Host "=== Project Dashboard setup ==="
Write-Host "Dashboard folder : $dash"
Write-Host "Work folder      : $work"
Write-Host ""

# 1) config.json: set 'root' to the work folder
$cfgPath = Join-Path $dash "config.json"
$txt = Get-Content $cfgPath -Raw -Encoding UTF8
$txt = $txt -replace '"root"\s*:\s*"[^"]*"', ('"root": "' + $workFwd + '"')
[IO.File]::WriteAllText($cfgPath, $txt, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[1/3] config.json root -> $workFwd"

# 2) place AI instruction files at the work folder root (keep any existing ones)
$tpl = Join-Path $dash "workspace_templates"
foreach ($f in @("01_code.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md")) {
    $dest = Join-Path $work $f
    if (Test-Path $dest) {
        Write-Host "      kept (already exists): $f"
    }
    else {
        Copy-Item (Join-Path $tpl $f) $dest
        Write-Host "      created: $f"
    }
}
Write-Host "[2/3] AI instruction files ready"

# 3) install packages for tray mode (widget mode works without them)
Write-Host "[3/3] installing pystray, pillow ..."
try {
    python -m pip install --quiet --disable-pip-version-check pystray pillow
    if ($LASTEXITCODE -eq 0) {
        Write-Host "      done (or already installed)"
    }
    else {
        Write-Host "      pip error - for tray mode retry: python -m pip install pystray pillow"
    }
}
catch {
    Write-Host "      python not found - for tray mode install: python -m pip install pystray pillow"
}

Write-Host ""
Write-Host "=== Setup complete ==="
Write-Host "Run the widget with  run.bat"
Write-Host "Auto-start on boot:  install_autostart.bat"
