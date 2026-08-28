@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

if exist "%~dp0python\python.exe" goto bundled_python
if exist "%~dp0venv\Scripts\python.exe" goto project_venv

where py >nul 2>&1
if not errorlevel 1 goto python_launcher

where python >nul 2>&1
if not errorlevel 1 goto system_python

echo.
echo ERRO: Python nao foi encontrado.
echo Instale o Python 3 ou adicione um runtime em python\python.exe.
pause
exit /b 1

:bundled_python
"%~dp0python\python.exe" "%~dp0portable_launcher.py" %*
goto finish

:project_venv
"%~dp0venv\Scripts\python.exe" "%~dp0portable_launcher.py" %*
goto finish

:python_launcher
py -3 "%~dp0portable_launcher.py" %*
goto finish

:system_python
python "%~dp0portable_launcher.py" %*

:finish
set "PDV_EXIT_CODE=%ERRORLEVEL%"
if not "%PDV_EXIT_CODE%"=="0" pause
exit /b %PDV_EXIT_CODE%
