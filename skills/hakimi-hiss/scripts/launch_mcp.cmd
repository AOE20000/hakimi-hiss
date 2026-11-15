@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "SERVER=%SCRIPT_DIR%mcp_server.py"
if not exist "%SERVER%" (
    >&2 echo [hakimi-hiss] mcp_server.py not found at "%SERVER%"
    exit /b 1
)

set "PY_CMD="
set "PY_ARG="

rem 1. Search PATH entries first, skipping Microsoft Store WindowsApps alias stubs
call :scan_path
if defined PY_CMD goto :run_server

rem 2. Try Windows Python Launcher (py -3)
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if %ERRORLEVEL%==0 (
        set "PY_CMD=py"
        set "PY_ARG=-3"
        goto :run_server
    )
)

rem 3. Probe standard non-hardcoded environment locations (venv, conda, Scoop, python.org, ProgramFiles, SystemDrive)
call :try_env_dir VIRTUAL_ENV "\Scripts"
if defined PY_CMD goto :run_server
call :try_env_dir CONDA_PREFIX ""
if defined PY_CMD goto :run_server
call :try_env_dir SCOOP "\shims"
if defined PY_CMD goto :run_server
call :try_env_dir USERPROFILE "\scoop\shims"
if defined PY_CMD goto :run_server

call :probe_env_root LOCALAPPDATA "\Programs\Python"
if defined PY_CMD goto :run_server
call :probe_env_root ProgramFiles ""
if defined PY_CMD goto :run_server
call :probe_env_root "ProgramFiles(x86)" ""
if defined PY_CMD goto :run_server
call :probe_env_root SystemDrive ""
if defined PY_CMD goto :run_server
call :try_env_dir SystemDrive "\Python"
if defined PY_CMD goto :run_server

>&2 echo [hakimi-hiss] Python ^>= 3.10 not found. Install Python 3.10+ or disable WindowsApps stub alias.
exit /b 1

:run_server
if defined PY_ARG (
    "%PY_CMD%" %PY_ARG% -u "%SERVER%" %*
) else (
    "%PY_CMD%" -u "%SERVER%" %*
)
exit /b %ERRORLEVEL%

:resolve_env_dir
set "RESOLVED_DIR="
set "ENV_NAME=%~1"
set "ENV_SUB=%~2"
if not defined %ENV_NAME% goto :eof
setlocal EnableDelayedExpansion
set "RAW_VAL=!%ENV_NAME%!"
if not defined RAW_VAL (
    endlocal
    goto :eof
)
set "RAW_VAL=!RAW_VAL:"=!"
if not defined RAW_VAL (
    endlocal
    goto :eof
)
for /f "delims=" %%D in ("X!RAW_VAL!%ENV_SUB%") do (
    endlocal
    set "RESOLVED_DIR=%%D"
)
set "RESOLVED_DIR=%RESOLVED_DIR:~1%"
goto :eof

:try_env_dir
call :resolve_env_dir "%~1" "%~2"
if not defined RESOLVED_DIR goto :eof
set "CAND_DIR=%RESOLVED_DIR%"
goto :try_cand_dir

:probe_env_root
call :resolve_env_dir "%~1" "%~2"
if not defined RESOLVED_DIR goto :eof
:probe_strip_slash
if not defined RESOLVED_DIR goto :eof
if "%RESOLVED_DIR:~-1%"=="\" (
    set "RESOLVED_DIR=%RESOLVED_DIR:~0,-1%"
    goto :probe_strip_slash
)
if not exist "%RESOLVED_DIR%\" goto :eof
for /d %%P in ("%RESOLVED_DIR%\Python3*") do (
    if not defined PY_CMD (
        set "CAND_DIR=%%~P"
        call :try_cand_dir
    )
)
goto :eof

:scan_path
call :resolve_env_dir "PATH" ""
if not defined RESOLVED_DIR goto :eof
set "REM_PATH=%RESOLVED_DIR%"
:scan_loop
if not defined REM_PATH goto :eof
set "CUR_DIR="
set "NEXT_PATH="
for /f "tokens=1* delims=; eol=" %%A in ("%REM_PATH%") do (
    set "CUR_DIR=%%A"
    set "NEXT_PATH=%%B"
)
set "REM_PATH=%NEXT_PATH%"
if not defined CUR_DIR goto :scan_next
if /i not "%CUR_DIR:WindowsApps=%"=="%CUR_DIR%" goto :scan_next
set "CAND_DIR=%CUR_DIR%"
call :try_cand_dir
if defined PY_CMD goto :eof
:scan_next
if defined REM_PATH goto :scan_loop
goto :eof

:try_dir
set "CAND_DIR=%~1"
:try_cand_dir
if not defined CAND_DIR goto :eof
:cand_strip_slash
if "%CAND_DIR:~-1%"=="\" (
    set "CAND_DIR=%CAND_DIR:~0,-1%"
    if defined CAND_DIR goto :cand_strip_slash
)
if not defined CAND_DIR goto :eof
for %%N in (python3.exe python.exe) do (
    if exist "%CAND_DIR%\%%N" (
        "%CAND_DIR%\%%N" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if not errorlevel 1 (
            set "PY_CMD=%CAND_DIR%\%%N"
            goto :eof
        )
    )
)
goto :eof
