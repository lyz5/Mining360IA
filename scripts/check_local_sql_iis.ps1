[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Get-RegistryValueSafe {
    param([string]$Path, [string]$Name)
    try {
        return (Get-ItemProperty -LiteralPath $Path -Name $Name -ErrorAction Stop).$Name
    }
    catch {
        return $null
    }
}

$instancesPath = 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL'
$instanceRows = @()
if (Test-Path -LiteralPath $instancesPath) {
    $instanceProperties = Get-ItemProperty -LiteralPath $instancesPath
    foreach ($property in $instanceProperties.PSObject.Properties) {
        if ($property.Name -like 'PS*') { continue }
        $instanceName = $property.Name
        $instanceId = [string]$property.Value
        $setupPath = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceId\Setup"
        $serviceName = if ($instanceName -eq 'MSSQLSERVER') { 'MSSQLSERVER' } else { "MSSQL`$$instanceName" }
        $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        $instanceRows += [pscustomobject]@{
            Instance = $instanceName
            InstanceId = $instanceId
            Version = Get-RegistryValueSafe -Path $setupPath -Name 'Version'
            Edition = Get-RegistryValueSafe -Path $setupPath -Name 'Edition'
            Service = $serviceName
            ServiceStatus = if ($service) { [string]$service.Status } else { 'NotFound' }
        }
    }
}

$iisFeatures = @(
    'IIS-WebServerRole',
    'IIS-WebServer',
    'IIS-ManagementConsole',
    'IIS-ASPNET45',
    'IIS-NetFxExtensibility45',
    'IIS-ISAPIExtensions',
    'IIS-ISAPIFilter',
    'IIS-StaticContent'
)

$iisRows = foreach ($feature in $iisFeatures) {
    $state = 'Unknown (run elevated for DISM details)'
    try {
        $output = & dism.exe /Online /Get-FeatureInfo /FeatureName:$feature /English 2>$null
        $stateLine = $output | Where-Object { $_ -match '^State\s*:' } | Select-Object -First 1
        if ($stateLine) { $state = ($stateLine -split ':', 2)[1].Trim() }
    }
    catch {}
    [pscustomobject]@{ Feature = $feature; State = $state }
}

$report = [pscustomobject]@{
    GeneratedAt = (Get-Date).ToString('o')
    SqlInstances = $instanceRows
    IisFeatures = $iisRows
    Target = [pscustomobject]@{
        Mining360Sql = 'SQL Server 2022 Developer 16.x; database Mining360App_Dev; compatibility 160'
        MiningProdSql = 'SQL Server 2022 Developer 16.x; database Miningprod_test_Local; source compatibility to confirm'
        MiningProdIis = 'Dedicated IIS site and application pool; ASP.NET 4.x; local-only database'
    }
}

$report | ConvertTo-Json -Depth 5
