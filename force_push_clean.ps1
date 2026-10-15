# force_push_clean.ps1 - replace the PUBLIC repo history with the cleaned one.
#
# WHY THIS IS NEEDED
#   The original commits (8fd7f2d, b500ff8, ...) hard-coded this machine's real
#   Tailscale IP and the Windows user name. Scrubbing the working tree is NOT
#   enough: anyone can still run `git log -S <the leaked ip>` on the public repo.
#   Worse, the v1.0 TAG pointed straight at 8fd7f2d, so the leaked tree stayed
#   reachable at .../tree/v1.0 even if main were fixed.
#
#   The local history has already been rewritten into a single clean commit with
#   byte-identical content (same tree hash), and the v1.0 tag re-pointed at it.
#   This script publishes that.
#
# Run it in YOUR OWN terminal (PowerShell), NOT in a sandboxed shell:
#   powershell -ExecutionPolicy Bypass -File "<repo>\force_push_clean.ps1"
#
# It force-pushes origin/main and refs/tags/v1.0. Type YES at the prompt.
# Note: GitHub may keep the old objects reachable by SHA for a while, but with
# 0 forks / 0 stars / 0 downloads nothing has copied them.

$ErrorActionPreference = 'Stop'

$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $Dir
try {
    Write-Host '== force-push the cleaned history ==' -ForegroundColor Cyan
    Write-Host ("   remote      : " + (git remote get-url origin))
    Write-Host ("   commits now : " + (git rev-list --count HEAD))
    Write-Host ("   HEAD        : " + (git rev-parse --short HEAD))
    Write-Host ''

    Write-Host 'This OVERWRITES origin/main and refs/tags/v1.0.' -ForegroundColor Yellow
    Write-Host 'The old commits holding the leaked IP / user name become unreachable.' -ForegroundColor Yellow
    $ans = Read-Host 'Type YES to proceed'
    if ($ans -ne 'YES') { Write-Host 'aborted - nothing was pushed.' -ForegroundColor Yellow; exit 1 }

    git push --force origin main
    if ($LASTEXITCODE -ne 0) { throw 'force push of main failed' }
    Write-Host '[ok] origin/main replaced' -ForegroundColor Green

    git push --force origin refs/tags/v1.0
    if ($LASTEXITCODE -ne 0) { throw 'force push of the v1.0 tag failed' }
    Write-Host '[ok] v1.0 tag re-pointed' -ForegroundColor Green

    Write-Host ''
    Write-Host '[ok] history replaced.' -ForegroundColor Green
    Write-Host 'Next: replace the release asset with the clean build -'
    Write-Host '   powershell -ExecutionPolicy Bypass -File "' -NoNewline
    Write-Host (Join-Path $Dir 'make_release.ps1') -NoNewline
    Write-Host '"'
} finally {
    Pop-Location
}
