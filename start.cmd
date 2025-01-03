@echo off

:: Run python script in a new window
start cmd /k "cd /d d:\git-hub\florence - backend && python index.py"

:: Run Ionic serve in another new window
start cmd /k "cd /d d:\git-hub\florence-develop && ionic serve --host 0.0.0.0"

pause
