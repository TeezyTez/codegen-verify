param([ValidateSet('Source','Dll')][string]$Mode)
$ErrorActionPreference='Stop'
$stopwatch=[Diagnostics.Stopwatch]::StartNew()
if ($Mode -eq 'Source') {
    Add-Type -Path generation/public_benchmark/structure_bridge.cs
} else {
    Add-Type -Path research/bridge-v2-proposal/original-bridge.dll
}
$loadSeconds=$stopwatch.Elapsed.TotalSeconds
$source=[IO.File]::ReadAllText((Resolve-Path 'logs/public-codegen-20261009/mutations/tasks/DA0045/mutants/constant-001/candidate.dfy'))
$homePath=(Resolve-Path '.tools/dafny/4.11.0').Path
$stopwatch.Restart()
$result=[PublicDafnyStructure]::Inspect($homePath,$source)
$inspectSeconds=$stopwatch.Elapsed.TotalSeconds
$sha=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($result)))
@{mode=$Mode;load_seconds=$loadSeconds;inspect_seconds=$inspectSeconds;status=($result|ConvertFrom-Json).status;result_sha256=$sha}|ConvertTo-Json -Compress
