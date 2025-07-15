Write-Host "SAXOtrade 実行スクリプト (PowerShell)" -ForegroundColor Green

# 仮想環境をアクティベート
& ".\saxobot_venv_new\Scripts\Activate.ps1"

# SAXObotを実行（1回実行モード）
python SAXObot.py OFF

Read-Host "続行するには何かキーを押してください" 