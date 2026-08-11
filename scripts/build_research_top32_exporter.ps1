[CmdletBinding()]
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
    [string]$VerificationStatus = "unverified"
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$expectedSakuraHead = "8e966dff456e4e7165e025f97c1f73327ff3f550"
$expectedDictionarySha256 = "6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad"
$expectedTarget = "x86_64-pc-windows-msvc"
$expectedToolchain = "stable-x86_64-pc-windows-msvc"
$expectedRustcVersion = "rustc 1.96.0 (ac68faa20 2026-05-25)"
$expectedCargoVersion = "cargo 1.96.0 (30a34c682 2026-05-25)"
$tempRoot = [System.IO.Path]::GetFullPath("C:\Users\developer\tmp")
$sourceRoot = [System.IO.Path]::GetFullPath($SakuraInputRoot)
$dictionaryPathResolved = [System.IO.Path]::GetFullPath($DictionaryPath)
$outputBinaryResolved = [System.IO.Path]::GetFullPath($OutputBinary)
$identityManifestResolved = [System.IO.Path]::GetFullPath($IdentityManifest)
$buildRootResolved = [System.IO.Path]::GetFullPath($BuildRoot)

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

function Assert-GitClean([string]$Root, [string]$Field) {
    $status = Get-RtkText @("git", "-C", $Root, "status", "--porcelain=v1", "--untracked-files=all")
    if ($status) {
        throw "$Field has staged, unstaged, or untracked changes"
    }
    & rtk git -C $Root diff --quiet --exit-code
    if ($LASTEXITCODE -ne 0) {
        throw "$Field has unstaged changes"
    }
    & rtk git -C $Root diff --cached --quiet --exit-code
    if ($LASTEXITCODE -ne 0) {
        throw "$Field has staged changes"
    }
}

Assert-UnderTempRoot $sourceRoot "SakuraInputRoot"
Assert-UnderTempRoot $dictionaryPathResolved "DictionaryPath"
Assert-UnderTempRoot $outputBinaryResolved "OutputBinary"
Assert-UnderTempRoot $identityManifestResolved "IdentityManifest"
Assert-UnderTempRoot $buildRootResolved "BuildRoot"
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

$sakuraHead = Get-RtkText @("git", "-C", $sourceRoot, "rev-parse", "HEAD")
if ($sakuraHead -ne $expectedSakuraHead) {
    throw "SakuraInputRoot is not the pinned HEAD"
}
Assert-GitClean $sourceRoot "SakuraInputRoot"
$dictionarySha256 = Get-Sha256 $dictionaryPathResolved
if ($dictionarySha256 -ne $expectedDictionarySha256) {
    throw "DictionaryPath does not match the pinned SHA-256"
}

$exporterGitSha = Get-RtkText @("git", "-C", $repoRoot, "rev-parse", "HEAD")
if ($exporterGitSha -notmatch "^[0-9a-f]{40}$") {
    throw "repository HEAD is not a full lowercase Git SHA"
}
Assert-GitClean $repoRoot "sakura-rerank source"

$runRoot = Join-Path $buildRootResolved ("run-" + [Guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $runRoot "sakura-rerank-source.zip"
$archiveRoot = Join-Path $runRoot "sakura-rerank-source"
$worktree = Join-Path $runRoot "sakura-input"
$targetDir = Join-Path $runRoot "target"
$worktreeAdded = $false
$publishedOutput = $false
$publishedManifest = $false
$environmentNames = @(
    "RUSTFLAGS",
    "CARGO_ENCODED_RUSTFLAGS",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "RUSTDOCFLAGS",
    "CARGO_TARGET_DIR",
    "CARGO_BUILD_TARGET",
    "CARGO_BUILD_RUSTC",
    "CARGO_INCREMENTAL",
    "CARGO_NET_OFFLINE",
    "CARGO_PROFILE_RELEASE_CODEGEN_UNITS",
    "CARGO_PROFILE_RELEASE_DEBUG",
    "CARGO_PROFILE_RELEASE_LTO",
    "CARGO_PROFILE_RELEASE_OPT_LEVEL",
    "CARGO_PROFILE_RELEASE_PANIC",
    "CARGO_PROFILE_RELEASE_STRIP",
    "RUSTUP_TOOLCHAIN",
    "RUSTC",
    "RUSTC_BOOTSTRAP",
    "SOURCE_DATE_EPOCH",
    "SAKURA_RERANK_EXPORTER_GIT_SHA",
    "SAKURA_RERANK_PATCH_SHA256",
    "SAKURA_RERANK_CARGO_LOCK_SHA256",
    "SAKURA_RERANK_RUSTC_VERSION",
    "SAKURA_RERANK_CARGO_VERSION"
)
$oldEnvironment = @{}
foreach ($name in $environmentNames) {
    $oldEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
    if ($oldEnvironment[$name]) {
        throw "build-affecting environment variable $name must be unset before a verified build"
    }
}

try {
    New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
    Invoke-RtkChecked @("git", "-C", $repoRoot, "archive", "--format=zip", "--output=$archivePath", $exporterGitSha, "--", "research/exporter", "research/patches/sakura-input-research-top32.patch", "research/lock/sakura-input-research-top32.Cargo.lock")
    Expand-Archive -LiteralPath $archivePath -DestinationPath $archiveRoot -Force

    $archivedSource = Join-Path $archiveRoot "research\exporter"
    $archivedPatch = Join-Path $archiveRoot "research\patches\sakura-input-research-top32.patch"
    $archivedLock = Join-Path $archiveRoot "research\lock\sakura-input-research-top32.Cargo.lock"
    foreach ($path in @($archivedSource, $archivedPatch, $archivedLock)) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "Git archive is missing the exact tracked build input: $path"
        }
    }
    $patchSha256 = Get-Sha256 $archivedPatch
    $cargoLockSha256 = Get-Sha256 $archivedLock

    Invoke-RtkChecked @("git", "-C", $sourceRoot, "worktree", "add", "--detach", $worktree, $expectedSakuraHead)
    $worktreeAdded = $true
    Invoke-RtkChecked @("git", "-C", $worktree, "apply", "--unidiff-zero", $archivedPatch)

    $destinationResearch = Join-Path $worktree "research"
    New-Item -ItemType Directory -Path $destinationResearch -Force | Out-Null
    Copy-Item -LiteralPath $archivedSource -Destination (Join-Path $destinationResearch "exporter") -Recurse
    [System.IO.File]::Copy($archivedLock, (Join-Path $worktree "Cargo.lock"), $true)

    $rootManifestPath = Join-Path $worktree "Cargo.toml"
    $rootManifest = [System.IO.File]::ReadAllText($rootManifestPath)
    $rootManifest = $rootManifest.Replace("`r`n", "`n").Replace("`r", "`n")
    $member = '    "crates/sakura-neural-worker",'
    if (($rootManifest.Split($member).Length - 1) -ne 1) {
        throw "Sakura Input workspace member anchor is missing or ambiguous"
    }
    $rootManifest = $rootManifest.Replace($member, "$member`n    `"research/exporter`",")
    Write-Utf8 $rootManifestPath $rootManifest

    $env:RUSTUP_TOOLCHAIN = $expectedToolchain
    $env:CARGO_BUILD_TARGET = $expectedTarget
    $env:CARGO_INCREMENTAL = "0"
    $env:CARGO_NET_OFFLINE = "true"
    $env:CARGO_PROFILE_RELEASE_CODEGEN_UNITS = "1"
    $env:CARGO_PROFILE_RELEASE_DEBUG = "0"
    $env:CARGO_PROFILE_RELEASE_LTO = "fat"
    $env:CARGO_PROFILE_RELEASE_OPT_LEVEL = "3"
    $env:CARGO_PROFILE_RELEASE_PANIC = "abort"
    $env:CARGO_PROFILE_RELEASE_STRIP = "true"
    $env:SOURCE_DATE_EPOCH = "0"
    $worktreeForRust = $worktree.Replace("\", "/")
    $env:RUSTFLAGS = "--remap-path-prefix=$worktreeForRust=/sakura-input -C link-arg=/Brepro"

    $rustcVersion = Get-RtkText @("proxy", "rustc", "--version")
    $cargoVersion = Get-RtkText @("proxy", "cargo", "--version")
    if ($rustcVersion -ne $expectedRustcVersion -or $cargoVersion -ne $expectedCargoVersion) {
        throw "rustc/cargo version differs from the pinned toolchain"
    }
    $rustcDetails = Get-RtkText @("proxy", "rustc", "-vV")
    $hostLine = $rustcDetails -split "`r?`n" | Where-Object { $_ -like "host:*" } | Select-Object -First 1
    if (-not $hostLine -or $hostLine.Substring(5).Trim() -ne $expectedTarget) {
        throw "rustc target triple differs from the pinned target"
    }

    $env:SAKURA_RERANK_EXPORTER_GIT_SHA = $exporterGitSha
    $env:SAKURA_RERANK_PATCH_SHA256 = $patchSha256
    $env:SAKURA_RERANK_CARGO_LOCK_SHA256 = $cargoLockSha256
    $env:SAKURA_RERANK_RUSTC_VERSION = $rustcVersion
    $env:SAKURA_RERANK_CARGO_VERSION = $cargoVersion
    $workspaceManifest = Join-Path $worktree "Cargo.toml"
    Invoke-RtkChecked @("cargo", "build", "--locked", "--release", "--target", $expectedTarget, "--target-dir", $targetDir, "--manifest-path", $workspaceManifest, "--package", "sakura-research-top32-exporter")
    $builtBinary = Join-Path $targetDir "$expectedTarget\release\sakura-research-top32-exporter.exe"
    if (-not (Test-Path -LiteralPath $builtBinary -PathType Leaf)) {
        throw "release exporter binary was not produced"
    }
    if ((Get-Sha256 (Join-Path $worktree "Cargo.lock")) -ne $cargoLockSha256) {
        throw "build changed the tracked exact Cargo.lock input"
    }

    $outputParent = Split-Path -Parent $outputBinaryResolved
    $identityParent = Split-Path -Parent $identityManifestResolved
    New-Item -ItemType Directory -Path $outputParent -Force | Out-Null
    New-Item -ItemType Directory -Path $identityParent -Force | Out-Null
    [System.IO.File]::Copy($builtBinary, $outputBinaryResolved)
    $publishedOutput = $true
    $binarySha256 = Get-Sha256 $outputBinaryResolved
    $buildFlags = @(
        "--remap-path-prefix=<WORKSPACE>=/sakura-input",
        "-C",
        "link-arg=/Brepro"
    )
    $buildEnvironment = [ordered]@{
        CARGO_BUILD_TARGET = $expectedTarget
        CARGO_INCREMENTAL = "0"
        CARGO_NET_OFFLINE = "true"
        CARGO_PROFILE_RELEASE_CODEGEN_UNITS = "1"
        CARGO_PROFILE_RELEASE_DEBUG = "0"
        CARGO_PROFILE_RELEASE_LTO = "fat"
        CARGO_PROFILE_RELEASE_OPT_LEVEL = "3"
        CARGO_PROFILE_RELEASE_PANIC = "abort"
        CARGO_PROFILE_RELEASE_STRIP = "true"
        RUSTUP_TOOLCHAIN = $expectedToolchain
        SOURCE_DATE_EPOCH = "0"
    }
    $manifest = [ordered]@{
        schema_version = 2
        manifest_kind = "research_top32_exporter"
        verification_status = $VerificationStatus
        exporter_git_sha = $exporterGitSha
        exporter_binary_sha256 = $binarySha256
        sakura_input_head = $expectedSakuraHead
        dictionary_sha256 = $dictionarySha256
        instrumentation_patch_sha256 = $patchSha256
        cargo_lock_sha256 = $cargoLockSha256
        rustc_version = $rustcVersion
        cargo_version = $cargoVersion
        target_triple = $expectedTarget
        profile = "release"
        build_flags = $buildFlags
        build_environment = $buildEnvironment
        requested_limit = 32
        effective_converter_bound = 32
        user_dictionary_enabled = $false
    }
    Write-Utf8 $identityManifestResolved (($manifest | ConvertTo-Json -Depth 8) + "`n")
    $publishedManifest = $true
    Write-Output (ConvertTo-Json -InputObject ([ordered]@{
        status = "built"
        exporter_git_sha = $exporterGitSha
        exporter_binary_sha256 = $binarySha256
        instrumentation_patch_sha256 = $patchSha256
        cargo_lock_sha256 = $cargoLockSha256
        sakura_input_head = $expectedSakuraHead
        dictionary_sha256 = $dictionarySha256
        effective_converter_bound = 32
        output_binary = $outputBinaryResolved
        identity_manifest = $identityManifestResolved
    }) -Compress)
}
finally {
    foreach ($name in $environmentNames) {
        $oldValue = $oldEnvironment[$name]
        if ($null -eq $oldValue) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item "Env:$name" $oldValue
        }
    }
    if ($worktreeAdded) {
        try {
            Invoke-RtkChecked @("git", "-C", $sourceRoot, "worktree", "remove", "--force", $worktree)
        }
        catch {
            Write-Warning "could not remove temporary Sakura Input worktree: $worktree"
        }
    }
    if ($publishedOutput -and -not $publishedManifest) {
        Remove-Item -LiteralPath $outputBinaryResolved -Force -ErrorAction SilentlyContinue
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
