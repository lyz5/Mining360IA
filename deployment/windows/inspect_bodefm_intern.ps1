# Read-only inventory. Run inside the authorized BODEFM RDP session.
$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne 'BODEFM') { throw 'Run this inventory on BODEFM.' }
Import-Module WebAdministration

$sites = @(Get-Website | ForEach-Object {
    [ordered]@{
        site = $_.Name
        pool = $_.applicationPool
        path = $_.physicalPath
        bindings = @($_.Bindings.Collection | ForEach-Object {
            [ordered]@{protocol=$_.protocol; binding=$_.bindingInformation}
        })
        applications = @(Get-WebApplication -Site $_.Name | Select-Object path,physicalPath,applicationPool)
        virtualDirectories = @(Get-WebVirtualDirectory -Site $_.Name | Select-Object path,physicalPath)
    }
})
$dns = @()
foreach ($server in @('172.17.0.205','172.17.0.206')) {
    if (Get-Command Get-DnsServerZone -ErrorAction SilentlyContinue) {
        try {
            $zones = @(Get-DnsServerZone -ComputerName $server -ErrorAction Stop |
                Where-Object {-not $_.IsReverseLookupZone} |
                Select-Object ZoneName,ZoneType,IsDsIntegrated,ReplicationScope)
            $dns += [ordered]@{server=$server; zones=$zones}
        } catch {
            $dns += [ordered]@{server=$server; error=$_.FullyQualifiedErrorId}
        }
    } else {
        $dns += [ordered]@{server=$server; error='DnsServer administration module unavailable; nothing installed'}
    }
}
$certificates = @(Get-ChildItem Cert:\LocalMachine\My | Select-Object Subject,Issuer,Thumbprint,NotAfter,
    @{Name='DnsNames';Expression={@($_.DnsNameList | ForEach-Object {$_.Unicode})}})
[ordered]@{
    computer=$env:COMPUTERNAME
    account=[Security.Principal.WindowsIdentity]::GetCurrent().Name
    sites=$sites
    certificates=$certificates
    dns=$dns
    changesApplied=$false
} | ConvertTo-Json -Depth 8
