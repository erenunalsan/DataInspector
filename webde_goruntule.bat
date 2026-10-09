@echo off
REM ============================================================
REM  livedata - buyuk veri goruntuleyici, WEB arayuzu
REM
REM  Bu dosyaya cift tiklayin: yerel bir web sunucusu baslar ve
REM  tarayicida http://127.0.0.1:8000 acilir. Ayni ekran, ayni
REM  ilkelerle (diske yazma yok, RAM'e doldurma yok, arayuz
REM  kilitlenmez) artik bir tarayicidan da kullanilabilir.
REM
REM  Bu pencereyi KAPATMAYIN -- sunucu bu pencerede calisir;
REM  kapatildiginda sunucu da durur. Sadece bu bilgisayardan/
REM  yerel agdan erisim icindir, internete acmayin (bkz.
REM  LIVEDATA_WEB.md).
REM ============================================================
cd /d "%~dp0"

set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

echo Sunucu baslatiliyor: http://127.0.0.1:8000
echo Kapatmak icin bu pencerede Ctrl+C, sonra tarayici sekmesini kapatin.
echo.

start "" http://127.0.0.1:8000/

"%PY%" manage.py runserver 127.0.0.1:8000 --noreload
if errorlevel 1 (
    echo.
    echo Sunucu baslatilamadi. Yukaridaki hatayi kontrol edin.
    echo ("pip install -r requirements.txt" calistirmayi deneyin.)
    pause
)
