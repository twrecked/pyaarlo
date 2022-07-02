@echo off
REM Send commands to daemon change port 5005 to your port number if necessary
REM Needs netcat.exe (see https://nmap.org/ncat/)
REM Sample: "cl quit", "cl set-mode garten"
echo %1 %2 %3 %4 %5 | c:\tools\ncat.exe --send-only 127.0.0.1 5005