## E2E Result Verification Script
## Compares actual final states against expected outcomes
## Usage: powershell tests/verify_e2e.ps1

$dataFile = "$PSScriptRoot\e2e_test_data.json"
$resultsFile = "$PSScriptRoot\e2e_final_results.csv"
$outputFile = "$PSScriptRoot\evidence\e2e_pass_fail.csv"

if (-not (Test-Path $resultsFile)) {
    Write-Host "ERROR: $resultsFile not found. Run check_results.ps1 first." -ForegroundColor Red
    exit 1
}

$expected = Get-Content -Raw $dataFile | ConvertFrom-Json
$actual = Import-Csv $resultsFile

$results = @()
$pass = 0; $fail = 0

foreach ($exp in $expected) {
    $label = $exp._label
    $expect = $exp._expect
    $caseId = "CASE-" + $exp.shipment_id
    $row = $actual | Where-Object { $_.CaseId -eq $caseId }

    if (-not $row) {
        $results += [PSCustomObject]@{
            Label = $label; Expected = $expect; Actual = "NOT_FOUND"
            State = ""; RiskScore = ""; ClearedBy = ""; Pass = "FAIL"
        }
        $fail++; continue
    }

    $state = $row.State
    $clearedBy = $row.ClearedBy
    $actualOutcome = switch ($expect) {
        "auto_clear_rules" { if ($state -eq "AUTO_CLEARED" -and $clearedBy -eq "rules") { "auto_clear_rules" } else { "$state/$clearedBy" } }
        "auto_reject_rules" { if ($state -eq "ESCALATED" -and $clearedBy -eq "rules") { "auto_reject_rules" } else { "$state/$clearedBy" } }
        "grey_area_ai" { if ($state -in @("AUTO_CLEARED", "HELD_FOR_REVIEW", "ESCALATED", "PENDING_HUMAN") -and $clearedBy -ne "rules") { "grey_area_ai" } else { "$state/$clearedBy" } }
        "human_review" { if ($state -in @("ESCALATED", "PENDING_HUMAN", "HELD_FOR_REVIEW")) { "human_review" } else { "$state/$clearedBy" } }
        "human_review_nonwaivable" { if ($state -in @("ESCALATED", "PENDING_HUMAN")) { "human_review_nonwaivable" } else { "$state/$clearedBy" } }
        default { "$state/$clearedBy" }
    }

    $ok = ($actualOutcome -eq $expect)
    $status = if ($ok) { "PASS" } else { "FAIL" }
    if ($ok) { $pass++ } else { $fail++ }

    $results += [PSCustomObject]@{
        Label = $label; Expected = $expect; Actual = $actualOutcome
        State = $state; RiskScore = $row.RiskScore; ClearedBy = $clearedBy; Pass = $status
    }
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host "[$status] $label  expected=$expect  actual=$actualOutcome  state=$state" -ForegroundColor $color
}

Write-Host "`n=== E2E Results: $pass PASS, $fail FAIL out of $($results.Count) ===" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })
$results | Export-Csv -Path $outputFile -NoTypeInformation
Write-Host "Saved to $outputFile"
exit $fail
