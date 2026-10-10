param([string]$DafnyHome, [string]$CacheRoot)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $DafnyHome) { $DafnyHome = Join-Path $projectRoot '.tools/dafny/4.11.0' }
if (-not $CacheRoot) { $CacheRoot = Join-Path $projectRoot '.tools/public-structure-bridge' }
$CacheRoot = [IO.Path]::GetFullPath($CacheRoot)
function FileHash([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function TextHash([string]$value) { [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($value))).ToLowerInvariant() }
$identity = [ordered]@{
    schema = 'public_dafny_bridge_v2'
    cs_sha256 = FileHash (Join-Path $PSScriptRoot 'structure_bridge.cs')
    wrapper_sha256 = FileHash (Join-Path $PSScriptRoot 'structure_bridge.ps1')
    builder_sha256 = FileHash $PSCommandPath
    dafny_core_sha256 = FileHash (Join-Path $DafnyHome 'DafnyCore.dll')
    powershell = $PSVersionTable.PSVersion.ToString()
    dotnet = [Runtime.InteropServices.RuntimeInformation]::FrameworkDescription
    architecture = [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture.ToString()
}
$key = TextHash ($identity | ConvertTo-Json -Compress)
$receiptPath = Join-Path $CacheRoot 'build.json'
$cacheDirectory = Join-Path $CacheRoot ('cache/' + $key)
$dllPath = Join-Path $cacheDirectory 'bridge.dll'
# The fixed receipt is frozen with an experiment. A changed source needs an
# explicitly selected fresh cache root or an externally archived old receipt.
if (Test-Path -LiteralPath $receiptPath) {
    $existing = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json -AsHashtable
    if ($existing.key -ne $key -or $existing.dll_path -ne $dllPath -or
        -not (Test-Path -LiteralPath $dllPath) -or (FileHash $dllPath) -ne $existing.dll_sha256) {
        throw 'Existing build receipt is stale or corrupt; refusing overwrite.'
    }
    [Console]::Out.WriteLine($receiptPath)
    exit 0
}
[void][IO.Directory]::CreateDirectory($CacheRoot)
$mutex = [Threading.Mutex]::new($false, 'PublicDafnyBridge_' + (TextHash $CacheRoot))
if (-not $mutex.WaitOne(120000)) { throw 'Timed out waiting for the bridge build lock.' }
try {
    if (Test-Path -LiteralPath $receiptPath) { throw 'Another build published the receipt; rerun to validate it.' }
    [void][IO.Directory]::CreateDirectory($cacheDirectory)
    if (Test-Path -LiteralPath $dllPath) { throw 'Unreceipted DLL exists; refusing to trust or replace it.' }
    $temporaryDll = Join-Path $cacheDirectory ('building-' + [Guid]::NewGuid().ToString('N') + '.dll')
    Add-Type -Path (Join-Path $PSScriptRoot 'structure_bridge.cs') -OutputAssembly $temporaryDll
    $dllHash = FileHash $temporaryDll
    [IO.File]::Move($temporaryDll, $dllPath, $false)
    $receipt = [ordered]@{schema_version=1;key=$key;identity=$identity;dll_path=$dllPath;dll_sha256=$dllHash}
    $temporaryReceipt = Join-Path $CacheRoot ('building-' + [Guid]::NewGuid().ToString('N') + '.json')
    [IO.File]::WriteAllText($temporaryReceipt, ($receipt | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    [IO.File]::Move($temporaryReceipt, $receiptPath, $false)
    [Console]::Out.WriteLine($receiptPath)
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
