## Unified Test Runner -- VF Logistics
## Runs all test phases in sequence with evidence collection
## Usage: powershell tests/run_all_tests.ps1 [-SkipExternal] [-SkipE2E]

param(
    [switch]$SkipExternal,
    [switch]$SkipE2E,
    [string]$BaseUrl = "https://vf-logistics-f7rcctz26a-as.a.run.app"
)

$root = Split-Path $PSScriptRoot -Parent
$evidenceDir = "$PSScriptRoot\evidence"
if (-not (Test-Path $evidenceDir)) { New-Item -ItemType Directory -Force $evidenceDir | Out-Null }

$totalPass = 0; $totalFail = 0

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  VF Logistics -- Full Test Suite" -ForegroundColor Cyan
Write-Host "============================================`n"

# -- Phase 1: Unit + Integration Tests (pytest) --
Write-Host "--- Phase 1: Unit + Integration Tests ---" -ForegroundColor Yellow
Push-Location $root
python -m pytest tests/ -v --tb=short --junitxml="$evidenceDir\pytest-results.xml" 2>&1 | Tee-Object -Variable pytestOutput
$pytestExit = $LASTEXITCODE
Pop-Location

$pytestPassed = ($pytestOutput | Select-String "(\d+) passed" | ForEach-Object { $_.Matches[0].Groups[1].Value })
$pytestFailed = ($pytestOutput | Select-String "(\d+) failed" | ForEach-Object { $_.Matches[0].Groups[1].Value })
if (-not $pytestFailed) { $pytestFailed = 0 }
$totalPass += [int]$pytestPassed; $totalFail += [int]$pytestFailed
Write-Host "`nPhase 1: $pytestPassed passed, $pytestFailed failed`n"

# -- Phase 2: External API Tests --
if (-not $SkipExternal) {
    Write-Host "--- Phase 2: External API Tests ---" -ForegroundColor Yellow
    powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\test_external_api.ps1" -BaseUrl $BaseUrl
    $apiResults = Import-Csv "$evidenceDir\external-api-results.csv"
    $apiPass = ($apiResults | Where-Object { $_.Status -eq "PASS" }).Count
    $apiFail = ($apiResults | Where-Object { $_.Status -eq "FAIL" }).Count
    $totalPass += $apiPass; $totalFail += $apiFail
    Write-Host "`nPhase 2: $apiPass passed, $apiFail failed`n"
} else {
    Write-Host "--- Phase 2: SKIPPED (External API) ---`n" -ForegroundColor DarkGray
}

# -- Phase 3: E2E Regression --
if (-not $SkipE2E) {
    Write-Host "--- Phase 3: E2E Regression (23 scenarios) ---" -ForegroundColor Yellow
    Write-Host "Step 3a: Injecting test shipments..."
    powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\run_e2e.ps1"
    Write-Host "Step 3b: Waiting 90s for pipeline processing..."
    Start-Sleep 90
    Write-Host "Step 3c: Checking final states..."
    powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\check_results.ps1"
    Write-Host "Step 3d: Verifying against expectations..."
    powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\verify_e2e.ps1"
    if (Test-Path "$evidenceDir\e2e_pass_fail.csv") {
        $e2eResults = Import-Csv "$evidenceDir\e2e_pass_fail.csv"
        $e2ePass = ($e2eResults | Where-Object { $_.Pass -eq "PASS" }).Count
        $e2eFail = ($e2eResults | Where-Object { $_.Pass -eq "FAIL" }).Count
        $totalPass += $e2ePass; $totalFail += $e2eFail
        Write-Host "`nPhase 3: $e2ePass passed, $e2eFail failed`n"
    }
} else {
    Write-Host "--- Phase 3: SKIPPED (E2E) ---`n" -ForegroundColor DarkGray
}

# -- Summary --
Write-Host "============================================" -ForegroundColor Cyan
$color = if ($totalFail -eq 0) { "Green" } else { "Red" }
Write-Host "  TOTAL: $totalPass PASS, $totalFail FAIL" -ForegroundColor $color
Write-Host "============================================"
Write-Host "`nEvidence directory: $evidenceDir"
Write-Host "  - pytest-results.xml (JUnit XML)"
Write-Host "  - external-api-results.csv"
Write-Host "  - e2e_pass_fail.csv"
Write-Host "  - production-headers.txt"

exit $totalFail
