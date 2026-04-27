@echo off
cd /d "%~dp0.."
echo.
echo  =========================================
echo   IQ Surco -- WhatsApp Webhook Listener
echo  =========================================
echo.
echo  Starting webhook listener on port 8080...
echo  Press Ctrl+C to stop.
echo.
python LeadAutomation/webhook_listener.py --port 8080
pause
