"""
SoyMutDB Worker Windows Service.

Uses win32serviceutil to run the Celery worker as a Windows Service.
Launches celery via subprocess.Popen.

Installation:
    python winservice_worker.py --username .\\soymutdb --password <password> install
    python winservice_worker.py start
    python winservice_worker.py stop
    python winservice_worker.py remove
"""

from __future__ import annotations

import os
import sys
import logging
import signal
import subprocess
import threading

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


class SoyMutDBWorkerService(win32serviceutil.ServiceFramework):
    """Windows Service wrapper for SoyMutDB Celery Worker."""

    _svc_name_ = "SoyMutDBWorker"
    _svc_display_name_ = "SoyMutDB Worker Service"
    _svc_description_ = "SoyMutDB async task worker (Celery) for ingestion, BLAST, and export"
    _svc_deps_ = ["SoyMutDBAPI", "Tcpip"]

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.should_stop = False
        self.worker_process = None

        self.logger = logging.getLogger("SoyMutDBWorker")
        self.logger.setLevel(logging.INFO)

    def SvcStop(self):
        """Called when the service is requested to stop."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.should_stop = True

        # Gracefully stop the Celery worker
        if self.worker_process and self.worker_process.poll() is None:
            try:
                self.worker_process.terminate()
                self.worker_process.wait(timeout=30)
            except Exception:
                try:
                    self.worker_process.kill()
                except Exception:
                    pass

        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        """Called when the service starts running."""
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.main()

    def main(self):
        """Main service loop - start Celery worker via subprocess.Popen."""
        try:
            # Set environment
            os.environ.setdefault("SOYMUTDB_APP_ENV", "prod")
            os.environ.setdefault("SOYMUTDB_API_APP_PATH", os.path.join(API_APP_DIR, "app"))

            # Load env file
            config_path = os.path.join(SERVICE_DIR, "..", "..", ".env")
            if os.path.exists(config_path):
                from dotenv import load_dotenv
                load_dotenv(config_path)

            # Determine worker config
            concurrency = os.environ.get("SOYMUTDB_WORKER_CONCURRENCY", "4")
            queues = os.environ.get(
                "SOYMUTDB_WORKER_QUEUES",
                "ingest,export,stats,cleanup,blast,default",
            )
            log_level = os.environ.get("SOYMUTDB_WORKER_LOG_LEVEL", "info")

            # Build celery command
            cmd = [
                sys.executable, "-m", "celery",
                "-A", "soymutdb_worker.main:celery_app",
                "worker",
                "--concurrency", concurrency,
                "--queues", queues,
                "--loglevel", log_level,
                "--pool", "prefork",
                "--without-mingle",
                "--without-gossip",
            ]

            # Run as subprocess
            self.worker_process = subprocess.Popen(
                cmd,
                cwd=os.path.join(SERVICE_DIR, "..", "..", "apps", "worker"),
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            # Read output and log to event log
            def log_output():
                process = self.worker_process
                if process is None or process.stdout is None:
                    return
                for line in iter(process.stdout.readline, b""):
                    if line:
                        servicemanager.LogInfoMsg(
                            f"[Worker] {line.decode('utf-8', errors='replace').rstrip()}"
                        )

            log_thread = threading.Thread(target=log_output, daemon=True)
            log_thread.start()

            # Wait for worker to exit
            while not self.should_stop:
                if self.worker_process.poll() is not None:
                    break
                # Check every 1 second
                rc = win32event.WaitForSingleObject(self.stop_event, 1000)
                if rc == win32event.WAIT_OBJECT_0:
                    break

            # Ensure worker is stopped
            if self.worker_process.poll() is None:
                self.worker_process.terminate()
                try:
                    self.worker_process.wait(timeout=10)
                except Exception:
                    self.worker_process.kill()

        except Exception as e:
            servicemanager.LogErrorMsg(
                f"SoyMutDB Worker Service failed: {e}"
            )
            raise


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(SoyMutDBWorkerService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(SoyMutDBWorkerService)
