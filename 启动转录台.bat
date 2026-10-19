@echo off
rem Launch the drag-and-drop transcriber without a console window.
rem Keep this file pure ASCII: cmd parses bat files with the OEM codepage.
cd /d "%~dp0"
start "" "C:\Python314\pythonw.exe" "%~dp0app.py"
