@echo off
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "INSTALL_DIR=%USERPROFILE%\QuickAttach"
set "APP_PY=%INSTALL_DIR%\app.py"

echo === QuickAttach - Instalacao (Windows) ===
echo Origem  : %SCRIPT_DIR%
echo Destino : %INSTALL_DIR%
echo.

:: ── Verificar Python ─────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    echo       Instale em https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo Python: %%i
echo.

:: ── 0. Copiar scripts para pasta permanente ───────────────────────────────────
echo [0/4] Copiando arquivos para %INSTALL_DIR%...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
for %%f in (
    app.py
    split_comprovantes.py
    sienge_relatorio.py
    extrair_lancamentos.py
    sienge_anexar.py
) do (
    if exist "%SCRIPT_DIR%%%f" (
        copy /Y "%SCRIPT_DIR%%%f" "%INSTALL_DIR%\%%f" >nul
    ) else (
        echo AVISO: %%f nao encontrado na origem, ignorando.
    )
)
:: Copiar credentials apenas se ainda nao existir no destino (preserva senha salva)
if not exist "%INSTALL_DIR%\sienge_credentials.json" (
    if exist "%SCRIPT_DIR%sienge_credentials.json" (
        copy /Y "%SCRIPT_DIR%sienge_credentials.json" "%INSTALL_DIR%\sienge_credentials.json" >nul
    )
)
echo       OK
echo.

:: ── 1. Dependencias Python ───────────────────────────────────────────────────
echo [1/4] Instalando dependencias Python...
python -m pip install --quiet --upgrade pymupdf playwright requests pdfplumber
if errorlevel 1 goto :erro
echo       OK
echo.

:: ── 2. Playwright Chromium ───────────────────────────────────────────────────
echo [2/4] Instalando Chromium (Playwright)...
python -m playwright install chromium
if errorlevel 1 goto :erro
echo       OK
echo.

:: ── 3. Atalho no Desktop ─────────────────────────────────────────────────────
echo [3/4] Criando atalho de desktop...

for /f "tokens=*" %%i in ('where python 2^>nul') do (
    set "PYTHON_EXE=%%i"
    goto :got_python
)
:got_python
for %%i in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpi"
set "PYTHONW=%PYTHON_DIR%pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=%PYTHON_EXE%"

:: Cria e executa PowerShell temporario para gerar o atalho .lnk
set "PS1=%TEMP%\qa_install.ps1"
(
    echo $lnk = "$env:USERPROFILE\Desktop\QuickAttach.lnk"
    echo $s = (New-Object -COM WScript.Shell^).CreateShortcut($lnk^)
    echo $s.TargetPath = '%PYTHONW%'
    echo $s.Arguments = '"%APP_PY%"'
    echo $s.WorkingDirectory = '%INSTALL_DIR%'
    echo $s.Description = 'QuickAttach - Anexo de comprovantes no SIENGE'
    echo $s.Save(^)
) > "%PS1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
del "%PS1%" >nul 2>&1

echo       Atalho: %USERPROFILE%\Desktop\QuickAttach.lnk
echo.
echo === Instalacao concluida. ===
echo     Arquivos instalados em: %INSTALL_DIR%
echo     Abra o QuickAttach pelo icone no Desktop.
goto :fim

:erro
echo.
echo ERRO na instalacao. Verifique a saida acima.
pause
exit /b 1

:fim
pause
