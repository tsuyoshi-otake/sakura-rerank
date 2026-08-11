[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SakuraInputRoot,

    [Parameter(Mandatory = $true)]
    [string]$DictionaryPath
)

$ErrorActionPreference = "Stop"
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$buildScript = Join-Path $repoRoot "scripts\build_research_top32_exporter.ps1"
$expectedSakuraHead = "8e966dff456e4e7165e025f97c1f73327ff3f550"
$tempRoot = [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE "tmp"))
$testRoot = Join-Path $tempRoot ("issue3-build-preflight-" + [Guid]::NewGuid().ToString("N"))
$markerRoot = Join-Path $testRoot "cargo-markers"
$wrongSakuraRoot = Join-Path $testRoot "wrong-sakura-source"
$wrongDictionary = Join-Path $testRoot "wrong.dic"
$dirtyMarker = Join-Path $repoRoot (".issue3-build-preflight-dirty-marker-" + [Guid]::NewGuid().ToString("N"))
$wrongWorktreeAdded = $false

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

function Assert-BuildRootEmpty([string]$BuildRoot) {
    if (-not [System.IO.Directory]::Exists($BuildRoot)) {
        throw "build root disappeared: $BuildRoot"
    }
    if (@([System.IO.Directory]::EnumerateFileSystemEntries($BuildRoot)).Count -ne 0) {
        throw "build root retained a run directory: $BuildRoot"
    }
}

function Assert-NoExporterResidue(
    [string]$CaseRoot,
    [string]$OutputPath,
    [string]$ManifestPath,
    [string]$ExpectedExistingOutputSha256
) {
    if ([System.IO.File]::Exists($OutputPath)) {
        if (-not $ExpectedExistingOutputSha256 -or (Get-Sha256 $OutputPath) -ne $ExpectedExistingOutputSha256) {
            throw "output target remained or changed: $OutputPath"
        }
    }
    if ([System.IO.File]::Exists($ManifestPath)) {
        throw "manifest target remained: $ManifestPath"
    }
    foreach ($entry in [System.IO.Directory]::EnumerateFileSystemEntries(
        $CaseRoot,
        "*",
        [System.IO.SearchOption]::AllDirectories
    )) {
        try {
            $attributes = [System.IO.File]::GetAttributes($entry)
        }
        catch {
            continue
        }
        if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            continue
        }
        $leaf = [System.IO.Path]::GetFileName($entry)
        if ($leaf -like "run-*" -or $leaf -like ".*.research-exporter-*" -or $leaf -like "*.bak") {
            throw "exporter residue remained: $entry"
        }
    }
}

function Remove-TestJunction([string]$PathToRemove) {
    if (Test-Path -LiteralPath $PathToRemove) {
        Remove-Item -LiteralPath $PathToRemove -Force
    }
}

function Invoke-BuildCase(
    [string]$InputRoot,
    [string]$Dictionary,
    [string]$OutputPath,
    [string]$ManifestPath,
    [string]$BuildRoot,
    [string]$MarkerPath,
    [ValidateSet("none", "temporary-write", "first-publish", "second-publish")]
    [string]$FailureInjection = "none"
) {
    $arguments = @(
        "proxy", "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $buildScript,
        "-SakuraInputRoot", $InputRoot,
        "-DictionaryPath", $Dictionary,
        "-OutputBinary", $OutputPath,
        "-IdentityManifest", $ManifestPath,
        "-BuildRoot", $BuildRoot,
        "-VerificationStatus", "unverified",
        "-TestCargoMarker", $MarkerPath
    )
    if ($FailureInjection -ne "none") {
        $arguments += @("-TestFailureInjection", $FailureInjection)
    }
    & rtk @arguments *> $null
    return $LASTEXITCODE
}

function Invoke-ExpectedFailure(
    [string]$Name,
    [string]$InputRoot,
    [string]$Dictionary,
    [string]$OutputPath,
    [string]$ManifestPath,
    [string]$BuildRoot,
    [bool]$ExpectCargo = $false,
    [string]$ExpectedExistingOutputSha256
) {
    $caseRoot = Join-Path $testRoot $Name
    $markerPath = Join-Path $markerRoot "$Name.marker"
    New-Item -ItemType Directory -Path $caseRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
    $exitCode = Invoke-BuildCase $InputRoot $Dictionary $OutputPath $ManifestPath $BuildRoot $markerPath
    if ($exitCode -eq 0) {
        throw "$Name unexpectedly succeeded"
    }
    $cargoStarted = [System.IO.File]::Exists($markerPath)
    if ($cargoStarted -ne $ExpectCargo) {
        throw "$Name reached Cargo unexpectedly: expected=$ExpectCargo actual=$cargoStarted"
    }
    Assert-BuildRootEmpty $BuildRoot
    Assert-NoExporterResidue $caseRoot $OutputPath $ManifestPath $ExpectedExistingOutputSha256
}

function Invoke-ExpectedPublicationFailure(
    [string]$Name,
    [ValidateSet("temporary-write", "first-publish", "second-publish")]
    [string]$FailureInjection
) {
    $caseRoot = Join-Path $testRoot $Name
    $buildRoot = Join-Path $caseRoot "build"
    $outputPath = Join-Path $caseRoot "exporter.exe"
    $manifestPath = Join-Path $caseRoot "identity.json"
    $markerPath = Join-Path $markerRoot "$Name.marker"
    New-Item -ItemType Directory -Path $caseRoot, $buildRoot | Out-Null
    $exitCode = Invoke-BuildCase $SakuraInputRoot $DictionaryPath $outputPath $manifestPath $buildRoot $markerPath $FailureInjection
    if ($exitCode -eq 0) {
        throw "$Name unexpectedly succeeded"
    }
    if (-not [System.IO.File]::Exists($markerPath)) {
        throw "$Name did not reach the publication phase"
    }
    Assert-BuildRootEmpty $buildRoot
    Assert-NoExporterResidue $caseRoot $outputPath $manifestPath
}

function Invoke-ExpectedSuccess {
    $name = "successful-pair"
    $caseRoot = Join-Path $testRoot $name
    $buildRoot = Join-Path $caseRoot "build"
    $outputPath = Join-Path $caseRoot "exporter.exe"
    $manifestPath = Join-Path $caseRoot "identity.json"
    $markerPath = Join-Path $markerRoot "$name.marker"
    New-Item -ItemType Directory -Path $caseRoot, $buildRoot | Out-Null
    $arguments = @(
        "proxy", "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $buildScript,
        "-SakuraInputRoot", $SakuraInputRoot,
        "-DictionaryPath", $DictionaryPath,
        "-OutputBinary", $outputPath,
        "-IdentityManifest", $manifestPath,
        "-BuildRoot", $buildRoot,
        "-VerificationStatus", "unverified",
        "-TestCargoMarker", $markerPath
    )
    $output = (& rtk @arguments 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "successful-pair failed: $output"
    }
    $statusLine = $output -split "`r?`n" | Where-Object { $_.TrimStart().StartsWith("{") } | Select-Object -Last 1
    if (-not $statusLine) {
        throw "successful-pair did not emit a JSON status: $output"
    }
    $status = $statusLine | ConvertFrom-Json
    if ($status.status -ne "built") {
        throw "successful-pair did not report built"
    }
    $binaryBytes = [System.IO.File]::ReadAllBytes($outputPath)
    if ($binaryBytes.Length -lt 2 -or $binaryBytes[0] -ne 0x4d -or $binaryBytes[1] -ne 0x5a) {
        throw "successful-pair output is not an MZ executable"
    }
    $manifest = [System.IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
    if ((Get-Sha256 $outputPath) -ne $manifest.exporter_binary_sha256) {
        throw "successful-pair manifest hash does not match the binary"
    }
    Assert-BuildRootEmpty $buildRoot
    if ([System.IO.File]::Exists($markerPath)) {
        [System.IO.File]::Delete($markerPath)
    }
    [System.IO.Directory]::Delete($caseRoot, $true)
}

try {
    if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        throw "USERPROFILE is required"
    }
    if (-not [System.IO.Directory]::Exists($tempRoot)) {
        throw "temporary root does not exist: $tempRoot"
    }
    if ([System.IO.Directory]::Exists($testRoot)) {
        throw "test root already exists: $testRoot"
    }
    New-Item -ItemType Directory -Path $testRoot, $markerRoot | Out-Null
    [System.IO.File]::WriteAllBytes($wrongDictionary, [byte[]](0x00))

    $sameRoot = Join-Path $testRoot "same-output-manifest"
    $sameBuild = Join-Path $sameRoot "build"
    $samePath = Join-Path $sameRoot "artifact.exe"
    Invoke-ExpectedFailure "same-output-manifest" $SakuraInputRoot $DictionaryPath $samePath $samePath $sameBuild $false
    [System.IO.Directory]::Delete($sameRoot, $true)

    $caseRoot = Join-Path $testRoot "case-only-collision"
    $caseBuild = Join-Path $caseRoot "build"
    New-Item -ItemType Directory -Path $caseRoot, $caseBuild | Out-Null
    Invoke-ExpectedFailure "case-only-collision" $SakuraInputRoot $DictionaryPath (Join-Path $caseRoot "Case.exe") (Join-Path $caseRoot "case.EXE") $caseBuild $false
    [System.IO.Directory]::Delete($caseRoot, $true)

    $aliasRoot = Join-Path $testRoot "alias-parent-collision"
    $aliasBuild = Join-Path $aliasRoot "build"
    $realParent = Join-Path $aliasRoot "real"
    $aliasParent = Join-Path $aliasRoot "alias"
    New-Item -ItemType Directory -Path $aliasRoot, $aliasBuild, $realParent | Out-Null
    New-Item -ItemType Junction -Path $aliasParent -Target $realParent | Out-Null
    Invoke-ExpectedFailure "alias-parent-collision" $SakuraInputRoot $DictionaryPath (Join-Path $aliasParent "artifact.exe") (Join-Path $realParent "artifact.exe") $aliasBuild $false
    Remove-TestJunction $aliasParent
    [System.IO.Directory]::Delete($aliasRoot, $true)

    $sourcePublicationRoot = Join-Path $testRoot "source-tree-publication"
    $sourcePublicationBuild = Join-Path $sourcePublicationRoot "build"
    New-Item -ItemType Directory -Path $sourcePublicationRoot, $sourcePublicationBuild | Out-Null
    Invoke-ExpectedFailure "sakura-input-source-publication" $SakuraInputRoot $DictionaryPath (Join-Path $SakuraInputRoot "Cargo.toml") (Join-Path $sourcePublicationRoot "identity.json") $sourcePublicationBuild $false (Get-Sha256 (Join-Path $SakuraInputRoot "Cargo.toml"))
    [System.IO.Directory]::Delete($sourcePublicationRoot, $true)

    $rerankPublicationRoot = Join-Path $testRoot "rerank-source-publication"
    $rerankPublicationBuild = Join-Path $rerankPublicationRoot "build"
    New-Item -ItemType Directory -Path $rerankPublicationRoot, $rerankPublicationBuild | Out-Null
    Invoke-ExpectedFailure "rerank-source-publication" $SakuraInputRoot $DictionaryPath (Join-Path $repoRoot "README.md") (Join-Path $rerankPublicationRoot "identity.json") $rerankPublicationBuild $false (Get-Sha256 (Join-Path $repoRoot "README.md"))
    [System.IO.Directory]::Delete($rerankPublicationRoot, $true)

    $containmentRoot = Join-Path $testRoot "build-containment"
    $containmentBuild = Join-Path $containmentRoot "build"
    New-Item -ItemType Directory -Path $containmentRoot, $containmentBuild | Out-Null
    Invoke-ExpectedFailure "output-under-build-root" $SakuraInputRoot $DictionaryPath (Join-Path $containmentBuild "exporter.exe") (Join-Path $containmentRoot "identity.json") $containmentBuild $false
    [System.IO.Directory]::Delete($containmentRoot, $true)

    $missingRoot = Join-Path $testRoot "unconfirmable-parent"
    $missingBuild = Join-Path $missingRoot "build"
    New-Item -ItemType Directory -Path $missingRoot, $missingBuild | Out-Null
    Invoke-ExpectedFailure "unconfirmable-parent" $SakuraInputRoot $DictionaryPath (Join-Path $missingRoot "missing\exporter.exe") (Join-Path $missingRoot "identity.json") $missingBuild $false
    [System.IO.Directory]::Delete($missingRoot, $true)

    Invoke-ExpectedFailure "wrong-dictionary" $SakuraInputRoot $wrongDictionary (Join-Path $testRoot "wrong-dictionary\exporter.exe") (Join-Path $testRoot "wrong-dictionary\identity.json") (Join-Path $testRoot "wrong-dictionary\build") $false
    [System.IO.Directory]::Delete((Join-Path $testRoot "wrong-dictionary"), $true)

    & rtk git -C $SakuraInputRoot worktree add --detach $wrongSakuraRoot "$expectedSakuraHead^" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "could not create wrong-HEAD Sakura Input fixture worktree"
    }
    $wrongWorktreeAdded = $true
    Invoke-ExpectedFailure "wrong-sakura-head" $wrongSakuraRoot $DictionaryPath (Join-Path $testRoot "wrong-sakura-head\exporter.exe") (Join-Path $testRoot "wrong-sakura-head\identity.json") (Join-Path $testRoot "wrong-sakura-head\build") $false
    [System.IO.Directory]::Delete((Join-Path $testRoot "wrong-sakura-head"), $true)

    [System.IO.File]::WriteAllText($dirtyMarker, "preflight marker`n", [System.Text.UTF8Encoding]::new($false))
    try {
        Invoke-ExpectedFailure "dirty-rerank-source" $SakuraInputRoot $DictionaryPath (Join-Path $testRoot "dirty-rerank-source\exporter.exe") (Join-Path $testRoot "dirty-rerank-source\identity.json") (Join-Path $testRoot "dirty-rerank-source\build") $false
    }
    finally {
        if ([System.IO.File]::Exists($dirtyMarker)) {
            [System.IO.File]::Delete($dirtyMarker)
        }
        [System.IO.Directory]::Delete((Join-Path $testRoot "dirty-rerank-source"), $true)
    }

    Invoke-ExpectedPublicationFailure "temporary-write-failure" "temporary-write"
    [System.IO.Directory]::Delete((Join-Path $testRoot "temporary-write-failure"), $true)
    Invoke-ExpectedPublicationFailure "first-publish-failure" "first-publish"
    [System.IO.Directory]::Delete((Join-Path $testRoot "first-publish-failure"), $true)
    Invoke-ExpectedPublicationFailure "second-publish-failure" "second-publish"
    [System.IO.Directory]::Delete((Join-Path $testRoot "second-publish-failure"), $true)

    Invoke-ExpectedSuccess
    Write-Output "exporter-build-preflight-and-publication-tests-passed"
}
finally {
    if ([System.IO.File]::Exists($dirtyMarker)) {
        [System.IO.File]::Delete($dirtyMarker)
    }
    if ($wrongWorktreeAdded) {
        & rtk git -C $SakuraInputRoot worktree remove --force $wrongSakuraRoot *> $null
    }
    if ($aliasParent -and (Test-Path -LiteralPath $aliasParent)) {
        Remove-TestJunction $aliasParent
    }
    if ([System.IO.Directory]::Exists($testRoot)) {
        [System.IO.Directory]::Delete($testRoot, $true)
    }
}
