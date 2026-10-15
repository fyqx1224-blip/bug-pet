# make_release.ps1 - create the GitHub Release, upload the zip, refresh repo description.
#
# Run it in YOUR OWN terminal (PowerShell), NOT inside any sandboxed shell:
#   powershell -ExecutionPolicy Bypass -File "<path-to-this-repo>\make_release.ps1"
#
# Steps:
#   1. get a GitHub token: Git Credential Manager cache first, else prompt to paste one
#      (create at https://github.com/settings/tokens/new?scopes=repo&description=bug-pet-release )
#   2. create release "v1.0" (or reuse it if it already exists)
#   3. upload the zip as the release asset, under the ASCII name from asset_name.txt
#   4. patch the repository description with the download link
#   5. push all local commits ahead of origin/main (README download section etc.)
#
# IMPORTANT IMPLEMENTATION NOTES (do not "simplify" these away):
#   * Text files are read with [System.IO.File]::ReadAllText. Get-Content -Raw in this
#     environment returns a decorated object (value/PSPath/...), which ConvertTo-Json
#     would serialize as an object -> GitHub 422 "For properties/body".
#   * JSON bodies are sent as UTF-8 BYTES with charset in the Content-Type, because
#     Windows PowerShell 5.1 mangles non-ASCII when sending a string body.
#   * GitHub STRIPS every non-ASCII character out of a release ASSET name. Proven:
#     a byte-perfect PATCH of "<hanzi>.zip" came back as "-.zip", and a survey of 12
#     Chinese projects found 296 assets with zero non-ASCII names. Hence the asset
#     name lives in asset_name.txt and must be ASCII. (Release title / notes /
#     description ARE plain text fields and take Chinese just fine.)
#   * Invoke-WebRequest also drops non-ASCII from the request URL - same reason the
#     upload uses an ASCII ?name=.
#   * Do NOT call curl.exe. It cannot be launched on this machine; PowerShell aborts
#     with "[error 2147942632 (0x800700e8)] (start "curl.exe" ...)".
#   * script itself is pure ASCII; all Chinese text lives in the UTF-8 sidecar files.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # 42MB upload: avoid the slow progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Dir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Owner = 'fyqx1224-blip'
$Repo  = 'bug-pet'
$Tag   = 'v1.0'
$Api   = "https://api.github.com/repos/$Owner/$Repo"

function Read-Utf8([string]$rel) {
    $p = Join-Path $Dir $rel
    return [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
}

$ZipName   = (Read-Utf8 'zip_name.txt').Trim()      # LOCAL zip file name (may be Chinese)
$AssetName = (Read-Utf8 'asset_name.txt').Trim()    # PUBLISHED asset name (MUST be ASCII)
$Zip       = Join-Path (Split-Path -Parent $Dir) $ZipName
$Title     = (Read-Utf8 'release_title.txt').Trim()
$Notes     = Read-Utf8 'release_notes.md'
$Desc      = (Read-Utf8 'repo_description.txt').Trim()

# GitHub strips every non-ASCII character out of a release ASSET name (filename
# sanitisation). Verified the hard way: we PATCHed the name to
# "<5 hanzi>-<5 hanzi>.zip" and GitHub stored exactly "-.zip". Our json body was
# byte-perfect, so this is server-side, not ours. A survey of 12 Chinese projects
# found 296 release assets and ZERO with a non-ASCII name - they all use ASCII.
# So the asset name is a separate, ASCII-only setting.
$nonAscii = @($AssetName.ToCharArray() | Where-Object { [int]$_ -gt 127 })
if ($nonAscii.Count -gt 0) {
    Write-Host "[FAIL] asset_name.txt contains $($nonAscii.Count) non-ASCII char(s);" -ForegroundColor Red
    Write-Host "       GitHub would silently strip them. Use plain ASCII." -ForegroundColor Red
    exit 1
}

Write-Host "== bug_pet release publisher: $Owner/$Repo $Tag =="

if (-not (Test-Path -LiteralPath $Zip)) {
    Write-Host "[FAIL] zip not found: $Zip" -ForegroundColor Red
    exit 1
}

# ---------- 1) token ----------
$token = $null
$fill = ("url=https://github.com`n`n" | git credential fill 2>$null)
$pw   = $fill | Where-Object { $_ -like 'password=*' } | Select-Object -First 1
if ($pw) {
    $token = $pw.Substring('password='.Length)
    Write-Host '[ok] token from Git Credential Manager'
} else {
    Write-Host '[info] no cached credential in Git Credential Manager.'
    Write-Host '[info] create one here (repo scope): https://github.com/settings/tokens/new?scopes=repo&description=bug-pet-release'
    $secure = Read-Host 'Paste your GitHub token (input is hidden)' -AsSecureString
    $token  = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
                  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    if (-not $token) { Write-Host '[FAIL] empty token, abort.' -ForegroundColor Red; exit 1 }
    Write-Host '[ok] token pasted'
}
$H = @{
    Authorization = "Bearer $token"
    Accept        = 'application/vnd.github+json'
    'User-Agent'  = 'bug-pet-release'
}

function Send-Json {
    param([string]$Method, [string]$Uri, [hashtable]$Object)
    $json  = $Object | ConvertTo-Json -Depth 5 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    return Invoke-RestMethod -Uri $Uri -Headers $H -Method $Method -Body $bytes -ContentType 'application/json; charset=utf-8'
}

$script:failed = $false
function Show-Fail([string]$step) {
    $msg = $_.ErrorDetails.Message
    if (-not $msg) { $msg = $_.Exception.Message }
    Write-Host "[FAIL] $step : $msg" -ForegroundColor Red
    # Deliberately NOT fatal: a failed asset upload must not prevent the
    # description update or the git push that follow it.
    $script:failed = $true
}

# ---------- 2) create or reuse the release ----------
try {
    $rel = Invoke-RestMethod -Uri "$Api/releases/tags/$Tag" -Headers $H -Method Get
    Write-Host "[ok] release $Tag already exists, reusing: $($rel.html_url)"
    # refresh title + notes so a re-run always matches the current payload
    $rel = Send-Json -Method Patch -Uri "$Api/releases/$($rel.id)" -Object @{
        name = $Title
        body = $Notes
    }
    Write-Host '[ok] release title/notes refreshed'
} catch {
    try {
        $rel = Send-Json -Method Post -Uri "$Api/releases" -Object @{
            tag_name   = $Tag
            name       = $Title
            body       = $Notes
            draft      = $false
            prerelease = $false
        }
        Write-Host "[ok] release created: $($rel.html_url)"
    } catch { Show-Fail 'create release' }
}

# ---------- 3) upload the zip asset ----------
# The asset is uploaded straight under its final (ASCII) name - see the note at
# the top about GitHub stripping non-ASCII from asset names. There is no rename
# step, because renaming to a Chinese name provably does not stick.
# NEVER shell out to curl.exe here: this machine refuses to launch it and
# PowerShell dies with "[error 2147942632 (0x800700e8)] (start "curl.exe" ...)".
#
# ORDER MATTERS: upload first, clean up after. If the upload fails we then still
# have the previous release intact instead of a release with zero assets.

$sizeMB    = [math]::Round((Get-Item -LiteralPath $Zip).Length / 1MB, 1)
$uploadUrl = ($rel.upload_url -replace '\{.*\}', '') + '?name=' + $AssetName

# 3a) drop a same-named asset from an earlier run so the upload cannot 422
try {
    foreach ($a in @($rel.assets | Where-Object { $_.name -eq $AssetName })) {
        Invoke-RestMethod -Uri "$Api/releases/assets/$($a.id)" -Headers $H -Method Delete | Out-Null
        Write-Host "[ok] removed previous $AssetName"
    }
} catch { Show-Fail 'clear same-named asset' }

# 3b) upload under the ASCII name (Invoke-WebRequest is safe with ASCII)
# Stage a copy under a pure-ASCII path first, so the upload never has to open a
# Unicode file path. Falls back to uploading in place if the copy fails.
$stagePath = $Zip
$staged    = $false
try {
    $tmpPath = Join-Path $env:TEMP 'bug-pet-upload.zip'
    Copy-Item -LiteralPath $Zip -Destination $tmpPath -Force
    $stagePath = $tmpPath
    $staged    = $true
} catch {
    Write-Host "[WARN] staging copy failed, uploading in place: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    Invoke-WebRequest -Uri $uploadUrl -Method Post -Headers $H `
        -InFile $stagePath -ContentType 'application/zip' -UseBasicParsing | Out-Null
    Write-Host "[ok] uploaded as $AssetName ($sizeMB MB)"
} catch { Show-Fail 'upload asset' }
finally {
    if ($staged -and (Test-Path -LiteralPath $stagePath)) {
        Remove-Item -LiteralPath $stagePath -Force -ErrorAction SilentlyContinue
    }
}

# 3c) now remove every OTHER asset (the stale "-.zip" from the broken run, etc.)
$newId = $null
try {
    $relNow = Invoke-RestMethod -Uri "$Api/releases/tags/$Tag" -Headers $H -Method Get
    $newId  = (@($relNow.assets | Where-Object { $_.name -eq $AssetName })[0]).id
    if (-not $newId) { throw 'uploaded asset not found on the release' }
    foreach ($a in @($relNow.assets | Where-Object { $_.id -ne $newId })) {
        Invoke-RestMethod -Uri "$Api/releases/assets/$($a.id)" -Headers $H -Method Delete | Out-Null
        Write-Host "[ok] removed stale asset: $($a.name)"
    }
} catch { Show-Fail 'clear stale assets' }

# (no rename step: GitHub strips non-ASCII out of asset names, so the ASCII name
#  chosen in 3b IS the final name - see the note at the top of this script.)

# report where it landed
try {
    $relNow = Invoke-RestMethod -Uri "$Api/releases/tags/$Tag" -Headers $H -Method Get
    foreach ($a in @($relNow.assets)) {
        Write-Host "     asset: $($a.name)  ($([math]::Round($a.size/1MB,1)) MB)"
        Write-Host "     link : $($a.browser_download_url)"
    }
    $final = @($relNow.assets | Where-Object { $_.name -eq $AssetName })
    if ($final.Count -eq 1 -and $final[0].size -eq (Get-Item -LiteralPath $Zip).Length) {
        Write-Host "[ok] VERIFIED: asset '$AssetName' + byte size match the local package" -ForegroundColor Green
    } else {
        Write-Host '[WARN] asset name/size does NOT match the local package - check the list above' -ForegroundColor Yellow
        $script:failed = $true
    }
} catch {
    Write-Host "[WARN] could not re-read the release: $($_.Exception.Message)" -ForegroundColor Yellow
    $script:failed = $true
}

# ---------- 4) repo description ----------
try {
    Send-Json -Method Patch -Uri $Api -Object @{ description = $Desc } | Out-Null
    Write-Host '[ok] repo description updated'
} catch { Show-Fail 'update description' }

# ---------- 5) push local commits ----------
Push-Location $Dir
try {
    git add README.md
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host '[info] README unchanged locally'
    } else {
        git commit -m 'README: add release download link' | Out-Null
        Write-Host '[ok] README committed'
    }
    $hasRef = $false
    git show-ref --verify --quiet 'refs/remotes/origin/main'
    if ($?) { $hasRef = $true }
    if ($hasRef) {
        $ahead = [int](git rev-list --count 'origin/main..HEAD')
    } else {
        $ahead = 1
    }
    if ($ahead -gt 0) {
        git push
        if ($LASTEXITCODE -ne 0) { throw 'git push failed' }
        Write-Host "[ok] pushed $ahead commit(s)"
    } else {
        Write-Host '[skip] nothing to push'
    }
} catch {
    Show-Fail 'push commits'
} finally {
    Pop-Location
}

Write-Host ''
if ($script:failed) {
    Write-Host 'FINISHED WITH ERRORS - see the [FAIL]/[WARN] lines above' -ForegroundColor Red
    Write-Host "release page -> https://github.com/$Owner/$Repo/releases/tag/$Tag" -ForegroundColor Yellow
    exit 1
}
Write-Host "ALL DONE -> https://github.com/$Owner/$Repo/releases/tag/$Tag" -ForegroundColor Green
