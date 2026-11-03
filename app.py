
from flask import Flask, jsonify, render_template, request
import psutil
import sqlite3
import requests
import subprocess
import threading
import time
from datetime import datetime

app = Flask(__name__)

DATABASE = "cloudops.db"
CONTAINER_NAME = "cloudops-sample"

# Recovery configuration
WAIT_BEFORE_RECOVERY = 10
MAX_ATTEMPTS = 2

# Shared recovery state
recovery_state = {
    "status": "Monitoring",
    "message": "Application is being monitored.",
    "attempts": 0,
    "last_updated": None
}

recovery_lock = threading.Lock()
recovery_in_progress = False

# ---------------- DEPLOYMENT NOTIFICATION ----------------

deployment_notification = {
    "status": "No deployment yet",
    "message": "Waiting for the first Jenkins deployment.",
    "build_number": None,
    "timestamp": None
}


# ---------------- DATABASE ----------------

def create_database():

    conn = sqlite3.connect(DATABASE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cpu REAL,
            ram REAL,
            disk REAL,
            timestamp TEXT
        )
    """)

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


# ---------------- DOCKER MONITORING ----------------

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

    except subprocess.TimeoutExpired:
        return "unknown"

    except FileNotFoundError:
        return "docker_unavailable"


def check_application_health():

    try:
        response = requests.get(
            "http://127.0.0.1:5001/health",
            timeout=3
        )

        return response.status_code == 200

    except requests.RequestException:
        return False


# ---------------- RECOVERY SYSTEM ----------------

def update_recovery_state(status, message, attempts=0):

    recovery_state.update({
        "status": status,
        "message": message,
        "attempts": attempts,
        "last_updated": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    })


def run_recovery():

    global recovery_in_progress

    problem = "Docker container is stopped."

    try:

        update_recovery_state(
            "Waiting",
            "Developer notified. Recovery will start in 10 seconds."
        )

        save_recovery_log(
            problem,
            "Recovery Scheduled",
            0
        )

        # Wait to give the developer time to respond
        time.sleep(WAIT_BEFORE_RECOVERY)

        # Check again before restarting
        container_status = get_container_status()

        if container_status == "running" and check_application_health():

            update_recovery_state(
                "Recovered",
                "Application recovered during the waiting period."
            )

            save_recovery_log(
                problem,
                "Recovered Before Restart",
                0
            )

            return

        # Only restart an existing stopped container
        if container_status not in ["exited", "created", "dead"]:

            update_recovery_state(
                "Recovery Failed",
                "Container is unavailable or Docker cannot be accessed."
            )

            save_recovery_log(
                problem,
                "Recovery Failed",
                0
            )

            return

        # Maximum two restart attempts
        for attempt in range(1, MAX_ATTEMPTS + 1):

            update_recovery_state(
                "Recovering",
                f"Automatic restart attempt {attempt} of {MAX_ATTEMPTS}.",
                attempt
            )

            result = subprocess.run(
                ["docker", "start", CONTAINER_NAME],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:

                # Wait up to 12 seconds for health endpoint
                for _ in range(6):

                    time.sleep(2)

                    if (
                        get_container_status() == "running"
                        and check_application_health()
                    ):

                        update_recovery_state(
                            "Recovery Successful",
                            "Container restarted and application is healthy.",
                            attempt
                        )

                        save_recovery_log(
                            problem,
                            "Recovery Successful",
                            attempt
                        )

                        return

            # Do not restart a container that has disappeared
            if get_container_status() == "not_found":
                break

        update_recovery_state(
            "Recovery Failed",
            "Both restart attempts failed. Developer intervention required.",
            MAX_ATTEMPTS
        )

        save_recovery_log(
            problem,
            "Recovery Failed",
            MAX_ATTEMPTS
        )

    except Exception as error:

        update_recovery_state(
            "Recovery Failed",
            f"Recovery error: {str(error)}"
        )

        save_recovery_log(
            problem,
            "Recovery Error",
            0
        )

    finally:

        with recovery_lock:
            recovery_in_progress = False


def schedule_recovery():

    global recovery_in_progress

    with recovery_lock:

        if recovery_in_progress:
            return

        recovery_in_progress = True

        worker = threading.Thread(
            target=run_recovery,
            daemon=True
        )

        worker.start()


# ---------------- DASHBOARD ROUTES ----------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/health")
def health():

    return jsonify({
        "status": "healthy",
        "application": "CloudOps"
    })


# ---------------- DEPLOYMENT NOTIFICATION API ----------------

@app.route("/api/deployment-notification", methods=["GET", "POST"])
def deployment_notification_api():

    global deployment_notification

    if request.method == "POST":

        data = request.get_json(silent=True) or {}

        status = data.get("status")
        message = data.get("message")
        build_number = data.get("build_number")

        if status not in ["SUCCESS", "FAILURE"]:
            return jsonify({
                "error": "Status must be SUCCESS or FAILURE."
            }), 400

        if not isinstance(message, str) or not message.strip():
            return jsonify({
                "error": "A deployment message is required."
            }), 400

        deployment_notification = {
            "status": status,
            "message": message,
            "build_number": build_number,
            "timestamp": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        }

        return jsonify({
            "success": True,
            "notification": deployment_notification
        })

    return jsonify(deployment_notification)


# ---------------- SYSTEM METRICS ----------------

@app.route("/metrics")
def metrics():

    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage("C:\\").percent

    alerts = []

    if cpu > 80:
        alerts.append("High CPU usage detected.")

    if ram > 80:
        alerts.append("High RAM usage detected.")

    if disk > 90:
        alerts.append("Low disk space detected.")

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = sqlite3.connect(DATABASE)

    conn.execute("""
        INSERT INTO metrics (cpu, ram, disk, timestamp)
        VALUES (?, ?, ?, ?)
    """, (cpu, ram, disk, timestamp))

    conn.commit()
    conn.close()

    return jsonify({
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "alerts": alerts,
        "timestamp": timestamp
    })


# ---------------- METRIC HISTORY ----------------

@app.route("/api/history")
def history():

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT * FROM metrics
        ORDER BY id DESC
        LIMIT 50
    """).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


# ---------------- APPLICATION STATUS ----------------

@app.route("/application-status")
def application_status():

    container_status = get_container_status()

    if container_status == "running":

        if check_application_health():

            # Application is healthy again
            if recovery_state["status"] in [
                "Recovery Successful",
                "Recovered"
            ]:
                update_recovery_state(
                    "Monitoring",
                    "Application is healthy. Monitoring resumed."
                )

            return jsonify({
                "status": "Running",
                "recovery": recovery_state
            })

        # Running container but unhealthy application
        if not recovery_in_progress:
            schedule_recovery()

        return jsonify({
            "status": "Unhealthy",
            "recovery": recovery_state
        })

    elif container_status in ["exited", "created", "dead"]:

        schedule_recovery()

        return jsonify({
            "status": "Down",
            "recovery": recovery_state
        })

    elif container_status == "not_found":

        return jsonify({
            "status": "Not Found",
            "recovery": {
                "status": "Not Started",
                "message": "Container does not exist. Automatic restart is unavailable."
            }
        })

    elif container_status == "docker_unavailable":

        return jsonify({
            "status": "Docker Unavailable",
            "recovery": recovery_state
        })

    return jsonify({
        "status": "Unknown",
        "recovery": recovery_state
    })


# ---------------- FAILURE DIAGNOSIS ----------------

@app.route("/diagnose")
def diagnose():

    container_status = get_container_status()

    if container_status == "not_found":

        problem = "Docker container not found."

        solution = (
            "Create and start the cloudops-sample container."
        )

    elif container_status in ["exited", "created", "dead"]:

        problem = "Docker container is stopped."

        solution = (
            "CloudOps has scheduled automatic recovery."
        )

    elif container_status == "running":

        if check_application_health():

            problem = "No problem detected."

            solution = (
                "Docker container and application are healthy."
            )

        else:

            problem = (
                "Docker container is running, "
                "but the application is not responding."
            )

            solution = (
                "CloudOps is attempting automatic recovery."
            )

    elif container_status == "docker_unavailable":

        problem = "Docker is unavailable."

        solution = (
            "Start Docker Desktop and verify Docker is installed."
        )

    elif container_status == "unknown":

        problem = "Docker command timed out."

        solution = (
            "Check whether Docker Desktop is running."
        )

    else:

        problem = (
            "Unexpected Docker container state: "
            + container_status
        )

        solution = (
            "Inspect the Docker container and its logs."
        )

    return jsonify({
        "problem": problem,
        "solution": solution,
        "checked_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    })


# ---------------- RECOVERY STATUS API ----------------

@app.route("/api/recovery-status")
def recovery_status():

    return jsonify(recovery_state)


# ---------------- RECOVERY HISTORY API ----------------

@app.route("/api/recovery-logs")
def recovery_logs():

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT * FROM recovery_logs
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    return jsonify([dict(row) for row in rows])


# ---------------- START SERVER ----------------

if __name__ == "__main__":

    create_database()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False
    )
