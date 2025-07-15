Write-Host "SAXObot 起動スクリプト (PowerShell)" -ForegroundColor Green
Write-Host "============================" -ForegroundColor Green
Write-Host "仮想環境をアクティベートしています..." -ForegroundColor Yellow

# 仮想環境をアクティベート
& ".\saxobot_venv\Scripts\Activate.ps1"

Write-Host "仮想環境がアクティベートされました" -ForegroundColor Green
Write-Host "Pythonバージョン:" -ForegroundColor Cyan
python --version

Write-Host "============================" -ForegroundColor Green
Write-Host "SAXObotを起動します..." -ForegroundColor Yellow
python SAXObot.py

Read-Host "続行するには何かキーを押してください" 