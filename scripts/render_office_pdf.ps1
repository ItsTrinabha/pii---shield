# Render the PPTX and DOCX samples to PDF with locally installed Microsoft Office (COM), for the OCR-vs-native eval.
# Local only: no network. Usage: powershell -ExecutionPolicy Bypass -File scripts\render_office_pdf.ps1
param(
    [string]$Samples = "data\samples",
    [string]$Out = "data\derived"
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Out | Out-Null
$samplesFull = (Resolve-Path $Samples).Path
$outFull = (Resolve-Path $Out).Path

$docx = Get-ChildItem $samplesFull -Filter *.docx
if ($docx) {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    try {
        foreach ($f in $docx) {
            $d = $word.Documents.Open($f.FullName, $false, $true)  # ConfirmConversions=false, ReadOnly=true
            $d.ExportAsFixedFormat((Join-Path $outFull "$($f.Name).pdf"), 17)  # wdExportFormatPDF
            $d.Close(0)
            "rendered $($f.Name)"
        }
    } finally { $word.Quit() }
}

$pptx = Get-ChildItem $samplesFull -Filter *.pptx
if ($pptx) {
    $pp = New-Object -ComObject PowerPoint.Application
    try {
        foreach ($f in $pptx) {
            $p = $pp.Presentations.Open($f.FullName, -1, 0, 0)  # ReadOnly, Untitled=false, WithWindow=false
            $p.SaveAs((Join-Path $outFull "$($f.Name).pdf"), 32)  # ppSaveAsPDF
            $p.Close()
            "rendered $($f.Name)"
        }
    } finally { $pp.Quit() }
}
