[CmdletBinding()]
param(
    [string]$ApplicationRoot = 'C:\Mining360',
    [string]$HealthUrl = 'http://127.0.0.1:8000/health/'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Read-only diagnostic. This script does not download files, execute child
# processes, modify configuration, access secrets, or restart services.
$result = [ordered]@{
    Script = 'Mining360 read-only status'
    TimestampUtc = [DateTime]::UtcNow.ToString('o')
    ComputerName = $env:COMPUTERNAME
    ApplicationRootExists = Test-Path -LiteralPath $ApplicationRoot -PathType Container
    RuntimeTask = 'Unavailable'
    Port8000Listening = $false
    Health = [ordered]@{
        Reachable = $false
        StatusCode = $null
        ApplicationStatus = $null
        DatabaseStatus = $null
    }
}

try {
    $task = Get-ScheduledTask -TaskName 'Mining360TestRuntime' -ErrorAction Stop
    $result.RuntimeTask = [string]$task.State
} catch {
    $result.RuntimeTask = 'Not found or access denied'
}

try {
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction Stop
    $result.Port8000Listening = [bool]$listener
} catch {
    $result.Port8000Listening = $false
}

try {
    $response = Invoke-WebRequest `
        -UseBasicParsing `
        -Uri $HealthUrl `
        -Headers @{'X-Forwarded-Proto' = 'https'; 'Host' = 'bodefm'} `
        -Method Get `
        -TimeoutSec 10
    $payload = $response.Content | ConvertFrom-Json
    $result.Health.Reachable = $true
    $result.Health.StatusCode = [int]$response.StatusCode
    $result.Health.ApplicationStatus = [string]$payload.status
    $result.Health.DatabaseStatus = [string]$payload.database
} catch {
    $result.Health.Reachable = $false
    $result.Health.ApplicationStatus = 'Health endpoint unavailable'
}

$result | ConvertTo-Json -Depth 4
