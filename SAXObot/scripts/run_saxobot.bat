@echo off
echo SAXObot 起動スクリプト
echo ============================
echo 仮想環境をアクティベートしています...

call saxobot_venv\Scripts\activate.bat

echo 仮想環境がアクティベートされました
echo Pythonバージョン:
python --version

echo ============================
echo SAXObotを起動します...
python SAXObot.py

pause 