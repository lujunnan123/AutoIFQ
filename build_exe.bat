@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv not found. Create the virtual environment first.
    exit /b 1
)

echo [1/4] Installing runtime requirements...
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo [2/4] Installing PyInstaller...
"venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 exit /b 1

echo [3/4] Building AutoIFQ.exe...
"venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoIFQ --collect-all playwright --hidden-import xlrd --hidden-import openpyxl main.py
if errorlevel 1 exit /b 1

echo [4/4] Copying config and data...
copy /Y config.example.json dist\config.example.json >nul
if exist config.json copy /Y config.json dist\config.json >nul
if exist data xcopy /E /I /Y data dist\data >nul

echo Running smoke test...
dist\AutoIFQ.exe --smoke-test
if errorlevel 1 (
    echo [ERROR] Smoke test failed.
    exit /b 1
)

echo.
echo Build complete: %CD%\dist\AutoIFQ.exe
endlocal
