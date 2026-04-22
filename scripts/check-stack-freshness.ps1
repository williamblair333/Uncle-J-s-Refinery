<#
.SYNOPSIS
    Checks installed vs latest versions of all MCP stack tools.
    Exits 0 if current, 1 if any PyPI upgrades available.
.PARAMETER Changes
    If set, fetches and prints release notes for behind packages.
#>
param([switch]$Changes)

$ScriptDir  = $PSScriptRoot
$ProjRoot   = Split-Path $ScriptDir -Parent
$VenvPy     = Join-Path $ProjRoot ".venv\Scripts\python.exe"

$RED    = "`e[31m"; $GREEN = "`e[32m"; $YELLOW = "`e[33m"
$BOLD   = "`e[1m";  $DIM   = "`e[2m";  $NC     = "`e[0m"

$upgrades = 0

function Get-VenvVersion([string]$pkg) {
    try {
        $v = & $VenvPy -c "import importlib.metadata; print(importlib.metadata.version('$pkg'))" 2>$null
        return $v.Trim()
    } catch { return "" }
}

function Get-PypiLatest([string]$pkg) {
    try {
        $r = Invoke-RestMethod "https://pypi.org/pypi/$pkg/json" -TimeoutSec 10
        return $r.info.version
    } catch { return "?" }
}

function Get-NpmLatest([string]$pkg) {
    try {
        return (npm view $pkg version 2>$null).Trim()
    } catch { return "?" }
}

function Get-GhHead([string]$repo) {
    try {
        $h = @{ "Accept" = "application/vnd.github.v3+json" }
        if ($env:GITHUB_TOKEN) { $h["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
        $r = Invoke-RestMethod "https://api.github.com/repos/$repo/commits/HEAD" `
               -Headers $h -TimeoutSec 10
        return "$($r.sha.Substring(0,7))  $($r.commit.committer.date.Substring(0,10))"
    } catch { return "?" }
}

function Show-Changelog([string]$repo, [string]$installed) {
    try {
        $h = @{ "Accept" = "application/vnd.github.v3+json" }
        if ($env:GITHUB_TOKEN) { $h["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
        $releases = Invoke-RestMethod `
            "https://api.github.com/repos/$repo/releases?per_page=20" `
            -Headers $h -TimeoutSec 10
    } catch { return }

    $instVer = [System.Version]::new(($installed -replace '^v',''))
    $newer = $releases | Where-Object {
        try { [System.Version]::new(($_.tag_name -replace '^v','')) -gt $instVer } catch { $false }
    } | Sort-Object { [System.Version]::new(($_.tag_name -replace '^v','')) }

    foreach ($r in $newer) {
        Write-Host ""
        Write-Host "    ${BOLD}$($r.tag_name)${NC}  ($($r.published_at.Substring(0,10)))"
        if ($r.body) {
            $lines = $r.body -split "`n" | Where-Object { $_.Trim() }
            $shown = $lines | Select-Object -First 25
            foreach ($l in $shown) { Write-Host "    $l" }
            if ($lines.Count -gt 25) {
                Write-Host "    ${DIM}... $($lines.Count - 25) more lines — $($r.html_url)${NC}"
            }
        } else {
            Write-Host "    (no release notes — $($r.html_url))"
        }
    }
}

function Check-Pypi([string]$label, [string]$pkg, [string]$github) {
    $installed = Get-VenvVersion $pkg
    if (-not $installed) {
        Write-Host "  ${YELLOW}?${NC}  $($label.PadRight(22)) not found in venv"
        return
    }
    $latest = Get-PypiLatest $pkg
    if ($latest -eq "?") {
        Write-Host "  ${YELLOW}?${NC}  $($label.PadRight(22)) installed=$installed  fetch failed"
    } elseif ($installed -eq $latest) {
        Write-Host "  ${GREEN}✓${NC}  $($label.PadRight(22)) $($installed.PadRight(12)) current"
    } else {
        Write-Host "  ${RED}↑${NC}  $($label.PadRight(22)) $($installed.PadRight(12)) → $latest"
        $script:upgrades++
        if ($Changes) { Show-Changelog $github $installed }
        Write-Host ""
    }
}

function Check-Npm([string]$label, [string]$pkg) {
    $latest = Get-NpmLatest $pkg
    Write-Host "  ${GREEN}·${NC}  $($label.PadRight(22)) latest=$($latest.PadRight(10))  auto via npx"
}

function Check-Git([string]$label, [string]$repo) {
    $head = Get-GhHead $repo
    Write-Host "  ${GREEN}·${NC}  $($label.PadRight(22)) HEAD=$head  auto via uvx"
}

Write-Host ""
Write-Host "${BOLD}Stack Freshness — $(Get-Date -Format 'yyyy-MM-dd HH:mm')${NC}"
Write-Host ("━" * 68)
Write-Host ""
Write-Host "PyPI  (pinned in venv — needs explicit upgrade):"
Check-Pypi "jcodemunch-mcp" "jcodemunch-mcp" "jgravelle/jcodemunch-mcp"
Check-Pypi "jdatamunch-mcp" "jdatamunch-mcp" "jgravelle/jdatamunch-mcp"
Check-Pypi "jdocmunch-mcp"  "jdocmunch-mcp"  "jgravelle/jdocmunch-mcp"
Check-Pypi "mempalace"      "mempalace"      "MemPalace/mempalace"
Write-Host ""
Write-Host "npm   (fetched fresh via npx on each run):"
Check-Npm "context7" "@upstash/context7-mcp"
Write-Host ""
Write-Host "git   (fetched from HEAD via uvx on each run):"
Check-Git "serena" "oraios/serena"
Write-Host ""
Write-Host ("━" * 68)

if ($upgrades -gt 0) {
    Write-Host ""
    Write-Host "${BOLD}To upgrade:${NC}"
    Write-Host "  cd $ProjRoot && uv pip install --upgrade ``"
    Write-Host "    jcodemunch-mcp jdatamunch-mcp jdocmunch-mcp mempalace"
}

Write-Host ""
Write-Host "${BOLD}GitHub Watches (→ Watch → Custom → Releases):${NC}"
@(
    "https://github.com/jgravelle/jcodemunch-mcp"
    "https://github.com/jgravelle/jdatamunch-mcp"
    "https://github.com/jgravelle/jdocmunch-mcp"
    "https://github.com/MemPalace/mempalace"
    "https://github.com/oraios/serena"
    "https://github.com/upstash/context7"
) | ForEach-Object { Write-Host "  $_" }
Write-Host ""

exit $(if ($upgrades -gt 0) { 1 } else { 0 })
