## External API Test Script
## Tests live production endpoints with evidence collection
## Usage: powershell tests/test_external_api.ps1

param(
    [string]$BaseUrl = "https://vf-logistics-f7rcctz26a-as.a.run.app"
)

$evidenceDir = "$PSScriptRoot\evidence"
if (-not (Test-Path $evidenceDir)) { New-Item -ItemType Directory -Force $evidenceDir | Out-Null }

$results = @()
$pass = 0; $fail = 0

function Test-Endpoint {
    param([string]$Name, [string]$Method, [string]$Path, [string]$Body,
          [int]$ExpectedStatus, [string]$ContainsKey, [hashtable]$Headers)
    $url = "$BaseUrl$Path"
    try {
        $params = @{ Uri = $url; Method = $Method; TimeoutSec = 30; UseBasicParsing = $true }
        if ($Body) { $params["Body"] = $Body; $params["ContentType"] = "application/json" }
        if ($Headers) { $params["Headers"] = $Headers }
        $resp = Invoke-WebRequest @params -ErrorAction Stop
        $code = $resp.StatusCode
        $ok = $code -eq $ExpectedStatus
        if ($ContainsKey -and $ok) {
            $json = $resp.Content | ConvertFrom-Json
            $ok = $null -ne ($json.PSObject.Properties | Where-Object { $_.Name -eq $ContainsKey })
        }
        $status = if ($ok) { "PASS" } else { "FAIL" }
        return [PSCustomObject]@{ Name=$Name; Status=$status; Code=$code; Expected=$ExpectedStatus }
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        $ok = ($code -eq $ExpectedStatus)
        $status = if ($ok) { "PASS" } else { "FAIL" }
        return [PSCustomObject]@{ Name=$Name; Status=$status; Code=$code; Expected=$ExpectedStatus }
    }
}

Write-Host "=== VF Logistics External API Tests ===" -ForegroundColor Cyan
Write-Host "Target: $BaseUrl`n"

# 1. Health
$r = Test-Endpoint -Name "health_check" -Method GET -Path "/health" -ExpectedStatus 200 -ContainsKey "status"
$results += $r; Write-Host "[$($r.Status)] $($r.Name) ($($r.Code))"

# 2. Security headers
$headers = (Invoke-WebRequest -Uri "$BaseUrl/" -Method HEAD -TimeoutSec 15 -UseBasicParsing).Headers
$headerTests = @(
    @{Name="header_x_frame_options"; Key="X-Frame-Options"; Expected="DENY"},
    @{Name="header_x_content_type"; Key="X-Content-Type-Options"; Expected="nosniff"},
    @{Name="header_referrer_policy"; Key="Referrer-Policy"; Expected="strict-origin-when-cross-origin"},
    @{Name="header_permissions_policy"; Key="Permissions-Policy"; Expected="camera=()"}
)
foreach ($ht in $headerTests) {
    $val = $headers[$ht.Key]
    $ok = $val -and $val.Contains($ht.Expected)
    $status = if ($ok) { "PASS" } else { "FAIL" }
    $r = [PSCustomObject]@{ Name=$ht.Name; Status=$status; Code="present"; Expected=$ht.Expected }
    $results += $r; Write-Host "[$status] $($ht.Name): $val"
}

# 3. CSP header
$csp = $headers["Content-Security-Policy"]
$cspOk = $csp -and $csp.Contains("frame-ancestors 'none'") -and $csp.Contains("default-src 'self'")
$status = if ($cspOk) { "PASS" } else { "FAIL" }
$results += [PSCustomObject]@{ Name="header_csp"; Status=$status; Code="present"; Expected="CSP complete" }
Write-Host "[$status] header_csp"

# 4. CORS
$corsBlocked = (Invoke-WebRequest -Uri "$BaseUrl/" -Method HEAD -Headers @{Origin="https://evil.com"} -TimeoutSec 10 -UseBasicParsing).Headers
$corsVal = $corsBlocked["Access-Control-Allow-Origin"]
$ok = -not $corsVal -or $corsVal -ne "https://evil.com"
$status = if ($ok) { "PASS" } else { "FAIL" }
$results += [PSCustomObject]@{ Name="cors_blocks_evil"; Status=$status; Code="-"; Expected="no ACAO for evil.com" }
Write-Host "[$status] cors_blocks_evil"

$corsAllowed = (Invoke-WebRequest -Uri "$BaseUrl/" -Method HEAD -Headers @{Origin="http://localhost:5000"} -TimeoutSec 10 -UseBasicParsing).Headers
$ok = $corsAllowed["Access-Control-Allow-Origin"] -eq "http://localhost:5000"
$status = if ($ok) { "PASS" } else { "FAIL" }
$results += [PSCustomObject]@{ Name="cors_allows_localhost"; Status=$status; Code="-"; Expected="ACAO: localhost:5000" }
Write-Host "[$status] cors_allows_localhost"

# 5. Agents
$r = Test-Endpoint -Name "agents_endpoint" -Method GET -Path "/agents" -ExpectedStatus 200 -ContainsKey "agents"
$results += $r; Write-Host "[$($r.Status)] $($r.Name)"

# 6-12. CRUD GET endpoints
$getEndpoints = @(
    @{Name="config"; Path="/api/v1/config"; Key="agents"},
    @{Name="config_model"; Path="/api/v1/config/model"; Key="current_model"},
    @{Name="governance_agent"; Path="/api/v1/governance/agent"; Key="state"},
    @{Name="governance_boundaries"; Path="/api/v1/governance/boundaries"; Key="boundaries"},
    @{Name="prefilter_rules"; Path="/api/v1/governance/prefilter-rules"; Key="vip_registry"},
    @{Name="orchestrator_state"; Path="/api/v1/orchestrator/state?limit=1&drain=0"; Key="cases"},
    @{Name="metrics_summary"; Path="/api/v1/metrics/summary"; Key="counts"}
)
foreach ($ep in $getEndpoints) {
    $r = Test-Endpoint -Name $ep.Name -Method GET -Path $ep.Path -ExpectedStatus 200 -ContainsKey $ep.Key
    $results += $r; Write-Host "[$($r.Status)] $($r.Name) ($($r.Code))"
}

# 13-14. Pagination
$r = Test-Endpoint -Name "cases_pagination" -Method GET -Path "/api/v1/cases?limit=2" -ExpectedStatus 200 -ContainsKey "items"
$results += $r; Write-Host "[$($r.Status)] $($r.Name)"
$r = Test-Endpoint -Name "audit_pagination" -Method GET -Path "/api/v1/audit?limit=2" -ExpectedStatus 200 -ContainsKey "items"
$results += $r; Write-Host "[$($r.Status)] $($r.Name)"
$r = Test-Endpoint -Name "events_pagination" -Method GET -Path "/api/v1/events?limit=2" -ExpectedStatus 200 -ContainsKey "items"
$results += $r; Write-Host "[$($r.Status)] $($r.Name)"

# 15-16. POST endpoints
$r = Test-Endpoint -Name "drain" -Method POST -Path "/api/v1/orchestrator/drain" -Body "{}" -ExpectedStatus 200
$results += $r; Write-Host "[$($r.Status)] $($r.Name) ($($r.Code))"
$r = Test-Endpoint -Name "tick" -Method POST -Path "/api/v1/orchestrator/tick" -Body "{}" -ExpectedStatus 200
$results += $r; Write-Host "[$($r.Status)] $($r.Name) ($($r.Code))"

# Summary
$pass = ($results | Where-Object { $_.Status -eq "PASS" }).Count
$fail = ($results | Where-Object { $_.Status -eq "FAIL" }).Count
Write-Host "`n=== Results: $pass PASS, $fail FAIL out of $($results.Count) tests ===" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Red" })

# Save evidence
$results | Export-Csv -Path "$evidenceDir\external-api-results.csv" -NoTypeInformation
Write-Host "Evidence saved to $evidenceDir\external-api-results.csv"

# Save full headers
$headers | Out-String | Out-File "$evidenceDir\production-headers.txt" -Encoding utf8

exit $fail
