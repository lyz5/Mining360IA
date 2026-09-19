$ErrorActionPreference='Stop'
Import-Module WebAdministration
$binding=Get-WebBinding -Name 'Mining360' -Protocol https | Where-Object {$_.bindingInformation -eq '*:443:'}
if(@($binding).Count -ne 1){throw 'Unexpected HTTPS bindings'}
$thumb=[string]$binding.certificateHash
$store=[string]$binding.certificateStoreName
if($thumb -notmatch '^[a-fA-F0-9]{40}$' -or $store -ne 'My'){throw 'Unexpected certificate binding'}
$certificate=Get-Item -LiteralPath ('Cert:\LocalMachine\My\'+$thumb)
[pscustomobject]@{thumbprint=$certificate.Thumbprint;subject=$certificate.Subject;publicCertificate=[Convert]::ToBase64String($certificate.RawData)} | ConvertTo-Json -Compress
