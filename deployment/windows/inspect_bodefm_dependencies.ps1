$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'BODEFM'){throw 'Unexpected server'}
$report=[ordered]@{}
$report.protectedConfigHashes=@('C:\inetpub\wwwroot\Miningprod\web.config','C:\inetpub\Mining360Proxy\web.config') | ForEach-Object {
    if(Test-Path -LiteralPath $_){Get-FileHash -LiteralPath $_ -Algorithm SHA256 | Select-Object Path,Hash}
}
$report.runtimeSettings=@('MINING360_PUBLIC_BASE_URL','MINING360_ALLOWED_HOSTS','MINING360_CSRF_TRUSTED_ORIGINS','MINING360_SECURE_SSL_REDIRECT','ENTRA_REDIRECT_URI','AZURE_AD_REDIRECT_URI') | ForEach-Object {
    [pscustomobject]@{Name=$_;Machine=[Environment]::GetEnvironmentVariable($_,'Machine');User=[Environment]::GetEnvironmentVariable($_,'User')}
}
try {$report.tasks=@(Get-ScheduledTask -TaskName '*Mining360*' -ErrorAction Stop | Select-Object TaskName,State)}
catch {$report.tasksError=$_.FullyQualifiedErrorId}
$report.services=@(Get-CimInstance Win32_Service | Where-Object {$_.Name -like '*Mining360*'} | Select-Object Name,State,ProcessId)
$report.caCertificates=@(Get-ChildItem Cert:\LocalMachine\Root,Cert:\LocalMachine\CA | Where-Object {$_.Subject -match 'neemba|jadelmas|resdelmas'} | Select-Object Subject,Issuer,Thumbprint,NotAfter)
try {
    $rootDse=[ADSI]'LDAP://RootDSE'
    $config=[string]$rootDse.configurationNamingContext
    if(-not $config){throw 'Directory context unavailable'}
    $search=New-Object DirectoryServices.DirectorySearcher([ADSI]('LDAP://CN=Enrollment Services,CN=Public Key Services,CN=Services,'+$config))
    $search.Filter='(objectClass=pKIEnrollmentService)'
    $search.ClientTimeout=[TimeSpan]::FromSeconds(10)
    $report.enterpriseCAs=@($search.FindAll() | ForEach-Object {
        [pscustomobject]@{Name=[string]$_.Properties['cn'][0];Host=[string]$_.Properties['dnshostname'][0];Templates=@($_.Properties['certificatetemplates'])}
    })
} catch {$report.enterpriseCAError=$_.FullyQualifiedErrorId}
try {
    $uri='http://172.17.0.111/Miningprod'
    $request=[Net.HttpWebRequest]::Create($uri)
    $request.AllowAutoRedirect=$false
    $request.Timeout=10000
    $response=$request.GetResponse()
    $report.miningprodHttpStatus=[int]$response.StatusCode
    $response.Close()
} catch {
    if($_.Exception.Response){$report.miningprodHttpStatus=[int]$_.Exception.Response.StatusCode}
    else {$report.miningprodHttpError=$_.FullyQualifiedErrorId}
}
$report.changesApplied=$false
$report | ConvertTo-Json -Depth 6
