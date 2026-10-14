param([string]$Exe = '', [string]$DataRoot = '')
$ErrorActionPreference = 'Stop'
$taskRepo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Exe) { $Exe = Join-Path $taskRepo 'dist/yuanjing/源镜.exe' }
$taskExe = (Resolve-Path $Exe).Path
Add-Type @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class ScoutWindowProbe {
    public delegate bool EnumProc(IntPtr hwnd, IntPtr lparam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hwnd, StringBuilder title, int count);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam);
    public static IntPtr Find(uint[] ids) {
        IntPtr found = IntPtr.Zero;
        EnumWindows((handle, unused) => {
            uint id; GetWindowThreadProcessId(handle, out id);
            var title = new StringBuilder(512); GetWindowText(handle, title, 512);
            if (Array.IndexOf(ids, id) >= 0 && (title.ToString() == "源镜 · 传播工作台" || title.ToString() == "源镜 · 传播工作台 - 源镜")) { found=handle; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
    public static string Title(IntPtr handle) {
        var title = new StringBuilder(512); GetWindowText(handle, title, 512); return title.ToString();
    }
    public static string[] Titles(uint[] ids) {
        var titles = new System.Collections.Generic.List<string>();
        EnumWindows((handle, unused) => {
            uint id; GetWindowThreadProcessId(handle, out id);
            var title = new StringBuilder(512); GetWindowText(handle, title, 512);
            if (Array.IndexOf(ids, id) >= 0 && title.Length > 0) titles.Add(title.ToString());
            return true;
        }, IntPtr.Zero);
        return titles.ToArray();
    }
}
'@
$taskRoot = if ($DataRoot) { [System.IO.Path]::GetFullPath($DataRoot) } else { Join-Path ([System.IO.Path]::GetTempPath()) ('desktop-smoke-' + [guid]::NewGuid().ToString('N')) }
$taskWindow = $null
$taskChildren = @()
$taskProc = Start-Process -FilePath $taskExe -ArgumentList @('--data-dir', ('"' + $taskRoot + '"')) -WindowStyle Hidden -PassThru
$taskClosed = $false
try {
    $taskDeadline = (Get-Date).AddSeconds(25)
    while ((Get-Date) -lt $taskDeadline) {
        $taskChildren = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($taskProc.Id)" | Select-Object -ExpandProperty ProcessId)
        # Get-Process excludes hidden windows; probe only this launch's process IDs.
        $taskHandle = [ScoutWindowProbe]::Find([uint32[]](@($taskProc.Id) + $taskChildren))
        if ($taskHandle -ne [IntPtr]::Zero) { $taskWindow = $taskHandle }
        if ($taskWindow -and (Test-Path (Join-Path $taskRoot 'data/accounts/main/db/scout.sqlite3'))) { break }
        $taskProc.Refresh()
        if ($taskProc.HasExited) { break }
        Start-Sleep -Milliseconds 300
    }
    $taskDbReady = Test-Path (Join-Path $taskRoot 'data/accounts/main/db/scout.sqlite3')
    $taskTitle = if ($taskWindow) { [ScoutWindowProbe]::Title($taskWindow) } else { 'NO WINDOW' }
    if ($taskWindow) { $null = [ScoutWindowProbe]::PostMessage($taskWindow, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) }
    $taskClosed = $taskProc.WaitForExit(6000)
    $taskErrorFile = Join-Path $taskRoot 'desktop-startup.log'
    $taskDiagnostic = if (Test-Path $taskErrorFile) { Get-Content -Raw $taskErrorFile } else { '' }
    $taskTitles = [ScoutWindowProbe]::Titles([uint32[]](@($taskProc.Id) + $taskChildren))
    [pscustomobject]@{WindowTitle=$taskTitle; DetectedTitles=$taskTitles; DatabaseCreated=$taskDbReady; NormalExit=$taskClosed; DataRoot=$taskRoot; Diagnostic=$taskDiagnostic} | ConvertTo-Json
    if (-not $taskDbReady -or $taskTitle -notin @('源镜 · 传播工作台','源镜 · 传播工作台 - 源镜') -or -not $taskClosed) { throw 'Native executable startup check failed' }
} finally {
    # Only the process launched here and its recorded children are eligible for cleanup.
    if (-not $taskClosed) {
        foreach ($taskId in $taskChildren) { Stop-Process -Id $taskId -ErrorAction SilentlyContinue }
        Stop-Process -Id $taskProc.Id -ErrorAction SilentlyContinue
    }
}
