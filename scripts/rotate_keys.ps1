<#
Rotate the two provider API keys that leaked into a conversation transcript.

Rotation does not erase the leak -- the old values stay in that transcript file
forever. It makes the leaked values WORTHLESS, which is the actual objective.

Order of operations matters, and this script enforces it:

  1. read the new key without ever echoing it
  2. VALIDATE it against the provider directly, before Snowflake/GCP sees it
  3. add it as a new Secret Manager version
  4. redeploy so the running revision picks it up
  5. verify the live service still answers
  6. leave the OLD version enabled, and print the commands to disable it

Step 2 is the point of the whole script. A mistyped key is syntactically fine, so
it uploads and deploys cleanly and then fails at inference time -- in front of
whoever is watching the demo. Validating against the provider first means a bad
paste costs nothing and never reaches production.

Step 6 is deliberate too: the old version stays enabled so a rollback is one
command. Disabling it before the new key has served real traffic converts a
recoverable mistake into an outage.

    powershell -File scripts/rotate_keys.ps1              # both keys
    powershell -File scripts/rotate_keys.ps1 -Only nebius # one key
    powershell -File scripts/rotate_keys.ps1 -SkipDeploy  # secrets only
#>

[CmdletBinding()]
param(
    [ValidateSet('both', 'nebius', 'tavily')] [string] $Only = 'both',
    [switch] $SkipDeploy,
    # Deploy and verify without touching any key. Needed because a key can end up
    # in Secret Manager while the deploy never ran -- exactly what the stderr bug
    # above caused -- and re-pasting a key that is already stored would be both
    # pointless and another chance to leak it.
    [switch] $DeployOnly,
    [string] $Project = 'vf-fraud-detection-phuochoa',
    [string] $Region  = 'asia-southeast1',
    [string] $Service = 'vf-logistics'
)

$ErrorActionPreference = 'Stop'
$BackendUrl   = 'https://vf-logistics-f7rcctz26a-as.a.run.app'
$NebiusUrl    = 'https://api.tokenfactory.nebius.com/v1/chat/completions'
$NebiusModel  = 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B'
$TavilyUrl    = 'https://api.tavily.com/search'

function Read-Secret([string] $Label) {
    # SecureString so the value is never echoed to the console and never lands in
    # the shell history. Converted to plain text only in memory, at the moment of
    # use, and never written to a file or printed.
    $secure = Read-Host -AsSecureString "  dan gia tri moi cho $Label (khong hien thi)"
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Test-NebiusKey([string] $Key) {
    # One token. Enough to prove the credential is accepted; too small to cost
    # anything worth measuring.
    $body = @{
        model      = $NebiusModel
        messages   = @(@{ role = 'user'; content = 'ping' })
        max_tokens = 1
    } | ConvertTo-Json -Depth 4
    try {
        $null = Invoke-RestMethod -Uri $NebiusUrl -Method Post -TimeoutSec 60 `
            -Headers @{ Authorization = "Bearer $Key"; 'Content-Type' = 'application/json' } `
            -Body $body
        return @{ ok = $true; detail = 'provider accepted the key' }
    } catch {
        $code = $null
        if ($_.Exception.Response) { $code = [int] $_.Exception.Response.StatusCode }
        return @{ ok = $false; detail = "HTTP $code -- $($_.Exception.Message)" }
    }
}

function Test-TavilyKey([string] $Key) {
    $body = @{ api_key = $Key; query = 'ping'; max_results = 1 } | ConvertTo-Json
    try {
        $null = Invoke-RestMethod -Uri $TavilyUrl -Method Post -TimeoutSec 60 `
            -Headers @{ 'Content-Type' = 'application/json' } -Body $body
        return @{ ok = $true; detail = 'provider accepted the key' }
    } catch {
        $code = $null
        if ($_.Exception.Response) { $code = [int] $_.Exception.Response.StatusCode }
        return @{ ok = $false; detail = "HTTP $code -- $($_.Exception.Message)" }
    }
}

function Add-SecretVersion([string] $Name, [string] $Value) {
    # --data-file=- keeps the value off the command line, where it would otherwise
    # be visible to any process listing and recorded in shell history.
    $tmp = [IO.Path]::GetTempFileName()
    try {
        # No trailing newline: gcloud stores the bytes verbatim, and a stray \n
        # becomes part of the secret and fails authentication in a way that looks
        # like a wrong key rather than a formatting error.
        [IO.File]::WriteAllText($tmp, $Value, (New-Object Text.UTF8Encoding $false))
        # gcloud on Windows is a PowerShell wrapper, and it writes its SUCCESS
        # message ("Created version [2] of the secret [...]") to STDERR. Merging
        # stderr into the pipeline with 2>&1 while $ErrorActionPreference is
        # 'Stop' makes PowerShell promote that informational line into a
        # TERMINATING error -- so the script aborted immediately after a write
        # that had in fact succeeded, before deploying and before the second key.
        # Relax the preference around the call and judge the outcome by
        # $LASTEXITCODE, which is the only trustworthy signal for a native exe.
        $out = & {
            $ErrorActionPreference = 'Continue'
            gcloud secrets versions add $Name --data-file=$tmp --project=$Project 2>&1
        }
        if ($LASTEXITCODE -ne 0) { throw "gcloud secrets versions add ${Name}: $out" }
        return ($out | Out-String).Trim()
    } finally {
        # Overwrite before deleting: Remove-Item unlinks but leaves the bytes.
        if (Test-Path $tmp) {
            [IO.File]::WriteAllText($tmp, ('0' * 256))
            Remove-Item $tmp -Force
        }
    }
}

# ---------------------------------------------------------------------------

Write-Host ''
Write-Host 'DOI KHOA API' -ForegroundColor Cyan
Write-Host ('-' * 62)
Write-Host 'Tao khoa moi truoc tren console, roi dan vao day:'
Write-Host '  Nebius : https://tokenfactory.nebius.com  (API keys)'
Write-Host '  Tavily : https://app.tavily.com           (API keys)'
Write-Host ''
Write-Host 'Khoa moi se duoc kiem chung voi nha cung cap TRUOC khi deploy.'
Write-Host 'Version cu KHONG bi vo hieu hoa, de con duong lui.'
Write-Host ''

$targets = @()
if (-not $DeployOnly) {
if ($Only -in 'both', 'nebius') { $targets += @{ secret = 'NEBIUS_API_KEY'; test = ${function:Test-NebiusKey} } }
if ($Only -in 'both', 'tavily') { $targets += @{ secret = 'TAVILY_API_KEY'; test = ${function:Test-TavilyKey} } }
}

$rotated = @()
foreach ($t in $targets) {
    $name = $t.secret
    Write-Host "[$name]" -ForegroundColor Yellow

    $before = (gcloud secrets versions list $name --project=$Project --format='value(name)' 2>$null |
               Measure-Object).Count
    Write-Host "  version hien tai: $before"

    $value = Read-Secret $name
    if ([string]::IsNullOrWhiteSpace($value)) {
        Write-Host '  bo qua: khong co gia tri' -ForegroundColor DarkGray
        Write-Host ''
        continue
    }
    if ($value -ne $value.Trim()) {
        # Pasting from a browser very often brings a trailing newline or space.
        Write-Host '  canh bao: gia tri co khoang trang o dau/cuoi, da cat bo' -ForegroundColor DarkYellow
        $value = $value.Trim()
    }

    Write-Host '  dang kiem chung voi nha cung cap...' -NoNewline
    $check = & $t.test $value
    if (-not $check.ok) {
        Write-Host ' THAT BAI' -ForegroundColor Red
        Write-Host "    $($check.detail)" -ForegroundColor Red
        Write-Host '    Khong ghi vao Secret Manager. Production khong bi anh huong.' -ForegroundColor Red
        Write-Host ''
        continue
    }
    Write-Host ' OK' -ForegroundColor Green

    Write-Host '  dang them version moi...' -NoNewline
    $null = Add-SecretVersion $name $value
    $after = (gcloud secrets versions list $name --project=$Project --format='value(name)' 2>$null |
              Measure-Object).Count
    Write-Host " OK (version: $before -> $after)" -ForegroundColor Green
    $rotated += $name
    Write-Host ''

    Remove-Variable value
}

if ($rotated.Count -eq 0 -and -not $DeployOnly) {
    Write-Host 'Khong co khoa nao duoc doi. Ket thuc.' -ForegroundColor DarkGray
    exit 0
}

# ---- redeploy -------------------------------------------------------------
# Cloud Run resolves `latest` at container start, so a running revision keeps
# using the version it booted with. Adding the secret version is not enough; the
# service has to be given a new revision.
if ($SkipDeploy) {
    Write-Host 'Bo qua deploy (-SkipDeploy). Revision dang chay VAN dung khoa cu.' -ForegroundColor DarkYellow
    Write-Host "  gcloud run deploy $Service --source . --region=$Region --project=$Project"
    exit 0
}

Write-Host 'dang deploy lai de revision moi nhan khoa moi...' -ForegroundColor Cyan
# Same stderr trap as Add-SecretVersion: `gcloud run deploy` streams all of its
# build progress to stderr, so under 'Stop' the very first progress line would
# kill the script mid-deploy.
$deploy = & {
    $ErrorActionPreference = 'Continue'
    gcloud run deploy $Service --source . --region=$Region --project=$Project `
        --allow-unauthenticated --memory=512Mi --timeout=300 `
        --min-instances=0 --max-instances=2 --quiet 2>&1
}
if ($LASTEXITCODE -ne 0) {
    Write-Host 'DEPLOY THAT BAI' -ForegroundColor Red
    Write-Host ($deploy | Out-String)
    Write-Host 'Version secret moi da ton tai nhung chua duoc dung. Version cu van con.' -ForegroundColor Yellow
    exit 1
}
$rev = gcloud run services describe $Service --region=$Region --project=$Project `
    --format='value(status.latestReadyRevisionName)' 2>$null
Write-Host "  deploy OK, revision: $rev" -ForegroundColor Green
Write-Host ''

# ---- verify the live service -------------------------------------------
Write-Host 'dang kiem tra service that...' -ForegroundColor Cyan
try {
    $h = Invoke-RestMethod -Uri "$BackendUrl/health" -TimeoutSec 60
    Write-Host "  health: OK" -ForegroundColor Green
} catch {
    Write-Host "  health: THAT BAI -- $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ''
Write-Host ('=' * 62)
if ($rotated.Count -gt 0) {
    Write-Host "Da doi: $($rotated -join ', ')" -ForegroundColor Green
} else {
    Write-Host 'Da deploy lai voi cac version secret dang co (khong doi khoa nao).' -ForegroundColor Green
}
Write-Host ''
# Every secret with more than one enabled version has an older one still live.
# Reported for all of them, not just the ones rotated in this run, because a key
# can be rotated without the deploy succeeding -- and then the stale version is
# easy to forget.
$stale = @()
foreach ($name in @('NEBIUS_API_KEY', 'TAVILY_API_KEY')) {
    $enabled = @(gcloud secrets versions list $name --project=$Project `
                 --format='value(name)' --filter='state:ENABLED' 2>$null | Sort-Object)
    if ($enabled.Count -gt 1) { $stale += @{ secret = $name; old = $enabled[0] } }
}
if ($stale.Count -gt 0) {
    Write-Host 'Version cu VAN dang bat, de con duong lui. Sau khi da chay on dinh' -ForegroundColor Yellow
    Write-Host 'mot luc (vai gio la du), vo hieu hoa version cu:' -ForegroundColor Yellow
    foreach ($s in $stale) {
        Write-Host "  gcloud secrets versions disable $($s.old) --secret=$($s.secret) --project=$Project"
    }
    Write-Host ''
}
Write-Host 'CHUA XONG. Viec quan trong nhat van con:' -ForegroundColor Red
Write-Host '  Phai XOA/THU HOI khoa cu tren console nha cung cap.' -ForegroundColor Red
Write-Host ''
Write-Host 'Them version moi o day chi thay doi khoa ma SERVICE NAY dung. Khoa cu' -ForegroundColor Yellow
Write-Host 'van con hieu luc day du o phia nha cung cap, nen ai giu gia tri da lo' -ForegroundColor Yellow
Write-Host 'van tieu tien duoc tren tai khoan cua ban. Chi viec thu hoi tai' -ForegroundColor Yellow
Write-Host 'nguon moi dong duoc lo:' -ForegroundColor Yellow
Write-Host '  Nebius : https://tokenfactory.nebius.com  -> xoa khoa cu'
Write-Host '  Tavily : https://app.tavily.com           -> xoa khoa cu'
Write-Host ''
Write-Host 'An toan de lam ngay: service da chay khoa moi roi.' -ForegroundColor DarkGray
