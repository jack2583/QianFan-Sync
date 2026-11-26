@echo off
chcp 65001 >nul
set "PY=D://DSH//social-auto-upload//QianFan-Sync//backend//.venv//Scripts//python.exe"
if not exist "%PY%" set "PY=python"

REM ===== 分类参数：直接改引号内的值；留空则不设置分类 =====
set "QF_CATEGORY=AI动画"

REM Double-click (no args): prepare loose videos, check, upload, retry.
if "%~1"=="" goto :full

if /I "%~1"=="prepare" (
  "%PY%" "%~dp0prepare_batch.py" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="review" (
  "%PY%" "%~dp0review_batch.py" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)

REM 参数模式：upload / retry 上传前先检查服务器连接
if /I "%~1"=="upload" (
  call :ping_check %*
  if errorlevel 1 goto :server_down
  goto :auto_category
)
if /I "%~1"=="retry" (
  call :ping_check %*
  if errorlevel 1 goto :server_down
  goto :auto_category
)

"%PY%" "%~dp0qianfan_lib.py" %*
exit /b %ERRORLEVEL%

:auto_category
if not defined QF_CATEGORY goto :run_plain
echo %* | findstr /I /C:"--category" >nul
if not errorlevel 1 goto :run_plain
"%PY%" "%~dp0qianfan_lib.py" %* --category "%QF_CATEGORY%"
exit /b %ERRORLEVEL%

:run_plain
"%PY%" "%~dp0qianfan_lib.py" %*
exit /b %ERRORLEVEL%

:full
echo ========== QianFan Library: full upload flow ==========
if defined QF_CATEGORY echo Category: %QF_CATEGORY%
echo [1/4] Prepare loose videos in 01_inbox (folders + 4 bordered covers)
"%PY%" "%~dp0prepare_batch.py"
if errorlevel 1 goto :failed

echo.
echo [2/4] Check prepared folders
"%PY%" "%~dp0qianfan_lib.py" check
if errorlevel 1 goto :failed

echo.
echo [3/4] Upload materials and create drafts
call :ping_check
if errorlevel 1 goto :server_down_full
if defined QF_CATEGORY (
  "%PY%" "%~dp0qianfan_lib.py" upload --category "%QF_CATEGORY%"
) else (
  "%PY%" "%~dp0qianfan_lib.py" upload
)
set UP=%ERRORLEVEL%

echo.
echo [4/4] Retry failed items
if defined QF_CATEGORY (
  "%PY%" "%~dp0qianfan_lib.py" retry --category "%QF_CATEGORY%"
) else (
  "%PY%" "%~dp0qianfan_lib.py" retry
)
set RT=%ERRORLEVEL%

echo.
echo ========== Done: upload=%UP% retry=%RT% ==========
if not "%UP%"=="0" goto :failed
if not "%RT%"=="0" goto :failed
echo All finished.
echo.
pause
exit /b 0

:ping_check
REM 上传前服务器连通性预检；--dry-run / --help 不联网，跳过检查
echo %* | findstr /I /C:"--dry-run" >nul
if not errorlevel 1 exit /b 0
echo %* | findstr /I /C:"--help" >nul
if not errorlevel 1 exit /b 0
echo [pre] 检查服务器连接...
"%PY%" "%~dp0qianfan_lib.py" ping
exit /b %ERRORLEVEL%

:server_down
echo.
echo ========== 服务器不可连接，已中止上传 ==========
echo 请先启动 QianFan-Sync 后端（运行 start.bat），确认端口 5409 可访问后再试。
echo.
exit /b 1

:server_down_full
echo.
echo ========== 服务器不可连接，已中止上传 ==========
echo 请先启动 QianFan-Sync 后端（运行 start.bat），确认端口 5409 可访问后再试。
echo.
pause
exit /b 1

:failed
echo.
echo Some steps failed. See messages above and run this script again after fixing.
echo.
pause
exit /b 1
