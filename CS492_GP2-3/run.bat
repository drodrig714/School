@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set PYTHON=py
) else (
  set PYTHON=python
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYTHON% -m venv .venv || goto :error
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt || goto :error
) else (
  call .venv\Scripts\activate.bat
)
echo Opening School Management System...
start "" http://127.0.0.1:5000
python app.py
goto :eof
:error
echo.
echo Setup failed. Confirm Python 3.10 or newer is installed.
pause
