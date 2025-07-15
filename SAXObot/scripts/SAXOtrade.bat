@echo off

rem モード:エンドレスモード（ON:継続実行、OFF:1回実行）

cd /d "%~dp0.."
call saxobot_venv_new\Scripts\activate.bat && python SAXObot.py OFF

pause