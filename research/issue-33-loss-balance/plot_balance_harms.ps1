$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms.DataVisualization
Add-Type -AssemblyName System.Drawing
$source='reports/issue-33-loss-balance-v1.json'
$destination='reports/issue-33-loss-balance-harms-v1.png'
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
    $area.AxisY.Title='Harmful changes (count)'
    $area.AxisY.Minimum=0
    $area.AxisY.Maximum=60
    $area.AxisY.Interval=10
    $area.AxisY.MajorGrid.LineColor=[Drawing.Color]::FromArgb(230,234,238)
    $area.AxisY.LabelStyle.Font=New-Object Drawing.Font('Segoe UI',11)
    $area.AxisY.TitleFont=New-Object Drawing.Font('Segoe UI',11)
    $chart.ChartAreas.Add($area)
    $legend=New-Object System.Windows.Forms.DataVisualization.Charting.Legend
    $legend.Docking='Bottom'
    $legend.Font=New-Object Drawing.Font('Segoe UI',12)
    $chart.Legends.Add($legend)
    $title=$chart.Titles.Add('Loss weighting reduces harms; dictionary anchors remain safer')
    $title.Font=New-Object Drawing.Font('Segoe UI',17,[Drawing.FontStyle]::Bold)
    $subtitle=$chart.Titles.Add('593 unused research examples; 475 originally correct; intact context; no gate; CPU')
    $subtitle.Font=New-Object Drawing.Font('Segoe UI',11)
    $foot=$chart.Titles.Add('Source-form agreement only. These counts do not certify IME intent, Gold quality or safety.')
    $foot.Font=New-Object Drawing.Font('Segoe UI',10)
    $foot.Docking='Bottom'
    $labels=@{annotation='Original annotations';weighted='Same rows, weighted loss';dictionary='Dictionary anchor'}
    $colors=@{
        annotation=[Drawing.Color]::FromArgb(203,119,66)
        weighted=[Drawing.Color]::FromArgb(48,104,155)
        dictionary=[Drawing.Color]::FromArgb(88,120,98)
    }
    foreach ($arm in @('annotation','weighted','dictionary')) {
        $series=New-Object System.Windows.Forms.DataVisualization.Charting.Series $arm
        $series.ChartType='Column'
        $series.IsXValueIndexed=$true
        $series.LegendText=$labels[$arm]
        $series.Color=$colors[$arm]
        $series.IsValueShownAsLabel=$true
        $series.Font=New-Object Drawing.Font('Segoe UI',12,[Drawing.FontStyle]::Bold)
        $position=1
        foreach ($seed in @('20260814','20261103','20261104')) {
            $key='ungated/intact/'+$arm+'-s'+$seed
            $value=$data.metrics.$key.main
            if ($value.rows -ne 593 -or $value.baseline_correct -ne 475) { throw 'Figure denominator changed' }
            $point=$series.Points.AddXY($position,[double]$value.harm)
            $series.Points[$point].AxisLabel=$seed
            $position++
        }
        $chart.Series.Add($series)
    }
    $chart.SaveImage([IO.Path]::GetFullPath($destination),'Png')
    Write-Output 'Saved loss-balance harm figure.'
} finally {
    $chart.Dispose()
}
