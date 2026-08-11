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
    [string]$VerificationStatus = "unverified",

    [ValidateSet("none", "temporary-write", "first-publish", "second-publish")]
    [string]$TestFailureInjection = "none",

    [string]$TestCargoMarker
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$expectedSakuraHead = "8e966dff456e4e7165e025f97c1f73327ff3f550"
$expectedDictionarySha256 = "6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad"
$expectedTarget = "x86_64-pc-windows-msvc"
$expectedToolchain = "1.96.0-x86_64-pc-windows-msvc"
$expectedRustcVersion = "rustc 1.96.0 (ac68faa20 2026-05-25)"
$expectedCargoVersion = "cargo 1.96.0 (30a34c682 2026-05-25)"

if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
    throw "USERPROFILE is required to resolve the verified temporary root"
}
$tempRoot = [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE "tmp"))

Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class SakuraExporterPathIdentity
{
    private const uint FileShareRead = 0x00000001;
    private const uint FileShareWrite = 0x00000002;
    private const uint FileShareDelete = 0x00000004;
    private const uint OpenExisting = 3;
    private const uint FileFlagBackupSemantics = 0x02000000;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(
        SafeFileHandle file,
        StringBuilder path,
        uint pathLength,
        uint flags);

    public static string Resolve(string path)
    {
        using (SafeFileHandle handle = CreateFile(
            path,
            0,
            FileShareRead | FileShareWrite | FileShareDelete,
            IntPtr.Zero,
            OpenExisting,
            FileFlagBackupSemantics,
            IntPtr.Zero))
        {
            if (handle.IsInvalid)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            var buffer = new StringBuilder(32768);
            uint length = GetFinalPathNameByHandle(handle, buffer, (uint)buffer.Capacity, 0);
            if (length == 0 || length >= buffer.Capacity)
            {
                throw new InvalidOperationException("final path name is unavailable");
            }
            string value = buffer.ToString();
            if (value.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
            {
                return @"\" + value.Substring(7);
            }
            if (value.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase))
            {
                return value.Substring(4);
            }
            return value;
        }
    }
}
'@

function Normalize-IdentityPath([string]$PathToNormalize) {
    $normalized = [System.IO.Path]::GetFullPath($PathToNormalize)
    while ($normalized.Length -gt 3 -and ($normalized.EndsWith("\") -or $normalized.EndsWith("/"))) {
        $normalized = $normalized.Substring(0, $normalized.Length - 1)
    }
    return $normalized
}

function Test-SameOrUnder([string]$Candidate, [string]$Root) {
    $candidateNormalized = Normalize-IdentityPath $Candidate
    $rootNormalized = Normalize-IdentityPath $Root
    if ($candidateNormalized.Equals($rootNormalized, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $candidateNormalized.StartsWith(
        $rootNormalized + "\",
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Get-PathIdentity(
    [string]$PathToCheck,
    [string]$Field,
    [ValidateSet("file", "directory")]
    [string]$Kind
) {
    if ([string]::IsNullOrWhiteSpace($PathToCheck)) {
        throw "$Field path is empty"
    }
    try {
        $logical = Normalize-IdentityPath $PathToCheck
    }
    catch {
        throw "$Field path cannot be resolved"
    }
    $exists = Test-Path -LiteralPath $logical
    if ($exists) {
        $isDirectory = Test-Path -LiteralPath $logical -PathType Container
        if ($Kind -eq "directory" -and -not $isDirectory) {
            throw "$Field is not a directory"
        }
        if ($Kind -eq "file" -and $isDirectory) {
            throw "$Field is a directory, not a file path"
        }
        try {
            $final = [SakuraExporterPathIdentity]::Resolve($logical)
        }
        catch {
            throw "$Field path identity cannot be confirmed"
        }
    }
    else {
        if ($Kind -eq "directory") {
            throw "$Field directory must already exist so its identity can be confirmed"
        }
        $parent = [System.IO.Path]::GetDirectoryName($logical)
        $leaf = [System.IO.Path]::GetFileName($logical)
        if ([string]::IsNullOrWhiteSpace($parent) -or [string]::IsNullOrWhiteSpace($leaf)) {
            throw "$Field path has no confirmable parent and leaf"
        }
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
            throw "$Field parent directory must already exist so its identity can be confirmed"
        }
        try {
            $finalParent = [SakuraExporterPathIdentity]::Resolve($parent)
            $final = Join-Path $finalParent $leaf
        }
        catch {
            throw "$Field parent path identity cannot be confirmed"
        }
    }
    try {
        $final = Normalize-IdentityPath $final
    }
    catch {
        throw "$Field resolved identity is invalid"
    }
    return [pscustomobject]@{
        Field = $Field
        Logical = $logical
        Final = $final
        Exists = $exists
    }
}

function Assert-UnderTempRoot($Identity, [string]$Field, $TempIdentity) {
    if (-not (Test-SameOrUnder $Identity.Final $TempIdentity.Final)) {
        throw "$Field must resolve under $($TempIdentity.Final)"
    }
}

function Assert-NoPathRelationship($Left, $Right, [string]$Description) {
    if ((Test-SameOrUnder $Left.Final $Right.Final) -or (Test-SameOrUnder $Right.Final $Left.Final)) {
        throw "$Description has a dangerous path relationship"
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

function Test-ByteArrayEqual([byte[]]$Left, [byte[]]$Right) {
    if ($Left.Length -ne $Right.Length) {
        return $false
    }
    for ($index = 0; $index -lt $Left.Length; $index++) {
        if ($Left[$index] -ne $Right[$index]) {
            return $false
        }
    }
    return $true
}

function Write-CreateNewBytes([string]$PathToWrite, [byte[]]$Bytes, [string]$FailurePoint) {
    if ($TestFailureInjection -eq $FailurePoint) {
        throw "test failure injection: $FailurePoint"
    }
    $stream = $null
    try {
        $stream = [System.IO.File]::Open(
            $PathToWrite,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $stream.Write($Bytes, 0, $Bytes.Length)
        $stream.Flush($true)
    }
    finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Assert-BinaryArtifact([string]$PathToCheck, [string]$ExpectedSha256) {
    $bytes = [System.IO.File]::ReadAllBytes($PathToCheck)
    if ($bytes.Length -lt 2 -or $bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) {
        throw "binary artifact is not an MZ executable"
    }
    $actualSha256 = Get-Sha256 $PathToCheck
    if ($actualSha256 -ne $ExpectedSha256) {
        throw "binary artifact hash changed during publication"
    }
    return $actualSha256
}

function Assert-ManifestArtifact(
    [string]$PathToCheck,
    [byte[]]$ExpectedBytes,
    $ExpectedManifest,
    [string]$ExpectedBinarySha256
) {
    $actualBytes = [System.IO.File]::ReadAllBytes($PathToCheck)
    if (-not (Test-ByteArrayEqual $actualBytes $ExpectedBytes)) {
        throw "identity manifest content changed during publication"
    }
    try {
        $actualManifest = ([System.Text.UTF8Encoding]::new($false)).GetString($actualBytes) | ConvertFrom-Json
    }
    catch {
        throw "identity manifest is not valid UTF-8 JSON after publication"
    }
    $expectedFields = @($ExpectedManifest.Keys)
    $actualFields = @($actualManifest.PSObject.Properties.Name)
    if ($actualFields.Count -ne $expectedFields.Count) {
        throw "identity manifest fields changed during publication"
    }
    foreach ($field in $expectedFields) {
        if ($null -eq $actualManifest.PSObject.Properties[$field]) {
            throw "identity manifest is missing $field after publication"
        }
        $expectedValue = ConvertTo-Json -InputObject $ExpectedManifest[$field] -Compress -Depth 8
        $actualValue = ConvertTo-Json -InputObject $actualManifest.$field -Compress -Depth 8
        if ($actualValue -ne $expectedValue) {
            throw "identity manifest field $field changed during publication"
        }
    }
    if ($actualManifest.exporter_binary_sha256 -ne $ExpectedBinarySha256) {
        throw "identity manifest binary hash does not match the published binary"
    }
}

function Assert-TargetStillSafe($Identity, [string]$Field) {
    $current = Get-PathIdentity $Identity.Logical $Field "file"
    if ($current.Exists) {
        throw "$Field appeared before publication"
    }
    if (-not $current.Final.Equals($Identity.Final, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Field path identity changed before publication"
    }
}

function Assert-TempInTargetDirectory(
    [string]$TemporaryPath,
    $TargetParentIdentity,
    [string]$Field
) {
    $temporaryIdentity = Get-PathIdentity $TemporaryPath $Field "file"
    $expectedParent = Normalize-IdentityPath $TargetParentIdentity.Final
    $actualParent = Normalize-IdentityPath ([System.IO.Path]::GetDirectoryName($temporaryIdentity.Final))
    if (-not $actualParent.Equals($expectedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Field temporary file is outside its target directory"
    }
}

function Publish-NoOverwrite(
    [string]$TemporaryPath,
    [string]$TargetPath,
    [string]$FailurePoint
) {
    if ($TestFailureInjection -eq $FailurePoint) {
        throw "test failure injection: $FailurePoint"
    }
    if (Test-Path -LiteralPath $TargetPath) {
        throw "publication target already exists"
    }
    try {
        [System.IO.File]::Move($TemporaryPath, $TargetPath)
    }
    catch {
        throw "cannot publish without overwriting an existing target"
    }
}

function Remove-FileIfPresent([string]$PathToRemove) {
    if ([System.IO.File]::Exists($PathToRemove)) {
        [System.IO.File]::Delete($PathToRemove)
    }
}

function Remove-DirectoryTree([string]$PathToRemove) {
    if (-not [System.IO.Directory]::Exists($PathToRemove)) {
        return
    }
    try {
        [System.IO.Directory]::Delete($PathToRemove, $true)
    }
    catch [System.UnauthorizedAccessException] {
        foreach ($file in [System.IO.Directory]::EnumerateFiles($PathToRemove, "*", [System.IO.SearchOption]::AllDirectories)) {
            $attributes = [System.IO.File]::GetAttributes($file)
            if (($attributes -band [System.IO.FileAttributes]::ReadOnly) -ne 0) {
                [System.IO.File]::SetAttributes($file, $attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly))
            }
        }
        [System.IO.Directory]::Delete($PathToRemove, $true)
    }
}

function Remove-PublishedIfOwned(
    [string]$PathToRemove,
    [byte[]]$ExpectedBytes,
    [string]$Field
) {
    if (-not [System.IO.File]::Exists($PathToRemove)) {
        return
    }
    $actualBytes = [System.IO.File]::ReadAllBytes($PathToRemove)
    if (-not (Test-ByteArrayEqual $actualBytes $ExpectedBytes)) {
        throw "$Field changed before rollback and will not be deleted"
    }
    [System.IO.File]::Delete($PathToRemove)
}

$tempIdentity = Get-PathIdentity $tempRoot "USERPROFILE temp root" "directory"
$sourceIdentity = Get-PathIdentity $SakuraInputRoot "SakuraInputRoot" "directory"
$dictionaryIdentity = Get-PathIdentity $DictionaryPath "DictionaryPath" "file"
$outputIdentity = Get-PathIdentity $OutputBinary "OutputBinary" "file"
$manifestIdentity = Get-PathIdentity $IdentityManifest "IdentityManifest" "file"
$buildRootIdentity = Get-PathIdentity $BuildRoot "BuildRoot" "directory"
$repoIdentity = Get-PathIdentity $repoRoot "sakura-rerank source" "directory"
$testCargoMarkerIdentity = $null
if ($TestCargoMarker) {
    $testCargoMarkerIdentity = Get-PathIdentity $TestCargoMarker "TestCargoMarker" "file"
}

foreach ($identity in @(
        $sourceIdentity,
        $dictionaryIdentity,
        $outputIdentity,
        $manifestIdentity,
        $buildRootIdentity,
        $testCargoMarkerIdentity
    )) {
    if ($null -ne $identity) {
        Assert-UnderTempRoot $identity $identity.Field $tempIdentity
    }
}

Assert-NoPathRelationship $outputIdentity $manifestIdentity "OutputBinary and IdentityManifest"
Assert-NoPathRelationship $outputIdentity $buildRootIdentity "OutputBinary and BuildRoot"
Assert-NoPathRelationship $manifestIdentity $buildRootIdentity "IdentityManifest and BuildRoot"
foreach ($publicationIdentity in @($outputIdentity, $manifestIdentity, $buildRootIdentity)) {
    Assert-NoPathRelationship $publicationIdentity $sourceIdentity "$($publicationIdentity.Field) and SakuraInputRoot"
    Assert-NoPathRelationship $publicationIdentity $repoIdentity "$($publicationIdentity.Field) and sakura-rerank source"
    Assert-NoPathRelationship $publicationIdentity $dictionaryIdentity "$($publicationIdentity.Field) and DictionaryPath"
}

if ($outputIdentity.Exists) {
    throw "OutputBinary already exists"
}
if ($manifestIdentity.Exists) {
    throw "IdentityManifest already exists"
}
if ($null -ne $testCargoMarkerIdentity -and $testCargoMarkerIdentity.Exists) {
    throw "TestCargoMarker already exists"
}

$outputParentLogical = [System.IO.Path]::GetDirectoryName($outputIdentity.Logical)
$manifestParentLogical = [System.IO.Path]::GetDirectoryName($manifestIdentity.Logical)
$outputParentIdentity = Get-PathIdentity $outputParentLogical "OutputBinary parent" "directory"
$manifestParentIdentity = Get-PathIdentity $manifestParentLogical "IdentityManifest parent" "directory"
Assert-UnderTempRoot $outputParentIdentity "OutputBinary parent" $tempIdentity
Assert-UnderTempRoot $manifestParentIdentity "IdentityManifest parent" $tempIdentity

$sakuraHead = Get-RtkText @("git", "-C", $sourceIdentity.Logical, "rev-parse", "HEAD")
if ($sakuraHead -ne $expectedSakuraHead) {
    throw "SakuraInputRoot is not the pinned HEAD"
}
Assert-GitClean $sourceIdentity.Logical "SakuraInputRoot"
$dictionarySha256 = Get-Sha256 $dictionaryIdentity.Logical
if ($dictionarySha256 -ne $expectedDictionarySha256) {
    throw "DictionaryPath does not match the pinned SHA-256"
}

$exporterGitSha = Get-RtkText @("git", "-C", $repoIdentity.Logical, "rev-parse", "HEAD")
if ($exporterGitSha -notmatch "^[0-9a-f]{40}$") {
    throw "repository HEAD is not a full lowercase Git SHA"
}
Assert-GitClean $repoIdentity.Logical "sakura-rerank source"

$runRoot = Join-Path $buildRootIdentity.Logical ("run-" + [Guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $runRoot "sakura-rerank-source.zip"
$archiveRoot = Join-Path $runRoot "sakura-rerank-source"
$worktree = Join-Path $runRoot "sakura-input"
$targetDir = Join-Path $runRoot "target"
$worktreeAdded = $false
$publishedOutput = $false
$publishedManifest = $false
$publicationSucceeded = $false
$outputTemp = $null
$manifestTemp = $null
$outputBytes = $null
$manifestBytes = $null
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
    New-Item -ItemType Directory -Path $runRoot | Out-Null
    Invoke-RtkChecked @("git", "-C", $repoIdentity.Logical, "archive", "--format=zip", "--output=$archivePath", $exporterGitSha, "--", "research/exporter", "research/patches/sakura-input-research-top32.patch", "research/lock/sakura-input-research-top32.Cargo.lock")
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

    Invoke-RtkChecked @("git", "-C", $sourceIdentity.Logical, "worktree", "add", "--detach", $worktree, $expectedSakuraHead)
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

    $rustcVersion = Get-RtkText @("proxy", "rustc", "+$expectedToolchain", "--version")
    $cargoVersion = Get-RtkText @("proxy", "cargo", "+$expectedToolchain", "--version")
    if ($rustcVersion -ne $expectedRustcVersion -or $cargoVersion -ne $expectedCargoVersion) {
        throw "rustc/cargo version differs from the pinned toolchain"
    }
    $rustcDetails = Get-RtkText @("proxy", "rustc", "+$expectedToolchain", "-vV")
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
    if ($TestCargoMarker) {
        Write-Utf8 $TestCargoMarker "cargo-started`n"
    }
    Invoke-RtkChecked @("cargo", "+$expectedToolchain", "build", "--locked", "--release", "--target", $expectedTarget, "--target-dir", $targetDir, "--manifest-path", $workspaceManifest, "--package", "sakura-research-top32-exporter")
    $builtBinary = Join-Path $targetDir "$expectedTarget\release\sakura-research-top32-exporter.exe"
    if (-not (Test-Path -LiteralPath $builtBinary -PathType Leaf)) {
        throw "release exporter binary was not produced"
    }
    if ((Get-Sha256 (Join-Path $worktree "Cargo.lock")) -ne $cargoLockSha256) {
        throw "build changed the tracked exact Cargo.lock input"
    }

    $outputBytes = [System.IO.File]::ReadAllBytes($builtBinary)
    $binarySha256 = Assert-BinaryArtifact $builtBinary (Get-Sha256 $builtBinary)
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
    $manifestJson = ($manifest | ConvertTo-Json -Depth 8) + "`n"
    $manifestBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($manifestJson)

    Assert-TargetStillSafe $outputIdentity "OutputBinary"
    Assert-TargetStillSafe $manifestIdentity "IdentityManifest"
    $tempToken = [Guid]::NewGuid().ToString("N")
    $outputLeaf = [System.IO.Path]::GetFileName($outputIdentity.Logical)
    $manifestLeaf = [System.IO.Path]::GetFileName($manifestIdentity.Logical)
    $outputTemp = Join-Path $outputParentLogical ".${outputLeaf}.research-exporter-$([System.Diagnostics.Process]::GetCurrentProcess().Id)-$tempToken-output.tmp"
    $manifestTemp = Join-Path $manifestParentLogical ".${manifestLeaf}.research-exporter-$([System.Diagnostics.Process]::GetCurrentProcess().Id)-$tempToken-manifest.tmp"
    Write-CreateNewBytes $outputTemp $outputBytes "temporary-write"
    Write-CreateNewBytes $manifestTemp $manifestBytes "temporary-write"
    Assert-TempInTargetDirectory $outputTemp $outputParentIdentity "OutputBinary"
    Assert-TempInTargetDirectory $manifestTemp $manifestParentIdentity "IdentityManifest"
    Assert-TargetStillSafe $outputIdentity "OutputBinary"
    Assert-TargetStillSafe $manifestIdentity "IdentityManifest"
    [void](Assert-BinaryArtifact $outputTemp $binarySha256)
    Assert-ManifestArtifact $manifestTemp $manifestBytes $manifest $binarySha256

    Publish-NoOverwrite $outputTemp $outputIdentity.Logical "first-publish"
    $publishedOutput = $true
    Publish-NoOverwrite $manifestTemp $manifestIdentity.Logical "second-publish"
    $publishedManifest = $true

    $publishedBinarySha256 = Assert-BinaryArtifact $outputIdentity.Logical $binarySha256
    if ($publishedBinarySha256 -ne $manifest.exporter_binary_sha256) {
        throw "published binary hash does not match the identity manifest"
    }
    Assert-ManifestArtifact $manifestIdentity.Logical $manifestBytes $manifest $publishedBinarySha256
    $publicationSucceeded = $true
    Write-Output (ConvertTo-Json -InputObject ([ordered]@{
        status = "built"
        exporter_git_sha = $exporterGitSha
        exporter_binary_sha256 = $binarySha256
        instrumentation_patch_sha256 = $patchSha256
        cargo_lock_sha256 = $cargoLockSha256
        sakura_input_head = $expectedSakuraHead
        dictionary_sha256 = $dictionarySha256
        effective_converter_bound = 32
        output_binary = $outputIdentity.Logical
        identity_manifest = $manifestIdentity.Logical
    }) -Compress)
}
finally {
    $cleanupErrors = New-Object System.Collections.Generic.List[string]
    if (-not $publicationSucceeded) {
        try {
            if ($publishedManifest -and $null -ne $manifestBytes) {
                Remove-PublishedIfOwned $manifestIdentity.Logical $manifestBytes "IdentityManifest"
            }
            if ($publishedOutput -and $null -ne $outputBytes) {
                Remove-PublishedIfOwned $outputIdentity.Logical $outputBytes "OutputBinary"
            }
        }
        catch {
            [void]$cleanupErrors.Add($_.Exception.Message)
        }
    }
    foreach ($temporaryPath in @($outputTemp, $manifestTemp)) {
        if ($temporaryPath) {
            try {
                Remove-FileIfPresent $temporaryPath
            }
            catch {
                [void]$cleanupErrors.Add("could not remove temporary file ${temporaryPath}: $($_.Exception.Message)")
            }
        }
    }
    if ($worktreeAdded) {
        try {
            Invoke-RtkChecked @("git", "-C", $sourceIdentity.Logical, "worktree", "remove", "--force", $worktree)
        }
        catch {
            [void]$cleanupErrors.Add("could not remove temporary Sakura Input worktree ${worktree}: $($_.Exception.Message)")
        }
    }
    if (Test-Path -LiteralPath $runRoot) {
        try {
            Remove-DirectoryTree $runRoot
        }
        catch {
            [void]$cleanupErrors.Add("could not remove temporary build root ${runRoot}: $($_.Exception.Message)")
        }
    }
    foreach ($name in $environmentNames) {
        try {
            $oldValue = $oldEnvironment[$name]
            if ($null -eq $oldValue) {
                Remove-Item "Env:$name" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item "Env:$name" $oldValue
            }
        }
        catch {
            [void]$cleanupErrors.Add("could not restore environment variable ${name}: $($_.Exception.Message)")
        }
    }
    if ($cleanupErrors.Count -gt 0) {
        throw ("cleanup failed: " + ($cleanupErrors -join "; "))
    }
}
