Set-Location 'C:\Users\Sławek\Documents\.MD\PARA\SER\10_PROJEKTY\SIDE\PRAWY'
$envFile = Join-Path 'C:\Users\Sławek\Documents\.MD\PARA\SER\10_PROJEKTY\SIDE\PRAWY' '.env'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
            $parts = $line -split '=', 2
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim())
        }
    }
}
& 'C:\Users\Sławek\AppData\Local\Programs\Python\Python313\python.exe' -m tost ping-collect -v
