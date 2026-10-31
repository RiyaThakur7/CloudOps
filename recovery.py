
import subprocess
import time
import sqlite3
from datetime import datetime

CONTAINER_NAME = "cloudops-sample"
DATABASE = "cloudops.db"

# Recovery configuration
WAIT_BEFORE_RECOVERY = 10
MAX_ATTEMPTS = 2


def create_recovery_table():
    conn = sqlite3.connect(DATABASE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS recovery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_name TEXT,
            problem TEXT,
            status TEXT,
            attempts INTEGER,
            timestamp TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_recovery_log(problem, status, attempts):

    conn = sqlite3.connect(DATABASE)

    conn.execute("""
        INSERT INTO recovery_logs
        (container_name, problem, status, attempts, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (
        CONTAINER_NAME,
        problem,
        status,
        attempts,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()


def get_container_status():

    try:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format={{.State.Status}}",
                CONTAINER_NAME
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return "not_found"

        return result.stdout.strip().lower()

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"


def check_application_health():

    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "python",
                "-c",
                "import urllib.request; "
                "urllib.request.urlopen('http://127.0.0.1:5001/health', timeout=3)"
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        return result.returncode == 0

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def recover_container():

    create_recovery_table()

    problem = "Docker container is stopped."

    # Check current state
    container_status = get_container_status()

    if container_status == "running":

        if check_application_health():
            return {
                "status": "Healthy",
                "message": "Application is already running and healthy.",
                "attempts": 0
            }

        problem = "Container is running but application is unhealthy."

    elif container_status in ["exited", "created", "dead"]:
        problem = "Docker container is stopped."

    else:
        save_recovery_log(
            problem,
            "Recovery Failed",
            0
        )

        return {
            "status": "Recovery Failed",
            "message": "Container not available. Check Docker status.",
            "attempts": 0
        }

    # Notify developer and wait
    notification_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    time.sleep(WAIT_BEFORE_RECOVERY)

    # Check again before restarting
    container_status = get_container_status()

    if container_status == "running" and check_application_health():

        return {
            "status": "Recovered",
            "message": "Application recovered during the waiting period.",
            "attempts": 0
        }

    # Attempt automatic recovery
    for attempt in range(1, MAX_ATTEMPTS + 1):

        result = subprocess.run(
            ["docker", "start", CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:

            # Allow application time to start
            for _ in range(6):
                time.sleep(2)

                if check_application_health():

                    save_recovery_log(
                        problem,
                        "Recovery Successful",
                        attempt
                    )

                    return {
                        "status": "Recovery Successful",
                        "message": "Docker container restarted and application is healthy.",
                        "attempts": attempt
                    }

    save_recovery_log(
        problem,
        "Recovery Failed",
        MAX_ATTEMPTS
    )

    return {
        "status": "Recovery Failed",
        "message": "Automatic recovery attempts were unsuccessful. Developer intervention required.",
        "attempts": MAX_ATTEMPTS
    }
