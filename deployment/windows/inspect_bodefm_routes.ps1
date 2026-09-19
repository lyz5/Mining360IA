$ErrorActionPreference='Stop'
$configPath='C:\inetpub\Mining360Proxy\web.config'
[xml]$config=Get-Content -LiteralPath $configPath -Raw
$rules=@($config.configuration.'system.webServer'.rewrite.rules.rule | ForEach-Object {
    [pscustomobject]@{name=$_.name;match=$_.match.url;action=$_.action.type;url=$_.action.url}
})
$paths=@('C:\Mining360\app\Mining360IA\settings.py','C:\Mining360\app\Mining360IA\urls.py')
$prefixSupport=@($paths | ForEach-Object {
    if(Test-Path -LiteralPath $_){
        $text=Get-Content -LiteralPath $_ -Raw
        [pscustomobject]@{path=$_;scriptNameSupport=($text -match 'FORCE_SCRIPT_NAME|SCRIPT_NAME');prefixRoute=($text -match 'mining360/')}
    }
})
$responses=@()
foreach($path in @('/','/mining360','/mining360/','/health/')) {
    try {
        $request=[Net.HttpWebRequest]::Create('http://127.0.0.1:8000'+$path)
        $request.AllowAutoRedirect=$false
        $request.Host='bodefm'
        $request.Headers['X-Forwarded-Proto']='https'
        $request.Timeout=10000
        $response=$request.GetResponse()
        $responses+=[pscustomobject]@{path=$path;status=[int]$response.StatusCode;location=$response.Headers['Location']}
        $response.Close()
    } catch {
        if($_.Exception.Response){$responses+=[pscustomobject]@{path=$path;status=[int]$_.Exception.Response.StatusCode;location=$_.Exception.Response.Headers['Location']}}
        else {$responses+=[pscustomobject]@{path=$path;error=$_.FullyQualifiedErrorId}}
    }
}
[pscustomobject]@{rules=$rules;prefixSupport=$prefixSupport;responses=$responses} | ConvertTo-Json -Depth 5
