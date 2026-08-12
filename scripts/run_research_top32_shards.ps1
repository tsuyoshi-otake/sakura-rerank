[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$ExporterBinary,
    [Parameter(Mandatory = $true)] [string]$DictionaryPath,
    [Parameter(Mandatory = $true)] [string]$IdentityManifest,
    [Parameter(Mandatory = $true)] [string]$RequestDirectory,
    [Parameter(Mandatory = $true)] [string]$OutputDirectory,
    [ValidateRange(1, 3600)] [int]$ShardTimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
$maximumShards = 256

function Resolve-ExistingFile([string]$Path, [string]$Field) {
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not [IO.File]::Exists($resolved)) {
        throw "$Field must be an existing file"
    }
    return $resolved
}

function Resolve-ExistingDirectory([string]$Path, [string]$Field) {
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not [IO.Directory]::Exists($resolved)) {
        throw "$Field must be an existing directory"
    }
    return $resolved.TrimEnd('\', '/')
}

function Remove-OwnedDirectory([string]$Path, [string]$ExpectedParent) {
    if (-not [IO.Directory]::Exists($Path)) {
        return
    }
    $resolved = [IO.Path]::GetFullPath($Path)
    $parent = [IO.Directory]::GetParent($resolved)
    if ($null -eq $parent -or -not $parent.FullName.Equals(
        $ExpectedParent,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "refusing to remove a directory outside the validated output parent"
    }
    [IO.Directory]::Delete($resolved, $true)
}

$binary = Resolve-ExistingFile $ExporterBinary "ExporterBinary"
$dictionary = Resolve-ExistingFile $DictionaryPath "DictionaryPath"
$identity = Resolve-ExistingFile $IdentityManifest "IdentityManifest"
$requests = Resolve-ExistingDirectory $RequestDirectory "RequestDirectory"
$destination = [IO.Path]::GetFullPath($OutputDirectory).TrimEnd('\', '/')
$destinationParentInfo = [IO.Directory]::GetParent($destination)
if ($null -eq $destinationParentInfo -or -not $destinationParentInfo.Exists) {
    throw "OutputDirectory parent must exist"
}
$destinationParent = $destinationParentInfo.FullName.TrimEnd('\', '/')
if ([IO.Directory]::Exists($destination) -or [IO.File]::Exists($destination)) {
    throw "OutputDirectory must not already exist"
}

$manifestPath = Join-Path $requests "manifest.json"
if (-not [IO.File]::Exists($manifestPath) -or (Get-Item -LiteralPath $manifestPath).Length -gt 1MB) {
    throw "request manifest is missing or outside the byte bound"
}
$requestManifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$shardCount = $requestManifest.shard_count
if (
    ($shardCount -isnot [int] -and $shardCount -isnot [long]) -or
    $shardCount -lt 1 -or
    $shardCount -gt $maximumShards
) {
    throw "request manifest shard_count is outside the bound"
}
$shardCount = [int]$shardCount
if (@($requestManifest.shards).Count -ne $shardCount) {
    throw "request manifest shard list does not match shard_count"
}
for ($index = 0; $index -lt $shardCount; $index++) {
    $expectedName = "requests-{0:D5}.jsonl" -f $index
    if ($requestManifest.shards[$index].file_name -cne $expectedName) {
        throw "request manifest contains a non-canonical shard name"
    }
    $requestPath = Join-Path $requests $expectedName
    if (-not [IO.File]::Exists($requestPath) -or (Get-Item -LiteralPath $requestPath).Length -gt 4MB) {
        throw "request shard is missing or outside the byte bound"
    }
}

$stageName = ".{0}.{1}.tmp" -f ([IO.Path]::GetFileName($destination)), ([guid]::NewGuid().ToString("N"))
$stage = Join-Path $destinationParent $stageName
[IO.Directory]::CreateDirectory($stage) | Out-Null
$activeProcess = $null
try {
    for ($index = 0; $index -lt $shardCount; $index++) {
        $requestPath = Join-Path $requests ("requests-{0:D5}.jsonl" -f $index)
        $outputPath = Join-Path $stage ("output-{0:D5}.jsonl" -f $index)
        $reportPath = Join-Path $stage ("report-{0:D5}.json" -f $index)
        $stdoutPath = Join-Path $stage (".{0:D5}.stdout.tmp" -f $index)
        $stderrPath = Join-Path $stage (".{0:D5}.stderr.tmp" -f $index)
        $arguments = @(
            "--input", $requestPath,
            "--dictionary", $dictionary,
            "--output", $outputPath,
            "--report", $reportPath,
            "--identity-manifest", $identity,
            "--limit", "32"
        )
        $activeProcess = Start-Process -FilePath $binary -ArgumentList $arguments -NoNewWindow -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        if (-not $activeProcess.WaitForExit($ShardTimeoutSeconds * 1000)) {
            Stop-Process -Id $activeProcess.Id -Force -ErrorAction SilentlyContinue
            $activeProcess.WaitForExit()
            throw "export shard timed out"
        }
        if ($activeProcess.ExitCode -ne 0) {
            throw "export shard failed"
        }
        $activeProcess = $null
        [IO.File]::Delete($stdoutPath)
        [IO.File]::Delete($stderrPath)
    }
    [IO.Directory]::Move($stage, $destination)
    $stage = $null
}
finally {
    if ($null -ne $activeProcess -and -not $activeProcess.HasExited) {
        Stop-Process -Id $activeProcess.Id -Force -ErrorAction SilentlyContinue
        $activeProcess.WaitForExit()
    }
    if ($null -ne $stage) {
        Remove-OwnedDirectory $stage $destinationParent
    }
}

[pscustomobject]@{
    status = "exported"
    shard_count = $shardCount
    output_directory = $destination
} | ConvertTo-Json -Compress
