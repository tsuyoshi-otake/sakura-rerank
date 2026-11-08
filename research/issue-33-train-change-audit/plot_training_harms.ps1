$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms.DataVisualization
Add-Type -AssemblyName System.Drawing
$source='reports/issue-33-train-change-audit-v1.json'
$destination='reports/issue-33-train-change-common-wikipedia-v1.png'
if (Test-Path -LiteralPath $destination) { throw 'Figure already exists' }
$data=Get-Content -LiteralPath $source -Raw | ConvertFrom-Json
$chart=New-Object System.Windows.Forms.DataVisualization.Charting.Chart
try {
    $chart.Width=1200
    $chart.Height=680
    $chart.BackColor=[Drawing.Color]::White
    $chart.AntiAliasing='All'
    $area=New-Object System.Windows.Forms.DataVisualization.Charting.ChartArea 'Main'
    $area.AxisX.Title='Fixed training seed'
    $area.AxisX.MajorGrid.Enabled=$false
    $area.AxisX.Interval=1
    $area.AxisX.Minimum=0.5
    $area.AxisX.Maximum=3.5
    $area.AxisX.LabelStyle.Font=New-Object Drawing.Font('Segoe UI',12)
    $area.AxisX.TitleFont=New-Object Drawing.Font('Segoe UI',12)
    $area.AxisY.Title='Harm count on shared Wikipedia'
    $area.AxisY.Minimum=0
    $area.AxisY.Maximum=1000
    $area.AxisY.Interval=200
    $area.AxisY.MajorGrid.LineColor=[Drawing.Color]::FromArgb(230,234,238)
    $area.AxisY.LabelStyle.Font=New-Object Drawing.Font('Segoe UI',11)
    $area.AxisY.TitleFont=New-Object Drawing.Font('Segoe UI',11)
    $chart.ChartAreas.Add($area)
    $legend=New-Object System.Windows.Forms.DataVisualization.Charting.Legend
    $legend.Docking='Bottom'
    $legend.Font=New-Object Drawing.Font('Segoe UI',12)
    $chart.Legends.Add($legend)
    $title=$chart.Titles.Add('More unnecessary changes on the same Wikipedia training inputs')
    $title.Font=New-Object Drawing.Font('Segoe UI',18,[Drawing.FontStyle]::Bold)
    $subtitle=$chart.Titles.Add('25,000 shared rows; 21,356 locally correct; intact context; no gate')
    $subtitle.Font=New-Object Drawing.Font('Segoe UI',11)
    $foot=$chart.Titles.Add('Fitted-training diagnosis on GPU. This is not independent accuracy or a safety estimate.')
    $foot.Font=New-Object Drawing.Font('Segoe UI',10)
    $foot.Docking='Bottom'
    foreach ($arm in @('dictionary','annotation')) {
        $series=New-Object System.Windows.Forms.DataVisualization.Charting.Series $arm
        $series.ChartType='Column'
        $series.IsXValueIndexed=$true
        $series.LegendText=if ($arm -eq 'dictionary') {'Dictionary extraction'} else {'Original annotations'}
        $series.Color=if ($arm -eq 'dictionary') {[Drawing.Color]::FromArgb(48,104,155)} else {[Drawing.Color]::FromArgb(203,119,66)}
        $series.IsValueShownAsLabel=$true
        $series.Font=New-Object Drawing.Font('Segoe UI',12,[Drawing.FontStyle]::Bold)
        $position=1
        foreach ($seed in @('20260814','20261103','20261104')) {
            $key='ungated/intact/'+$arm+'-s'+$seed
            $value=$data.metrics.$key.common_wikipedia
            if ($value.rows -ne 25000 -or $value.baseline_correct -ne 21356) { throw 'Figure denominator changed' }
            $point=$series.Points.AddXY($position,[double]$value.harm)
            $series.Points[$point].AxisLabel=$seed
            $position++
        }
        $chart.Series.Add($series)
    }
    $chart.SaveImage([IO.Path]::GetFullPath($destination),'Png')
    Write-Output 'Saved shared-Wikipedia harm figure.'
} finally {
    $chart.Dispose()
}
