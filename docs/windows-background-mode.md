# Windows background mode

Clipyyy can start at Windows sign-in without leaving a PowerShell or Command Prompt window open.

## Requirements

- The repository is installed on the computer.
- Dependencies have been installed into the repository's .venv.
- For the Parth B: drive setup, the data folder is B:\CLIPSTUDIO\clipyyy-data.

## Install automatic startup

From the repository root, run this once in PowerShell:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Install-Startup.ps1

The installer adds a hidden launcher to the current Windows user's Startup folder and a Clipyyy Dashboard shortcut to the desktop. Sign out and back in, or start scripts\windows\Launch-Clipyyy.vbs once to launch it immediately.

Then open http://127.0.0.1:8000. The server listens only on localhost; it is not exposed to the network.

## Logs and data

The B: drive launcher writes server logs to B:\CLIPSTUDIO\clipyyy-data\logs\server.log and uses the B: drive for temporary files. It sets CLIPYYY_HOME to the existing Clipyyy data directory and points FFmpeg to the configured B: drive executable.

## Remove automatic startup

Run:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Uninstall-Startup.ps1

This removes only the automatic-startup shortcut. It does not delete project files, settings, runs, clips, or model caches.

## Notes

- The launcher expects the virtual environment at .venv\Scripts\python.exe.
- The launcher starts the API and built-in queue worker on 127.0.0.1:8000.
- Closing the browser does not stop the background server.
- Signing out or shutting down Windows stops the process; it starts again at the next sign-in.
- This is a per-user startup integration, so it does not require administrator privileges.
