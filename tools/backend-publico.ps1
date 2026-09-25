# Expõe o backend local (Flask :5000, com biomecânica) na internet via túnel Cloudflare
# e aponta o site de produção (puxa-ai-site.pages.dev) para ele.
#   powershell -ExecutionPolicy Bypass -File tools\backend-publico.ps1
# A máquina precisa ficar ligada enquanto o túnel estiver aberto. A URL do túnel muda a cada execução.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Test-Health($base) {
  try { return (Invoke-RestMethod "$base/health" -TimeoutSec 8).status -eq "ok" } catch { return $false }
}

# 1. backend local
if (-not (Test-Health "http://localhost:5000")) {
  Write-Host "Subindo o backend local..." -ForegroundColor Yellow
  $env:BIO_PYTHON = "C:\Users\User\puxa-bio-env\Scripts\python.exe"
  Start-Process .\venv\Scripts\python.exe -ArgumentList "-m","flask","--app","app.api","run","--port","5000" -WindowStyle Minimized
  for ($i = 0; $i -lt 60 -and -not (Test-Health "http://localhost:5000"); $i++) { Start-Sleep 1 }
  if (-not (Test-Health "http://localhost:5000")) { throw "Backend não respondeu em localhost:5000" }
}
Write-Host "Backend local ok." -ForegroundColor Green

# 2. não deixar o PC dormir enquanto estiver na tomada
powercfg /change standby-timeout-ac 0

# 3. túnel
$log = Join-Path $env:TEMP "cloudflared-puxa.log"
if (Test-Path $log) { Remove-Item $log }
Start-Process .\cloudflared.exe -ArgumentList "tunnel","--no-autoupdate","--url","http://localhost:5000" `
  -RedirectStandardError $log -WindowStyle Minimized
$url = $null
for ($i = 0; $i -lt 45 -and -not $url; $i++) {
  Start-Sleep 1
  if (Test-Path $log) {
    $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
    if ($m) { $url = $m.Matches[0].Value }
  }
}
if (-not $url) { throw "Túnel não gerou URL. Veja $log" }
Write-Host "Túnel: $url" -ForegroundColor Green
for ($i = 0; $i -lt 30 -and -not (Test-Health $url); $i++) { Start-Sleep 2 }
if (-not (Test-Health $url)) { Write-Host "Aviso: $url/health ainda não respondeu, seguindo mesmo assim." -ForegroundColor Yellow }

# 4. site de produção passa a usar o túnel
$files = "analisar.html", "analisar-terminal.html", "var.html", "puxa-ai-site/script.js", "puxa-ai-site/terminal.js"
$pattern = "https://(guireeis0-puxa-ai-var\.hf\.space|[a-z0-9-]+\.trycloudflare\.com)"
$utf8 = New-Object Text.UTF8Encoding $false
foreach ($f in $files) {
  $p = Join-Path (Get-Location) $f
  [IO.File]::WriteAllText($p, ([regex]::Replace([IO.File]::ReadAllText($p), $pattern, $url)), $utf8)
}
# avisos do git (ex.: LF/CRLF) saem no stderr e o PowerShell 5.1 os trataria como erro
$ErrorActionPreference = "Continue"
git add $files 2>$null
git commit -m "chore: site aponta para o backend local via túnel ($url)"
git push origin main
if ($LASTEXITCODE -ne 0) { throw "git push falhou" }

Write-Host ""
Write-Host "Pronto. Em ~2 min o puxa-ai-site.pages.dev usa o backend desta máquina." -ForegroundColor Green
Write-Host "Não desligue o PC nem feche o cloudflared (janela minimizada na barra de tarefas)."
