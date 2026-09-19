$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'BODEFM'){throw 'Unexpected server'}
$root='C:\Mining360\app'
$hashes=@()
foreach($directory in @('Mining360IA','reports','codex_chatbot','codex_admin','codex_integration','deployment','desktop')){
    $path=Join-Path $root $directory
    if(Test-Path -LiteralPath $path){
        $hashes+=@(Get-ChildItem -LiteralPath $path -Recurse -File | Where-Object {$_.Extension -in @('.py','.html','.js','.css','.ps1') -and $_.FullName -notmatch '\\__pycache__\\'} | ForEach-Object {
            [pscustomobject]@{file=$_.FullName.Substring($root.Length+1).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
        })
    }
}
$git=Get-Command git.exe -ErrorAction SilentlyContinue
$commit=$null
if($git){$commit=& $git.Source -C $root rev-parse HEAD 2>$null;if($LASTEXITCODE -ne 0){$commit=$null}}
[pscustomobject]@{computer=$env:COMPUTERNAME;root=$root;commit=$commit;files=$hashes;changesApplied=$false} | ConvertTo-Json -Depth 4
