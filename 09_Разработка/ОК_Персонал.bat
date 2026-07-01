@echo off
rem ============================================================
rem  WeldPassport - OK / Personnel
rem  Dvoynoy klik po etomu faylu otkryvaet okno programmy.
rem  (Tekst tut latinitsey namerenno - chtoby cmd ne lomalsya
rem   na kirillice. Na rabotu programmy eto ne vliyaet.)
rem ============================================================

rem Perehodim v papku, gde lezhit etot .bat (09_Razrabotka)
cd /d "%~dp0"

rem Podderzhka UTF-8 dlya Python
set PYTHONUTF8=1

echo Starting OK / Personnel app...
python desktop_ok\main.py

rem Esli oshibka - ne zakryvat okno srazu, chtoby prochitat tekst
if errorlevel 1 (
  echo.
  echo [Launch error] See the message above. Press any key to exit.
  pause >nul
)
