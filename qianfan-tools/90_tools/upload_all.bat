@echo off
chcp 65001 >nul
set "LOG=%~dp0upload.log"

echo [%date% %time%] === check === >> "%LOG%"
call "%~dp0run.bat" check >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] check 未通过，详见 %LOG%
  echo.
  exit /b 1
)

echo [%date% %time%] === upload === >> "%LOG%"
call "%~dp0run.bat" upload >> "%LOG%" 2>&1
set UP=%ERRORLEVEL%

echo [%date% %time%] === retry === >> "%LOG%"
call "%~dp0run.bat" retry >> "%LOG%" 2>&1
set RT=%ERRORLEVEL%

echo.
echo 上传结束：upload=%UP% retry=%RT%
echo 日志：%LOG%
if "%UP%"=="0" if "%RT%"=="0" exit /b 0
exit /b 1
