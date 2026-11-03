param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$ConfirmFreeTierProject,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
if (-not $ConfirmFreeTierProject) {
    throw 'Use -ConfirmFreeTierProject only for the approved Free Tier project with no billing.'
}
$geminiRepoRoot = Split-Path -Parent $PSScriptRoot
$geminiBackendRoot = Join-Path $geminiRepoRoot 'backend'
$geminiPython = Join-Path $geminiBackendRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $geminiPython)) {
    throw 'Install the locked backend environment before starting Gemini.'
}
$geminiOriginalLocation = Get-Location
try {
    Set-Location -LiteralPath $geminiBackendRoot
    # Python owns private credential loading and scoped activation. This wrapper
    # never changes the parent's environment or prints a credential.
    $geminiArguments = @('-B', '-m', 'scripts.run_gemini', '--confirm-free-tier-project', '--port', "$Port")
    if ($Check) { $geminiArguments += '--check' }
    & $geminiPython @geminiArguments
    if ($LASTEXITCODE -ne 0) { throw 'Backend startup failed; inspect sanitized configuration errors.' }
}
finally {
    Set-Location -LiteralPath $geminiOriginalLocation
}
