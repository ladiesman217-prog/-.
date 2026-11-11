@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Создаю окружение и устанавливаю библиотеки для проекта...
  py -m venv .venv
  if errorlevel 1 goto install_error
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto install_error
".venv\Scripts\python.exe" telegram_bot.py
pause
exit /b

:install_error
echo Не удалось установить Python-библиотеки. Проверь Python и подключение к интернету.
pause
