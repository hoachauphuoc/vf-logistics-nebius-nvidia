$baseUrl = "https://vf-logistics-350828852747.asia-southeast1.run.app"
$data = Get-Content -Raw -Path "$PSScriptRoot\e2e_test_data.json" | ConvertFrom-Json

$results = @()
$i = 0
foreach ($item in $data) {
    $i++
    $label = $item._label
    $expect = $item._expect
    $shipment = $item.PSObject.Copy()
    $shipment.PSObject.Properties.Remove('_label')
    $shipment.PSObject.Properties.Remove('_expect')

    $body = $shipment | ConvertTo-Json -Depth 5
    try {
        $resp = Invoke-RestMethod -Uri "$baseUrl/api/v1/events/shipment" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 60
        $results += [PSCustomObject]@{
            No = $i
            Label = $label
            Expect = $expect
            CaseId = $resp.case_id
            State = $resp.state
            Decision = if ($resp.decision) { $resp.decision.action } else { "" }
        }
        Write-Host "[$i/23] $label -> state=$($resp.state) case_id=$($resp.case_id)"
    } catch {
        $results += [PSCustomObject]@{
            No = $i
            Label = $label
            Expect = $expect
            CaseId = "ERROR"
            State = "ERROR"
            Decision = $_.Exception.Message
        }
        Write-Host "[$i/23] $label -> ERROR: $($_.Exception.Message)"
    }
    Start-Sleep -Milliseconds 300
}

$results | Export-Csv -Path "$PSScriptRoot\e2e_results.csv" -NoTypeInformation
Write-Host "`nDone. Results saved to e2e_results.csv"
$results | Format-Table -AutoSize
