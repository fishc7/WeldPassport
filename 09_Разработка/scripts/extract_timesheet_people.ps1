$ErrorActionPreference = 'Stop'

$root = 'D:\МК_Кран'
$outputPath = 'D:\WeldPassport\ФИО и должности из 27 табелей.xlsx'
$allowedJobs = @('газорезчик', 'сварщик', 'эл/сварщик', 'эл/сварщик тт')

function Normalize-Text([string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) { return '' }
    return (($value -replace '[\r\n]+', ' ' -replace '\s+', ' ').Trim())
}

function Normalize-Name([string]$value) {
    $value = Normalize-Text $value
    $value = $value -replace '\s+\.$', ''
    return $value.Trim()
}

function Is-PersonName([string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) { return $false }
    if ($value -match '(?i)^(фио|ф\.и\.о|итого|всего|ответствен|начальник смены|номер|табель)') { return $false }
    if ($value -match '(?i)(отработано|дни явок|неявок|выходные|праздничные)') { return $false }
    return ($value -match '[А-ЯЁа-яёA-Za-z]{2,}.*[\s.]')
}

$records = @{}
$sourcesRead = New-Object System.Collections.Generic.List[string]
$sourcesSkipped = New-Object System.Collections.Generic.List[string]

function Add-Record([string]$fio, [string]$job) {
    $fio = Normalize-Name $fio
    $job = Normalize-Text $job
    if (-not (Is-PersonName $fio) -or [string]::IsNullOrWhiteSpace($job)) { return }
    if ($job -match '(?i)^(должность|смена|способ сварки)$') { return }
    $key = $fio.ToLowerInvariant() + '|' + $job.ToLowerInvariant()
    if (-not $records.ContainsKey($key)) {
        $records[$key] = [pscustomobject]@{ FIO = $fio; Job = $job }
    }
}

$files = @(Get-ChildItem -LiteralPath $root -Recurse -Force -File |
    Where-Object { $_.Name -match '(?i)табель' })
$excelFiles = @($files | Where-Object { $_.Extension -match '^\.xls(x|m|b)?$' })

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false

try {
    foreach ($file in $excelFiles) {
        $name = $file.Name

        # The flat workbook already contains normalized FIO/job pairs extracted
        # from all legacy СМР_табель *.xls forms.
        if ($name -match '^СМР_табель .+\.xls$' -or $name -eq 'СМР_табель_МАРТ.xls') {
            $sourcesSkipped.Add($file.FullName)
            continue
        }

        if ($name -eq 'сводный_табель.xlsx') {
            $sourcesSkipped.Add($file.FullName)
            continue
        }

        $wb = $excel.Workbooks.Open($file.FullName, 0, $true)
        try {
            $fileProducedData = $false
            foreach ($ws in $wb.Worksheets) {
                $used = $ws.UsedRange
                try {
                    $rowCount = [int]$used.Rows.Count
                    $colCount = [int]$used.Columns.Count
                    if ($rowCount -lt 2 -or $colCount -lt 1) { continue }

                    $values = $used.Value2
                    $fioRow = 0
                    $fioCol = 0
                    $jobCol = 0

                    $scanRows = [Math]::Min(15, $rowCount)
                    $scanCols = [Math]::Min(15, $colCount)
                    for ($r = 1; $r -le $scanRows; $r++) {
                        for ($c = 1; $c -le $scanCols; $c++) {
                            $v = Normalize-Text ([string]$values[$r, $c])
                            if ($v -match '(?i)^(фио|ф\.и\.о\.)$') {
                                $fioRow = $r
                                $fioCol = $c
                            }
                            if ($v -match '(?i)^должность$') {
                                $jobCol = $c
                            }
                        }
                    }

                    # Normal timesheets with separate FIO and position columns.
                    if ($fioCol -gt 0 -and $jobCol -gt 0) {
                        for ($r = $fioRow + 1; $r -le $rowCount; $r++) {
                            $fio = [string]$values[$r, $fioCol]
                            $job = [string]$values[$r, $jobCol]
                            $before = $records.Count
                            Add-Record $fio $job
                            if ($records.Count -gt $before) { $fileProducedData = $true }
                        }
                        continue
                    }

                    # Welding reports list only FIO; their personnel are welders.
                    if ($fioCol -gt 0 -and $file.FullName -match '(?i)\\Сварка\\|сварщик') {
                        for ($r = $fioRow + 1; $r -le $rowCount; $r++) {
                            $fio = Normalize-Name ([string]$values[$r, $fioCol])
                            if ($fio -match '(?i)^ответствен') { continue }
                            $before = $records.Count
                            Add-Record $fio 'сварщик'
                            if ($records.Count -gt $before) { $fileProducedData = $true }
                        }
                        continue
                    }

                    # Consolidated flat structure: C4 = FIO, C5 = Job.
                    if ($name -eq 'СМР_табель_все_месяцы_плоская_структура.xlsx') {
                        for ($r = 2; $r -le $rowCount; $r++) {
                            $before = $records.Count
                            Add-Record ([string]$values[$r, 4]) ([string]$values[$r, 5])
                            if ($records.Count -gt $before) { $fileProducedData = $true }
                        }
                    }
                }
                finally {
                    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($used)
                    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ws)
                }
            }
            if ($fileProducedData) { $sourcesRead.Add($file.FullName) }
            else { $sourcesSkipped.Add($file.FullName) }
        }
        finally {
            $wb.Close($false)
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($wb)
        }
    }

    $all = @($records.Values | Sort-Object FIO, Job)
    $filtered = @($all | Where-Object { $allowedJobs -contains $_.Job.ToLowerInvariant() })

    if (Test-Path -LiteralPath $outputPath) {
        Remove-Item -LiteralPath $outputPath -Force
    }

    $outWb = $excel.Workbooks.Add()
    try {
        while ($outWb.Worksheets.Count -lt 2) {
            [void]$outWb.Worksheets.Add()
        }

        $allSheet = $outWb.Worksheets.Item(1)
        $allSheet.Name = 'Все уникальные'
        $filterSheet = $outWb.Worksheets.Item(2)
        $filterSheet.Name = 'Сварочные должности'

        foreach ($sheetInfo in @(
            @{ Sheet = $allSheet; Data = $all },
            @{ Sheet = $filterSheet; Data = $filtered }
        )) {
            $sheet = $sheetInfo.Sheet
            $data = $sheetInfo.Data
            $sheet.Cells.Item(1, 1).Value2 = 'ФИО'
            $sheet.Cells.Item(1, 2).Value2 = 'Должность'
            $row = 2
            foreach ($item in $data) {
                $sheet.Cells.Item($row, 1).Value2 = $item.FIO
                $sheet.Cells.Item($row, 2).Value2 = $item.Job
                $row++
            }
            $header = $sheet.Range('A1:B1')
            $header.Font.Bold = $true
            $header.Interior.Color = 15773696
            $sheet.Columns.Item('A').ColumnWidth = 42
            $sheet.Columns.Item('B').ColumnWidth = 28
            $dataRange = $sheet.Range("A1:B$([Math]::Max(1, $row - 1))")
            [void]$dataRange.AutoFilter()
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($dataRange)
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($header)
        }

        $allSheet.Activate()
        $excel.ActiveWindow.SplitRow = 1
        $excel.ActiveWindow.FreezePanes = $true
        $outWb.SaveAs($outputPath, 51)

        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($allSheet)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($filterSheet)
    }
    finally {
        $outWb.Close($true)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($outWb)
    }

    Write-Output "MATCHED_FILES=$($files.Count)"
    Write-Output "EXCEL_FILES=$($excelFiles.Count)"
    Write-Output "UNIQUE_ALL=$($all.Count)"
    Write-Output "UNIQUE_FILTERED=$($filtered.Count)"
    Write-Output "READ_FILES=$($sourcesRead.Count)"
    Write-Output "SKIPPED_OR_COVERED=$($sourcesSkipped.Count)"
    Write-Output "OUTPUT=$outputPath"
}
finally {
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
