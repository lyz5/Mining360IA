# Add an exact entry URL, without moving Django under a different script prefix.
$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'BODEFM'){throw 'Unexpected server'}
Import-Module WebAdministration
$configPath='C:\inetpub\Mining360Proxy\web.config'
$protectedPath='C:\inetpub\wwwroot\Miningprod\web.config'
$expectedHash='EF0ED52D26C62DF9F4390797BFDDFC32657FF7CE6595E1FCDABB4861935C3E6F'
$beforeHash=(Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
if($beforeHash -ne $expectedHash){throw 'Mining360 configuration changed since inspection; no change applied'}
$protectedHash=(Get-FileHash -LiteralPath $protectedPath -Algorithm SHA256).Hash
if($protectedHash -ne 'F9098D8898B341FC27B42A4D823BD38AAA87EAC3902D757127A880F1F8CB2B0A'){throw 'Protected application changed since inspection'}
$defaultBefore=Get-Website -Name 'Default Web Site'
$defaultBindings=@($defaultBefore.Bindings.Collection | ForEach-Object {$_.protocol+' '+$_.bindingInformation}) -join ';'
$defaultPool=$defaultBefore.applicationPool
$app=Get-WebApplication -Site 'Default Web Site' -Name 'Miningprod'
if($app.applicationPool -ne 'DefaultAppPool' -or $app.physicalPath -ne 'C:\inetpub\wwwroot\Miningprod'){throw 'Unexpected protected application topology'}
if((Get-Website -Name 'Mining360').physicalPath -ne 'C:\inetpub\Mining360Proxy'){throw 'Unexpected Mining360 site path'}

$xml=New-Object Xml.XmlDocument
$xml.PreserveWhitespace=$true
$xml.Load($configPath)
$rules=$xml.SelectSingleNode('/configuration/system.webServer/rewrite/rules')
$proxy=$rules.SelectSingleNode("rule[@name='Mining360 HTTPS reverse proxy']")
if(-not $proxy -or $proxy.action.url -ne 'http://127.0.0.1:8000/{R:1}'){throw 'Unexpected reverse proxy configuration'}
if($rules.SelectSingleNode("rule[@name='Mining360 entry URL']")){throw 'Entry rule already exists'}
$fragment=$xml.CreateDocumentFragment()
$fragment.InnerXml=@'
<rule name="Mining360 entry URL" stopProcessing="true">
  <match url="^mining360/?$" ignoreCase="true" />
  <conditions logicalGrouping="MatchAll">
    <add input="{HTTPS}" pattern="^ON$" ignoreCase="true" />
    <add input="{HTTP_HOST}" pattern="^bodefm(?::443)?$" ignoreCase="true" />
  </conditions>
  <action type="Redirect" url="/" appendQueryString="true" redirectType="Found" />
</rule>
'@
[void]$rules.InsertBefore($fragment,$proxy)
$backupDirectory=Join-Path 'C:\Mining360\backups' ('entry-url-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
[void][IO.Directory]::CreateDirectory($backupDirectory)
$backup=Join-Path $backupDirectory 'web.config.before'
[IO.File]::Copy($configPath,$backup,$false)
$temporary=Join-Path $backupDirectory 'web.config.pending'
$xml.Save($temporary)
$applied=$false
try {
    if((Get-FileHash -LiteralPath $configPath).Hash -ne $beforeHash){throw 'Configuration changed during preparation'}
    [IO.File]::Replace($temporary,$configPath,(Join-Path $backupDirectory 'web.config.replaced'))
    $applied=$true
    $after=New-Object Xml.XmlDocument
    $after.Load($configPath)
    if(-not $after.SelectSingleNode("/configuration/system.webServer/rewrite/rules/rule[@name='Mining360 entry URL']")){throw 'Entry rule missing'}
    $defaultAfter=Get-Website -Name 'Default Web Site'
    $bindingsAfter=@($defaultAfter.Bindings.Collection | ForEach-Object {$_.protocol+' '+$_.bindingInformation}) -join ';'
    if((Get-FileHash -LiteralPath $protectedPath).Hash -ne $protectedHash -or $bindingsAfter -ne $defaultBindings -or $defaultAfter.applicationPool -ne $defaultPool){throw 'Protected application invariant failed'}
    [pscustomobject]@{applied=$true;entry='https://bodefm/mining360';redirectTarget='/';backup=$backup;protectedConfigUnchanged=$true;defaultBindingsUnchanged=$true;globalRestartPerformed=$false} | ConvertTo-Json
} catch {
    if($applied){[IO.File]::Copy($backup,$configPath,$true)}
    throw
}
