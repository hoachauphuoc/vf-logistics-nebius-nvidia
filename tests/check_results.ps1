$baseUrl = "https://vf-logistics-350828852747.asia-southeast1.run.app"
$data = Get-Content -Raw "C:\Users\phuochoa\vf-logistics-nebius-nvidia\tests\e2e_test_data.json" | ConvertFrom-Json

$results = @()
foreach ($item in $data) {
    $caseId = "CASE-" + $item.shipment_id
    try {
        $c = Invoke-RestMethod -Uri "$baseUrl/api/v1/orchestrator/case/$caseId" -Method Get -TimeoutSec 30
        $clearedBy = $c.cleared_by
        $decision = if ($c.decision) { $c.decision.outcome } else { "" }
        $results += [PSCustomObject]@{
            Label = $item._label
            Expect = $item._expect
            CaseId = $caseId
            State = $c.state
            RiskScore = $c.risk_score
            ClearedBy = $clearedBy
            DecisionOutcome = $decision
        }
    } catch {
        $results += [PSCustomObject]@{
            Label = $item._label
            Expect = $item._expect
            CaseId = $caseId
            State = "FETCH_ERROR"
            RiskScore = ""
            ClearedBy = ""
            DecisionOutcome = $_.Exception.Message
        }
    }
}
$results | Export-Csv -Path "C:\Users\phuochoa\vf-logistics-nebius-nvidia\tests\e2e_final_results.csv" -NoTypeInformation
$results | Format-Table -AutoSize -Wrap
