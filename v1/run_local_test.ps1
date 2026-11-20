$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$gameScript = Join-Path $PSScriptRoot "main.py"
$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Python was not found. Create the project .venv or add Python to PATH."
    }
    $pythonPath = $pythonCommand.Source
}

$shellCommand = Get-Command powershell.exe -ErrorAction SilentlyContinue
if ($null -eq $shellCommand) {
    $shellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
}
if ($null -eq $shellCommand) {
    throw "PowerShell was not found; it is required to open the two local clients."
}

function ConvertTo-PowerShellLiteral([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

foreach ($player in 1, 2) {
    $sessionPath = Join-Path $env:TEMP "mathships-player$player-session.bin"
    $command = "`$env:ARCADE_SESSION_FILE = $(ConvertTo-PowerShellLiteral $sessionPath); " +
        "Set-Location -LiteralPath $(ConvertTo-PowerShellLiteral $repositoryRoot); " +
        "& $(ConvertTo-PowerShellLiteral $pythonPath) $(ConvertTo-PowerShellLiteral $gameScript)"
    $encodedCommand = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($command)
    )
    Start-Process `
        -FilePath $shellCommand.Source `
        -ArgumentList @("-NoExit", "-EncodedCommand", $encodedCommand)
}
