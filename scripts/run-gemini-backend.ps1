param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000,
    [switch]$ConfirmFreeTierProject
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
$geminiLaunchConfig = @{
    TRACE_LLM_MODE = 'gemini_free'
    TRACE_LLM_PROVIDER_ID = 'gemini'
    TRACE_LLM_GENERATION_MODEL_ID = 'gemini-3.5-flash-lite'
    TRACE_LLM_CONVERSATIONAL_MODEL_ID = 'gemini-3.5-flash-lite'
    TRACE_LLM_CREDENTIAL_ENV_VAR = 'GEMINI_API_KEY'
    TRACE_LLM_FREE_TIER_PROJECT_CONFIRMED = 'true'
    TRACE_LLM_SPEND_LIMIT_MICROUSD = '0'
    TRACE_LLM_MAX_COST_PER_ATTEMPT_MICROUSD = '0'
    TRACE_LLM_MAX_RETRIES = '0'
    TRACE_LLM_MAX_LIVE_REQUESTS_PER_PROCESS = '20'
}
$geminiPrevious = @{}
$geminiOriginalLocation = Get-Location
try {
    foreach ($geminiName in $geminiLaunchConfig.Keys) {
        $geminiPrevious[$geminiName] = [Environment]::GetEnvironmentVariable($geminiName, 'Process')
        [Environment]::SetEnvironmentVariable($geminiName, $geminiLaunchConfig[$geminiName], 'Process')
    }
    $geminiPrevious['GEMINI_API_KEY'] = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'Process')
    if ([string]::IsNullOrWhiteSpace($geminiPrevious['GEMINI_API_KEY'])) {
        $geminiUserKey = [Environment]::GetEnvironmentVariable('GEMINI_API_KEY', 'User')
        if (-not [string]::IsNullOrWhiteSpace($geminiUserKey)) {
            [Environment]::SetEnvironmentVariable('GEMINI_API_KEY', $geminiUserKey, 'Process')
        }
        $geminiUserKey = $null
    }
    Set-Location -LiteralPath $geminiBackendRoot
    # Explicit opt-in to the approved unbilled-project pilot. No migrations or seed writes.
    & $geminiPython -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port --no-access-log
    if ($LASTEXITCODE -ne 0) { throw 'Backend startup failed; inspect sanitized configuration errors.' }
}
finally {
    foreach ($geminiName in $geminiPrevious.Keys) {
        [Environment]::SetEnvironmentVariable($geminiName, $geminiPrevious[$geminiName], 'Process')
    }
    Set-Location -LiteralPath $geminiOriginalLocation
}
