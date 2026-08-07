"""
SoyMutDB API Windows Service.

Uses win32serviceutil to install/start/stop the API as a Windows Service.

Installation:
    python winservice_api.py --username .\\soymutdb --password <password> install
    python winservice_api.py start
    python winservice_api.py stop
    python winservice_api.py remove
"""

from __future__ import annotations

import os
import sys
import logging
import signal

import win32serviceutil
import win32service
import win32event
import servicemanager

# Non-primary release path; the canonical deployment is the container image.
SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
API_APP_DIR = os.path.abspath(os.path.join(SERVICE_DIR, "..", "..", "apps", "api"))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)
if API_APP_DIR not in sys.path:
    sys.path.insert(0, API_APP_DIR)


class SoyMutDBAPIService(win32serviceutil.ServiceFramework):
    """Windows Service wrapper for SoyMutDB API."""

    _svc_name_ = "SoyMutDBAPI"
    _svc_display_name_ = "SoyMutDB API Service"
    _svc_description_ = "SoyMutDB REST API server (FastAPI + Uvicorn)"
    _svc_deps_ = ["Tcpip", "Dhcp", "Dnscache"]

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server_thread = None
        self.should_stop = False

        # Setup logging to Windows Event Log
        self.logger = logging.getLogger("SoyMutDBAPI")
        self.logger.setLevel(logging.INFO)

    def SvcStop(self):
        """Called when the service is requested to stop."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.should_stop = True
        win32event.SetEvent(self.stop_event)

        # Try to shutdown uvicorn gracefully
        try:
            os.kill(os.getpid(), signal.SIGINT)
        except Exception:
            pass

    def SvcDoRun(self):
        """Called when the service starts running."""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.main()

    def main(self):
        """Main service loop - start the uvicorn server."""
        try:
            import uvicorn

            # Set environment for service mode
            os.environ.setdefault("SOYMUTDB_APP_ENV", "prod")
            os.environ.setdefault("SOYMUTDB_API_APP_PATH", os.path.join(API_APP_DIR, "app"))

            # Determine config file path
            config_path = os.path.join(SERVICE_DIR, "..", "..", ".env")
            if os.path.exists(config_path):
                from dotenv import load_dotenv
                load_dotenv(config_path)

            # Import the FastAPI app
            from app.main import app

            # Get config
            host = os.environ.get("SOYMUTDB_HOST", "0.0.0.0")
            port = int(os.environ.get("SOYMUTDB_PORT", "8000"))
            workers = int(os.environ.get("SOYMUTDB_WORKERS", "4"))

            # Run uvicorn server
            config = uvicorn.Config(
                app=app,
                host=host,
                port=port,
                workers=workers,
                log_level="info",
                access_log=True,
                loop="asyncio",
            )
            server = uvicorn.Server(config)
            server.run()

        except Exception as e:
            servicemanager.LogErrorMsg(
                f"SoyMutDB API Service failed to start: {e}"
            )
            raise


def ctrl_handler(ctrl_type):
    """Handle console control events."""
    return True


if __name__ == "__main__":
    # When run as a script, handle service commands
    if len(sys.argv) == 1:
        # Running as service
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(SoyMutDBAPIService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # Install/remove/start/stop via command line
        win32serviceutil.HandleCommandLine(SoyMutDBAPIService)
