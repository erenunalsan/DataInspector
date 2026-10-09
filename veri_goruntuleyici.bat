@echo off
REM ============================================================
REM  livedata - buyuk veri goruntuleyici (CSV / JSON / XML / YAML)
REM
REM  Bu dosyaya cift tiklayin. Projedeki main.py ESKI ekrani
REM  (DataInspector) acar; bu ekran ondan bagimsizdir.
REM
REM  Istege bagli: acilista bir dosyayi hemen yuklemek icin
REM  veri dosyasini bu .bat dosyasinin uzerine SURUKLEYIP birakin.
REM ============================================================
cd /d "%~dp0"

set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

"%PY%" veri_goruntuleyici.py %*
if errorlevel 1 (
    echo.
    echo Ekran baslatilamadi. Yukaridaki hatayi kontrol edin.
    pause
)
