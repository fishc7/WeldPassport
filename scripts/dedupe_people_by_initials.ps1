$ErrorActionPreference = 'Stop'

$path = 'D:\WeldPassport\ФИО и должности из 27 табелей.xlsx'
$backup = 'D:\WeldPassport\ФИО и должности из 27 табелей — до объединения инициалов.xlsx'
$allowedJobs = @('газорезчик', 'сварщик', 'эл/сварщик', 'эл/сварщик тт')

function Clean([string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) { return '' }
    return (($value -replace '[\r\n]+', ' ' -replace '\s+', ' ').Trim())
}

function Name-Parts([string]$name) {
    $name = Clean $name
    $matches = [regex]::Matches($name.ToLowerInvariant(), '[а-яёa-z]+')
    $parts = @($matches | ForEach-Object { $_.Value })
    if ($parts.Count -eq 0) {
        return [pscustomobject]@{ Surname = ''; Initials = ''; Length = 0; WordCount = 0 }
    }
    $surname = $parts[0]
    $rest = if ($parts.Count -gt 1) { @($parts[1..($parts.Count - 1)]) } else { @() }
    $initials = ($rest | ForEach-Object { $_.Substring(0, 1) }) -join ''
    $letters = ([regex]::Matches($name, '[А-ЯЁа-яёA-Za-z]')).Count
    return [pscustomobject]@{
        Surname = $surname
        Initials = $initials
        Length = $letters
        WordCount = $parts.Count
    }
}

function Compatible($a, $b) {
    if ($a.Surname -ne $b.Surname) { return $false }
    if (-not $a.Initials -or -not $b.Initials) { return $false }
    return $a.Initials.StartsWith($b.Initials) -or $b.Initials.StartsWith($a.Initials)
}

Copy-Item -LiteralPath $path -Destination $backup -Force

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false

try {
    $wb = $excel.Workbooks.Open($path, 0, $false)
    try {
        $allSheet = $wb.Worksheets.Item('Все уникальные')
        $lastRow = $allSheet.UsedRange.Rows.Count
        $records = New-Object System.Collections.Generic.List[object]

        for ($r = 2; $r -le $lastRow; $r++) {
            $fio = Clean ([string]$allSheet.Cells.Item($r, 1).Text)
            $job = Clean ([string]$allSheet.Cells.Item($r, 2).Text)
            if ($fio -and $job) {
                $records.Add([pscustomobject]@{
                    FIO = $fio
                    Job = $job
                    JobKey = $job.ToLowerInvariant()
                    Parts = Name-Parts $fio
                })
            }
        }

        $kept = New-Object System.Collections.Generic.List[object]
        $removed = New-Object System.Collections.Generic.List[object]

        foreach ($jobGroup in ($records | Group-Object JobKey)) {
            foreach ($surnameGroup in ($jobGroup.Group | Group-Object { $_.Parts.Surname })) {
                $items = @($surnameGroup.Group | Sort-Object `
                    @{ Expression = { $_.Parts.Length }; Descending = $true }, `
                    @{ Expression = { $_.Parts.WordCount }; Descending = $true }, `
                    FIO)
                $localKept = New-Object System.Collections.Generic.List[object]

                foreach ($item in $items) {
                    $match = $localKept | Where-Object { Compatible $_.Parts $item.Parts } | Select-Object -First 1
                    if ($match) {
                        $removed.Add([pscustomobject]@{
                            Removed = $item.FIO
                            Kept = $match.FIO
                            Job = $item.Job
                        })
                    }
                    else {
                        $localKept.Add($item)
                    }
                }
                foreach ($item in $localKept) { $kept.Add($item) }
            }
        }

        $all = @($kept | Sort-Object FIO, Job)
        $filtered = @($all | Where-Object { $allowedJobs -contains $_.JobKey })

        foreach ($info in @(
            @{ Sheet = $allSheet; Data = $all },
            @{ Sheet = $wb.Worksheets.Item('Сварочные должности'); Data = $filtered }
        )) {
            $ws = $info.Sheet
            $ws.UsedRange.ClearContents()
            $ws.Cells.Item(1, 1).Value2 = 'ФИО'
            $ws.Cells.Item(1, 2).Value2 = 'Должность'
            $row = 2
            foreach ($item in $info.Data) {
                $ws.Cells.Item($row, 1).Value2 = $item.FIO
                $ws.Cells.Item($row, 2).Value2 = $item.Job
                $row++
            }
            $header = $ws.Range('A1:B1')
            $header.Font.Bold = $true
            $header.Interior.Color = 15773696
            $ws.Columns.Item('A').ColumnWidth = 42
            $ws.Columns.Item('B').ColumnWidth = 28
            $range = $ws.Range("A1:B$($row - 1)")
            [void]$range.AutoFilter()
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($range)
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($header)
            if ($ws.Name -ne 'Все уникальные') {
                [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ws)
            }
        }

        $wb.Save()
        Write-Output "REMOVED=$($removed.Count)"
        Write-Output "ALL=$($all.Count)"
        Write-Output "FILTERED=$($filtered.Count)"
        Write-Output "BACKUP=$backup"
        Write-Output 'EXAMPLES:'
        $removed | Select-Object -First 30 | ForEach-Object {
            Write-Output ("{0} => {1} | {2}" -f $_.Removed, $_.Kept, $_.Job)
        }

        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($allSheet)
    }
    finally {
        $wb.Close($true)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($wb)
    }
}
finally {
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
