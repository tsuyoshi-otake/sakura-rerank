$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$sakuraInputRoot = "C:\Users\developer\tmp\issue3-clean-input-c"
$dictionaryPath = "C:\Users\developer\tmp\sakura-input-dictionary-rebuild-20260811\system.dic"
$buildScript = Join-Path $repoRoot "scripts\build_research_top32_exporter.ps1"
$tempRoot = [System.IO.Path]::GetFullPath("C:\Users\developer\tmp")
$testRoot = Join-Path $tempRoot ("issue3-build-preflight-" + [Guid]::NewGuid().ToString("N"))
$wrongSakuraRoot = Join-Path $testRoot "wrong-sakura-source"
$wrongDictionary = Join-Path $testRoot "wrong.dic"
$dirtyMarker = Join-Path $repoRoot ".issue3-build-preflight-dirty-marker"
$wrongWorktreeAdded = $false

function Invoke-ExpectedFailure(
    [string]$Name,
    [string]$InputRoot,
    [string]$Dictionary
) {
    $caseRoot = Join-Path $testRoot $Name
    New-Item -ItemType Directory -Path $caseRoot -Force | Out-Null
    $arguments = @(
        "proxy", "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $buildScript,
        "-SakuraInputRoot", $InputRoot,
        "-DictionaryPath", $Dictionary,
        "-OutputBinary", (Join-Path $caseRoot "exporter.exe"),
        "-IdentityManifest", (Join-Path $caseRoot "identity.json"),
        "-BuildRoot", $caseRoot,
        "-VerificationStatus", "unverified"
    )
    & rtk @arguments *> $null
    if ($LASTEXITCODE -eq 0) {
        throw "$Name unexpectedly passed preflight"
    }
    if (@([System.IO.Directory]::EnumerateFileSystemEntries($caseRoot)).Count -ne 0) {
        throw "$Name left preflight residue"
    }
}

try {
    if (Test-Path -LiteralPath $testRoot) {
        throw "test root already exists: $testRoot"
    }
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    [System.IO.File]::WriteAllBytes($wrongDictionary, [byte[]](0x00))

    Invoke-ExpectedFailure "wrong-dictionary" $sakuraInputRoot $wrongDictionary

    & rtk git -C C:\Codes\tsuyoshi-otake\sakura-input worktree add --detach $wrongSakuraRoot "8e966dff456e4e7165e025f97c1f73327ff3f550^"
    if ($LASTEXITCODE -ne 0) {
        throw "could not create wrong-HEAD Sakura Input worktree"
    }
    $wrongWorktreeAdded = $true
    Invoke-ExpectedFailure "wrong-sakura-head" $wrongSakuraRoot $dictionaryPath

    [System.IO.File]::WriteAllText($dirtyMarker, "preflight marker`n", [System.Text.UTF8Encoding]::new($false))
    try {
        Invoke-ExpectedFailure "dirty-rerank-source" $sakuraInputRoot $dictionaryPath
    }
    finally {
        Remove-Item -LiteralPath $dirtyMarker -Force -ErrorAction SilentlyContinue
    }
    Write-Output "preflight-negative-tests-passed"
}
finally {
    Remove-Item -LiteralPath $dirtyMarker -Force -ErrorAction SilentlyContinue
    if ($wrongWorktreeAdded) {
        & rtk git -C C:\Codes\tsuyoshi-otake\sakura-input worktree remove --force $wrongSakuraRoot
    }
    if (Test-Path -LiteralPath $testRoot) {
        [System.IO.Directory]::Delete($testRoot, $true)
    }
}
