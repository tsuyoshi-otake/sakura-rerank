param(
    [Parameter(Mandatory = $true)]
    [string]$SakuraInputRoot,

    [Parameter(Mandatory = $true)]
    [string]$DictionaryPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputBinary,

    [Parameter(Mandatory = $true)]
    [string]$IdentityManifest,

    [Parameter(Mandatory = $true)]
    [string]$BuildRoot,

    [ValidateSet("unverified", "verified")]
    [string]$VerificationStatus = "unverified",

    [string]$CargoLockEvidence
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$expectedHead = "8e966dff456e4e7165e025f97c1f73327ff3f550"
$expectedDictionarySha256 = "6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad"
$tempRoot = [System.IO.Path]::GetFullPath("C:\Users\developer\tmp")
$sourceRoot = [System.IO.Path]::GetFullPath($SakuraInputRoot)
$dictionaryPathResolved = [System.IO.Path]::GetFullPath($DictionaryPath)
$outputBinaryResolved = [System.IO.Path]::GetFullPath($OutputBinary)
$identityManifestResolved = [System.IO.Path]::GetFullPath($IdentityManifest)
$buildRootResolved = [System.IO.Path]::GetFullPath($BuildRoot)
$cargoLockEvidenceResolved = if ($CargoLockEvidence) { [System.IO.Path]::GetFullPath($CargoLockEvidence) } else { $null }

function Assert-UnderTempRoot([string]$PathToCheck, [string]$Field) {
    $prefix = $tempRoot.TrimEnd("\") + "\"
    if (-not $PathToCheck.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Field must be under C:\Users\developer\tmp"
    }
}

function Invoke-RtkChecked([string[]]$Arguments) {
    & rtk @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "rtk command failed: $($Arguments -join ' ')"
    }
}

function Get-RtkText([string[]]$Arguments) {
    $text = (& rtk @Arguments | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "rtk command failed: $($Arguments -join ' ')"
    }
    return $text
}

function Get-Sha256([string]$PathToHash) {
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($PathToHash)
    try {
        return ([System.BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

function Write-Utf8([string]$PathToWrite, [string]$Text) {
    [System.IO.File]::WriteAllText($PathToWrite, $Text, [System.Text.UTF8Encoding]::new($false))
}

Assert-UnderTempRoot $sourceRoot "SakuraInputRoot"
Assert-UnderTempRoot $dictionaryPathResolved "DictionaryPath"
Assert-UnderTempRoot $outputBinaryResolved "OutputBinary"
Assert-UnderTempRoot $identityManifestResolved "IdentityManifest"
Assert-UnderTempRoot $buildRootResolved "BuildRoot"
if ($cargoLockEvidenceResolved) {
    Assert-UnderTempRoot $cargoLockEvidenceResolved "CargoLockEvidence"
}
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
    throw "SakuraInputRoot does not exist"
}
if (-not (Test-Path -LiteralPath $dictionaryPathResolved -PathType Leaf)) {
    throw "DictionaryPath does not exist"
}
if (Test-Path -LiteralPath $outputBinaryResolved -PathType Leaf) {
    throw "OutputBinary already exists"
}
if (Test-Path -LiteralPath $identityManifestResolved -PathType Leaf) {
    throw "IdentityManifest already exists"
}

$head = Get-RtkText @("git", "-C", $sourceRoot, "rev-parse", "HEAD")
if ($head -ne $expectedHead) {
    throw "SakuraInputRoot is not at the pinned HEAD"
}
$status = Get-RtkText @("git", "-C", $sourceRoot, "status", "--porcelain")
if ($status) {
    throw "SakuraInputRoot is dirty"
}
$dictionarySha256 = Get-Sha256 $dictionaryPathResolved
if ($dictionarySha256 -ne $expectedDictionarySha256) {
    throw "DictionaryPath does not match the pinned SHA-256"
}
$exporterGitSha = Get-RtkText @("git", "-C", $repoRoot, "rev-parse", "HEAD")
if ($exporterGitSha -notmatch "^[0-9a-f]{40}$") {
    throw "repository HEAD is not a full lowercase Git SHA"
}
$patchPath = Join-Path $repoRoot "research\patches\sakura-input-research-top32.patch"
$exporterSource = Join-Path $repoRoot "research\exporter"
if (-not (Test-Path -LiteralPath $patchPath -PathType Leaf)) {
    throw "instrumentation patch is missing"
}
if (-not (Test-Path -LiteralPath $exporterSource -PathType Container)) {
    throw "exporter source is missing"
}
$patchSha256 = Get-Sha256 $patchPath

$runRoot = Join-Path $buildRootResolved ("run-" + [Guid]::NewGuid().ToString("N"))
$worktree = Join-Path $runRoot "sakura-input"
$oldExporterGitSha = $env:SAKURA_RERANK_EXPORTER_GIT_SHA
$worktreeAdded = $false
try {
    New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
    Invoke-RtkChecked @("git", "-C", $sourceRoot, "worktree", "add", "--detach", $worktree, $expectedHead)
    $worktreeAdded = $true
    Invoke-RtkChecked @("git", "-C", $worktree, "apply", "--unidiff-zero", $patchPath)

    $destinationExporterSource = Join-Path $worktree "research\exporter"
    New-Item -ItemType Directory -Path (Split-Path -Parent $destinationExporterSource) -Force | Out-Null
    Copy-Item -LiteralPath $exporterSource -Destination $destinationExporterSource -Recurse
    $rootManifestPath = Join-Path $worktree "Cargo.toml"
    $rootManifest = [System.IO.File]::ReadAllText($rootManifestPath)
    $member = '    "crates/sakura-neural-worker",'
    if (-not $rootManifest.Contains($member)) {
        throw "Sakura Input workspace member anchor is missing"
    }
    $rootManifest = $rootManifest.Replace($member, "$member`r`n    `"research/exporter`",`r`n")
    Write-Utf8 $rootManifestPath $rootManifest

    $env:SAKURA_RERANK_EXPORTER_GIT_SHA = $exporterGitSha
    $workspaceManifest = Join-Path $worktree "Cargo.toml"
    Invoke-RtkChecked @("cargo", "generate-lockfile", "--manifest-path", $workspaceManifest)
    Invoke-RtkChecked @("cargo", "build", "--locked", "--release", "--manifest-path", $workspaceManifest, "--package", "sakura-research-top32-exporter")
    $builtBinary = Join-Path $worktree "target\release\sakura-research-top32-exporter.exe"
    if (-not (Test-Path -LiteralPath $builtBinary -PathType Leaf)) {
        throw "release exporter binary was not produced"
    }
    $outputParent = Split-Path -Parent $outputBinaryResolved
    $identityParent = Split-Path -Parent $identityManifestResolved
    $lockEvidenceParent = if ($cargoLockEvidenceResolved) { Split-Path -Parent $cargoLockEvidenceResolved } else { $null }
    New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
    New-Item -ItemType Directory -Path $identityParent -Force | Out-Null
    if ($lockEvidenceParent) {
        New-Item -ItemType Directory -Path $lockEvidenceParent -Force | Out-Null
    }
    [System.IO.File]::Copy($builtBinary, $outputBinaryResolved)
    $binarySha256 = Get-Sha256 $outputBinaryResolved
    $lockPath = Join-Path $worktree "Cargo.lock"
    $cargoLockSha256 = Get-Sha256 $lockPath
    if ($cargoLockEvidenceResolved) {
        [System.IO.File]::Copy($lockPath, $cargoLockEvidenceResolved, $true)
    }
    $rustcVersion = Get-RtkText @("proxy", "rustc", "--version")
    $cargoVersion = Get-RtkText @("proxy", "cargo", "--version")
    $rustcDetails = Get-RtkText @("proxy", "rustc", "-vV")
    $hostLine = $rustcDetails -split "`r?`n" | Where-Object { $_ -like "host:*" } | Select-Object -First 1
    if (-not $hostLine) {
        throw "rustc target triple is missing"
    }
    $targetTriple = $hostLine.Substring(5).Trim()
    $manifest = [ordered]@{
        schema_version = 1
        manifest_kind = "research_top32_exporter"
        verification_status = $VerificationStatus
        exporter_git_sha = $exporterGitSha
        exporter_binary_sha256 = $binarySha256
        sakura_input_head = $expectedHead
        dictionary_sha256 = $dictionarySha256
        instrumentation_patch_sha256 = $patchSha256
        cargo_lock_sha256 = $cargoLockSha256
        rustc_version = $rustcVersion
        cargo_version = $cargoVersion
        target_triple = $targetTriple
        profile = "release"
        requested_limit = 32
        effective_converter_bound = 32
        user_dictionary_enabled = $false
    }
    Write-Utf8 $identityManifestResolved (($manifest | ConvertTo-Json -Depth 4) + "`n")
    Write-Output (ConvertTo-Json -InputObject ([ordered]@{
        status = "built"
        exporter_git_sha = $exporterGitSha
        exporter_binary_sha256 = $binarySha256
        instrumentation_patch_sha256 = $patchSha256
        cargo_lock_sha256 = $cargoLockSha256
        sakura_input_head = $expectedHead
        dictionary_sha256 = $dictionarySha256
        effective_converter_bound = 32
        output_binary = $outputBinaryResolved
        identity_manifest = $identityManifestResolved
    }) -Compress)
}
finally {
    if ($oldExporterGitSha) {
        $env:SAKURA_RERANK_EXPORTER_GIT_SHA = $oldExporterGitSha
    }
    else {
        Remove-Item Env:SAKURA_RERANK_EXPORTER_GIT_SHA -ErrorAction SilentlyContinue
    }
    if ($worktreeAdded) {
        try {
            Invoke-RtkChecked @("git", "-C", $sourceRoot, "worktree", "remove", "--force", $worktree)
        }
        catch {
            Write-Warning "could not remove temporary Sakura Input worktree"
        }
    }
    if (Test-Path -LiteralPath $runRoot) {
        try {
            [System.IO.Directory]::Delete($runRoot, $true)
        }
        catch {
            Write-Warning "could not remove temporary build root: $runRoot"
        }
    }
}
