@echo off
REM ============================================================
REM  livedata masaustu uygulamasini TEK DOSYA bir .exe'ye paketler
REM  (PyInstaller ile) -- Python kurulu olmayan bir bilgisayara
REM  kopyalayip calistirabilmeniz icin.
REM
REM  Cikti: dist\LiveDataGoruntuleyici.exe
REM
REM  Not: Web arayuzu (Django) bu pakete DAHIL DEGILDIR -- o,
REM  ayri bir Python kurulumu ve `pip install -r requirements.txt`
REM  gerektirir (bkz. LIVEDATA_WEB.md). Bu paket yalnizca masaustu
REM  (Tkinter) ekranini icerir.
REM ============================================================
cd /d "%~dp0\.."

set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

"%PY%" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller kurulu degil, kuruluyor...
    "%PY%" -m pip install pyinstaller
)

echo.
echo Paketleniyor... (birkac dakika surebilir)
echo.

"%PY%" -m PyInstaller --onefile --windowed ^
    --name LiveDataGoruntuleyici ^
    --icon "livedata\ui\assets\icon.ico" ^
    --add-data "livedata\ui\assets\icon.ico;livedata\ui\assets" ^
    --collect-data sv_ttk ^
    --noconfirm ^
    veri_goruntuleyici.py

if errorlevel 1 (
    echo.
    echo Paketleme basarisiz oldu. Yukaridaki hatayi kontrol edin.
    pause
    exit /b 1
)

echo.
echo Tamamlandi: dist\LiveDataGoruntuleyici.exe
echo Bu dosyayi paylasmak istediginiz bilgisayara kopyalayip
echo cift tiklamaniz yeterlidir -- Python kurulumu gerekmez.
pause
