$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'BODEFM'){throw 'Unexpected server'}
$results=@()
foreach($server in @('172.17.0.205','172.17.0.206')) {
    $job=Start-Job -ArgumentList $server -ScriptBlock {
        param($dnsServer)
        try {
            $zones=@(Get-WmiObject -ComputerName $dnsServer -Namespace root\MicrosoftDNS -Class MicrosoftDNS_Zone -ErrorAction Stop | Select-Object Name,ZoneType,DsIntegrated)
            [pscustomobject]@{server=$dnsServer;zones=$zones;accessible=$true}
        } catch {[pscustomobject]@{server=$dnsServer;accessible=$false;error=$_.FullyQualifiedErrorId}}
    }
    try {
        if(Wait-Job $job -Timeout 12){$results+=Receive-Job $job | Select-Object server,zones,accessible,error}
        else {$results+=[pscustomobject]@{server=$server;accessible=$false;error='Read-only DNS administration query timed out'}}
    } finally {Stop-Job $job -ErrorAction SilentlyContinue; Remove-Job $job -Force}
}
[pscustomobject]@{dnsAdministration=$results;changesApplied=$false} | ConvertTo-Json -Depth 5
