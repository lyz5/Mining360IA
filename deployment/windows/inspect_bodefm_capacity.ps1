$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'BODEFM'){throw 'Unexpected server'}
$computer=Get-CimInstance Win32_ComputerSystem
$os=Get-CimInstance Win32_OperatingSystem
$cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,LoadPercentage)
$disks=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
    [pscustomobject]@{drive=$_.DeviceID;sizeGB=[math]::Round($_.Size/1GB,1);freeGB=[math]::Round($_.FreeSpace/1GB,1)}
})
$processes=@(Get-Process | Where-Object {$_.ProcessName -match '^(python|pythonw|w3wp|sqlservr)$'} | ForEach-Object {
    [pscustomobject]@{name=$_.ProcessName;pid=$_.Id;workingSetMB=[math]::Round($_.WorkingSet64/1MB);cpuSeconds=[math]::Round($_.CPU,1);threads=$_.Threads.Count}
})
$waitress=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -match '^python' -and $_.CommandLine -match 'waitress'} | ForEach-Object {
    $threadCount=$null
    if($_.CommandLine -match '--threads[=\s]+(\d+)'){$threadCount=[int]$Matches[1]}
    [pscustomobject]@{pid=$_.ProcessId;parent=$_.ParentProcessId;configuredThreads=$threadCount}
})
$pool=$null
try {
    Import-Module WebAdministration
    $item=Get-Item IIS:\AppPools\Mining360
    $pool=[pscustomobject]@{queueLength=$item.queueLength;maxProcesses=$item.processModel.maxProcesses;idleTimeout=[string]$item.processModel.idleTimeout}
} catch {}
$settingsPath='C:\Mining360\app\Mining360IA\settings.py'
$settingsHints=$null
if(Test-Path -LiteralPath $settingsPath){
    $content=Get-Content -LiteralPath $settingsPath -Raw
    $settingsHints=[pscustomobject]@{redisMentioned=($content -match 'redis');locmemMentioned=($content -match 'LocMemCache');sqlServerMentioned=($content -match 'mssql')}
}
$samples=@()
for($index=0;$index -lt 3;$index++) {
    $sampleCpu=Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'"
    $memory=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
    $samples+=[pscustomobject]@{cpuPercent=$sampleCpu.PercentProcessorTime;availableMB=$memory.AvailableMBytes;pagesPerSecond=$memory.PagesPersec}
    if($index -lt 2){Start-Sleep -Seconds 3}
}
[pscustomobject]@{
    computer=$env:COMPUTERNAME;manufacturer=$computer.Manufacturer;model=$computer.Model;
    logicalProcessors=$computer.NumberOfLogicalProcessors;ramGB=[math]::Round($computer.TotalPhysicalMemory/1GB,1);
    freeRamGB=[math]::Round($os.FreePhysicalMemory/1MB,1);os=$os.Caption;
    cpu=$cpu;disks=$disks;processes=$processes;waitress=$waitress;mining360Pool=$pool;
    settingsHints=$settingsHints;samples=$samples;loadTestPerformed=$false
} | ConvertTo-Json -Depth 6
