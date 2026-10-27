
from flask import (
    Flask, jsonify, render_template, request,
    redirect, url_for, session, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timezone
import sqlite3
import os
import secrets
import time
import json
import shutil
import threading

# =========================================================
# 1. CONFIGURATION
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
DATABASE = os.path.join(BASE_DIR, "smartheal.db")
TEST_DATABASE = os.path.join(BASE_DIR, "smartheal_test.db")
TEST_BACKUP = os.path.join(BASE_DIR, "smartheal_test_backup.db")

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax"
)

STATE_LOCK = threading.RLock()

ERROR_LAB_STATE = {
    "active_error": None,
    "service_down": False,
    "circuit_open_until": 0.0
}

# Starts OFF. The admin checkbox changes this setting.
AUTO_RECOVERY_ENABLED = False

# =========================================================
# WEBSITE OUTAGE SIMULATION
# =========================================================

@app.before_request
def simulate_website_outage():
    """Block student portal pages during a simulated dependency outage."""

    # Keep monitoring and recovery APIs working during an outage.
    monitoring_api_paths = {
        "/api/health",
        "/api/resilience",
        "/api/incidents",
        "/api/error-lab/status",
        "/api/error-lab/settings",
        "/api/error-lab/generate",
        "/api/error-lab/fix",
    }

    # The dashboard and its assets must remain available so recovery
    # can be triggered without restarting the Flask server.
    monitoring_paths = {
        "/",
        "/style.css",
        "/script.js",
    }

    if request.path in monitoring_paths:
        return None

    if request.path.startswith("/api/"):
        if request.path in monitoring_api_paths:
            return None

        return None

    with STATE_LOCK:
        outage_active = ERROR_LAB_STATE["service_down"]

    if outage_active:
        return (
            "<!DOCTYPE html>"
            "<html lang='en'>"
            "<head><meta charset='UTF-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
            "<title>Service Temporarily Unavailable</title></head>"
            "<body style='font-family:Arial,sans-serif;text-align:center;"
            "padding:60px 20px;background:#f4f6fa;color:#17233c;'>"
            "<h1>503 - Service Temporarily Unavailable</h1>"
            
            "</body></html>",
            503,
            {"Content-Type": "text/html; charset=utf-8"}
        )

    return None


FALLBACK_CACHE = {
    "results": {
        "message": "No cached results yet",
        "cached_at": None
    }
}

CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 10


# =========================================================
# 2. DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DATABASE, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'student')),
                full_name TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS student_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                attendance REAL NOT NULL DEFAULT 0,
                marks REAL NOT NULL DEFAULT 0,
                assignments INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        columns = {
            row[1] for row in
            conn.execute("PRAGMA table_info(incidents)").fetchall()
        }

        migrations = {
            "created_at": "TEXT",
            "detected_at": "TEXT",
            "diagnosed_at": "TEXT",
            "action_at": "TEXT",
            "recovered_at": "TEXT",
            "detection_ms": "REAL",
            "recovery_ms": "REAL",
            "mechanism": "TEXT",
            "details": "TEXT"
        }

        for column, sql_type in migrations.items():
            if column not in columns:
                conn.execute(
                    f"ALTER TABLE incidents ADD COLUMN {column} {sql_type}"
                )

        conn.execute("""
            UPDATE incidents SET created_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
        """)

        admin = conn.execute("""
            SELECT id FROM users WHERE role = 'admin' LIMIT 1
        """).fetchone()

        if not admin:
            username = os.environ.get("ADMIN_USERNAME", "admin")
            password = os.environ.get("ADMIN_PASSWORD", "SmartHeal@2026")

            conn.execute("""
                INSERT INTO users (username, password_hash, role, full_name)
                VALUES (?, ?, 'admin', ?)
            """, (
                username,
                generate_password_hash(password),
                "SmartHeal Administrator"
            ))


# =========================================================
# 3. AUTHENTICATION
# =========================================================

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "message": "Please sign in first."
                }), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(required_role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                if request.path.startswith("/api/"):
                    return jsonify({
                        "success": False,
                        "message": "Please sign in first."
                    }), 401
                return redirect(url_for("login"))

            if session.get("role") != required_role:
                if request.path.startswith("/api/"):
                    return jsonify({
                        "success": False,
                        "message": "Administrator permission required."
                    }), 403
                return "403 - You do not have permission to access this page.", 403

            return view(*args, **kwargs)
        return wrapped
    return decorator

def sign_in_blocked():
    """Return True when SmartHeal has an active simulated failure."""
    with STATE_LOCK:
        return ERROR_LAB_STATE["active_error"] is not None



# =========================================================
# 4. HOME AND LOGIN
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")



@app.route("/login", methods=["GET", "POST"])
def login():
    # Block both student and admin sign-ins during an active failure.
    if sign_in_blocked():
        message = (
           
            "Sign-in is disabled until recovery is successful."
        )

        if request.method == "POST":
            flash(message)
            return render_template("login.html"), 503

        return (
            "<h1>503 - Sign-in temporarily unavailable</h1>"
            "<p>SmartHeal is recovering. Please try again after recovery.</p>",
            503
        )

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["full_name"] = user["full_name"]

            if user["role"] == "admin":
                return redirect(url_for("admin_panel"))

            return redirect(url_for("existing_dashboard"))

        flash("Invalid username or password.")

    return render_template("login.html")

@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================================================
# 5. ADMIN PANEL AND STUDENT RECORDS
# =========================================================

@app.route("/admin", methods=["GET", "POST"])
@role_required("admin")
def admin_panel():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()

        try:
            attendance = float(request.form.get("attendance", 0))
            marks = float(request.form.get("marks", 0))
            assignments = int(request.form.get("assignments", 0))

            if not username or not password or not full_name:
                raise ValueError("Complete all required student fields.")
            if len(username) > 80 or len(full_name) > 120:
                raise ValueError("Username or name is too long.")
            if not 8 <= len(password) <= 128:
                raise ValueError("Password must contain 8 to 128 characters.")
            if not 0 <= attendance <= 100:
                raise ValueError("Attendance must be between 0 and 100.")
            if not 0 <= marks <= 100:
                raise ValueError("Marks must be between 0 and 100.")
            if assignments < 0:
                raise ValueError("Assignments cannot be negative.")

            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO users (username, password_hash, role, full_name)
                    VALUES (?, ?, 'student', ?)
                """, (
                    username,
                    generate_password_hash(password),
                    full_name
                ))

                conn.execute("""
                    INSERT INTO student_records
                    (user_id, attendance, marks, assignments)
                    VALUES (?, ?, ?, ?)
                """, (
                    cursor.lastrowid,
                    attendance,
                    marks,
                    assignments
                ))

            flash("Student account created successfully.")

        except ValueError as exc:
            flash(str(exc))
        except sqlite3.IntegrityError:
            flash("That username already exists.")

        return redirect(url_for("admin_panel"))

    with get_db() as conn:
        students = conn.execute("""
            SELECT users.id, users.username, users.full_name,
                student_records.attendance, student_records.marks,
                student_records.assignments
            FROM users
            LEFT JOIN student_records ON users.id = student_records.user_id
            WHERE users.role = 'student'
            ORDER BY users.full_name
        """).fetchall()

    return render_template("admin.html", students=students)


@app.route("/admin/student/<int:user_id>/update", methods=["POST"])
@role_required("admin")
def update_student(user_id):
    try:
        attendance = float(request.form.get("attendance", 0))
        marks = float(request.form.get("marks", 0))
        assignments = int(request.form.get("assignments", 0))

        if not 0 <= attendance <= 100:
            raise ValueError("Attendance must be between 0 and 100.")
        if not 0 <= marks <= 100:
            raise ValueError("Marks must be between 0 and 100.")
        if assignments < 0:
            raise ValueError("Assignments cannot be negative.")

        with get_db() as conn:
            student = conn.execute("""
                SELECT id FROM users WHERE id = ? AND role = 'student'
            """, (user_id,)).fetchone()

            if not student:
                flash("Student account not found.")
            else:
                conn.execute("""
                    INSERT INTO student_records
                    (user_id, attendance, marks, assignments)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        attendance = excluded.attendance,
                        marks = excluded.marks,
                        assignments = excluded.assignments
                """, (user_id, attendance, marks, assignments))

                flash("Student record updated successfully.")

    except ValueError as exc:
        flash(str(exc))

    return redirect(url_for("admin_panel"))


# =========================================================
# 6. STUDENT PAGES
# =========================================================

@app.route("/student")
@role_required("student")
def student_panel():
    with get_db() as conn:
        record = conn.execute("""
            SELECT attendance, marks, assignments
            FROM student_records WHERE user_id = ?
        """, (session["user_id"],)).fetchone()

    return render_template("student.html", record=record)


@app.route("/dashboard")
@role_required("student")
def existing_dashboard():
    with get_db() as conn:
        record = conn.execute("""
            SELECT attendance, marks, assignments
            FROM student_records WHERE user_id = ?
        """, (session["user_id"],)).fetchone()

    return render_template(
        "dashboard.html",
        record=record,
        full_name=session.get("full_name"),
        username=session.get("username")
    )


@app.route("/<path:filename>")
def static_files(filename):
    if filename in ("style.css", "script.js"):
        return send_from_directory(BASE_DIR, filename)
    return "Not found", 404


# =========================================================
# 7. INCIDENT LOGGING
# =========================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def record_incident(
    issue, status, detected_at=None, diagnosed_at=None,
    action_at=None, recovered_at=None, detection_ms=None,
    recovery_ms=None, mechanism=None, details=None
):
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO incidents (
                issue, status, created_at, detected_at, diagnosed_at,
                action_at, recovered_at, detection_ms, recovery_ms,
                mechanism, details
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            issue, status, utc_now(), detected_at, diagnosed_at,
            action_at, recovered_at, detection_ms, recovery_ms,
            mechanism, details
        ))
        return cursor.lastrowid


def update_incident(incident_id, status, **fields):
    allowed = {
        "detected_at", "diagnosed_at", "action_at", "recovered_at",
        "detection_ms", "recovery_ms", "mechanism", "details"
    }

    updates = ["status = ?"]
    values = [status]

    for key, value in fields.items():
        if key in allowed:
            updates.append(f"{key} = ?")
            values.append(value)

    values.append(incident_id)

    with get_db() as conn:
        conn.execute(
            f"UPDATE incidents SET {', '.join(updates)} WHERE id = ?",
            values
        )


# =========================================================
# 8. CONTROLLED DEPENDENCY AND DATABASE REPAIR
# =========================================================

def retry_with_backoff(operation, attempts=3, base_delay=0.25):
    last_error = None

    for attempt in range(attempts):
        try:
            return operation(), attempt + 1
        except (ConnectionError, TimeoutError, sqlite3.Error) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(base_delay * (2 ** attempt))

    raise last_error or RuntimeError("Operation failed")


def dependency_call():
    with STATE_LOCK:
        if time.monotonic() < ERROR_LAB_STATE["circuit_open_until"]:
            raise ConnectionError("Circuit breaker is open.")
        if ERROR_LAB_STATE["service_down"]:
            raise ConnectionError("Controlled dependency outage.")

    return {
        "status": "online",
        "source": "dependency-simulator"
    }


def call_dependency_with_resilience():
    try:
        result, attempts = retry_with_backoff(
            dependency_call, attempts=3
        )

        with STATE_LOCK:
            ERROR_LAB_STATE["circuit_open_until"] = 0.0

        FALLBACK_CACHE["results"] = {
            "message": "Dependency is online",
            "cached_at": utc_now()
        }

        return {
            "data": result,
            "attempts": attempts,
            "fallback": False
        }

    except (ConnectionError, TimeoutError, sqlite3.Error) as exc:
        with STATE_LOCK:
            ERROR_LAB_STATE["circuit_open_until"] = (
                time.monotonic() + CIRCUIT_COOLDOWN_SECONDS
            )

        return {
            "data": FALLBACK_CACHE["results"],
            "attempts": 3,
            "fallback": True,
            "circuit": "open",
            "error": str(exc)
        }


def ensure_test_database():
    # Create the test database and table if missing.
    # This does NOT modify the main smartheal.db.
    with sqlite3.connect(TEST_DATABASE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY,
                student TEXT NOT NULL,
                marks INTEGER NOT NULL
            )
        """)

        conn.execute("""
            INSERT OR IGNORE INTO test_results (id, student, marks)
            VALUES (1, 'Demo Student', 85)
        """)

        conn.commit()

    # Create a backup only if one does not already exist.
    if not os.path.exists(TEST_BACKUP):
        shutil.copy2(TEST_DATABASE, TEST_BACKUP)


def repair_test_data():
    ensure_test_database()
    shutil.copy2(TEST_BACKUP, TEST_DATABASE)

    with sqlite3.connect(TEST_DATABASE) as conn:
        row = conn.execute("""
            SELECT student, marks FROM test_results WHERE id = 1
        """).fetchone()

        if not row or not (0 <= row[1] <= 100):
            raise sqlite3.DatabaseError(
                "Restored test record failed validation."
            )

    return {
        "verified": True,
        "student": row[0],
        "marks": row[1]
    }


def verify_test_database():
    with sqlite3.connect(TEST_DATABASE) as conn:
        row = conn.execute("""
            SELECT student, marks FROM test_results WHERE id = 1
        """).fetchone()

        if not row or not (0 <= row[1] <= 100):
            raise sqlite3.DatabaseError(
                "Test database verification failed."
            )

    return True


# =========================================================
# 9. HEALTH AND INCIDENT APIS
# =========================================================

def recovery_count():
    try:
        with get_db() as conn:
            return conn.execute("""
                SELECT COUNT(*) FROM incidents
                WHERE status = 'recovered'
            """).fetchone()[0]
    except sqlite3.Error:
        app.logger.exception("Could not count recoveries.")
        return 0


@app.route("/api/health")
def health():
    started = time.monotonic()
    database_status = "online"

    # Check the actual main database
    try:
        with get_db() as conn:
            conn.execute("SELECT 1").fetchone()
            conn.execute("SELECT COUNT(*) FROM incidents").fetchone()
            conn.execute("SELECT COUNT(*) FROM users").fetchone()

    except sqlite3.Error:
        app.logger.exception("Health check database failure.")
        database_status = "offline"

    # Check the active simulated error and dependency status
    with STATE_LOCK:
        active_error = ERROR_LAB_STATE.get("active_error")

        # Show Offline when the Error Lab database failure is active
        if (
            active_error is not None
            and active_error.get("type") == "database"
        ):
            database_status = "offline"

        dependency_status = (
            "offline"
            if ERROR_LAB_STATE["service_down"]
            else "online"
        )

        circuit_open = (
            time.monotonic()
            < ERROR_LAB_STATE["circuit_open_until"]
        )

    # Determine overall application health
    healthy = (
        database_status == "online"
        and dependency_status == "online"
    )

    return jsonify({
        "server": "online",
        "database": database_status,
        "dependency": dependency_status,
        "application": "healthy" if healthy else "degraded",
        "healthy": healthy,
        "circuit_breaker": "open" if circuit_open else "closed",
        "recovery_count": recovery_count(),
        "checked_at": utc_now(),
        "response_ms": round(
            (time.monotonic() - started) * 1000, 2
        ),
        "project": "SmartHeal"
    }), (200 if database_status == "online" else 503)

@app.route("/api/resilience")
def resilience_status():
    with STATE_LOCK:
        service = (
            "offline" if ERROR_LAB_STATE["service_down"] else "online"
        )
        circuit = (
            "open"
            if time.monotonic() < ERROR_LAB_STATE["circuit_open_until"]
            else "closed"
        )
        active = ERROR_LAB_STATE["active_error"]

    return jsonify({
        "service": service,
        "circuit_breaker": circuit,
        "active_error": active,
        "fallback_cache": FALLBACK_CACHE["results"],
        "recovery_count": recovery_count()
    })


@app.route("/api/incidents")
def incidents():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, issue, status, created_at, detected_at,
                diagnosed_at, action_at, recovered_at,
                detection_ms, recovery_ms, mechanism, details
            FROM incidents
            ORDER BY id DESC LIMIT 100
        """).fetchall()

    return jsonify([dict(row) for row in rows])


@app.route("/api/error-lab/status")
def error_lab_status():
    with STATE_LOCK:
        active = ERROR_LAB_STATE["active_error"]
        service_down = ERROR_LAB_STATE["service_down"]
        circuit = (
            "open"
            if time.monotonic() < ERROR_LAB_STATE["circuit_open_until"]
            else "closed"
        )

    return jsonify({
        "active_error": active,
        "service_down": service_down,
        "circuit_breaker": circuit,
        "auto_recovery": AUTO_RECOVERY_ENABLED,
        "recovery_count": recovery_count(),
        "message": (
            "Chaos tests use the dependency simulator or disposable test "
            "database. The main student database is not deliberately damaged."
        )
    })


# =========================================================
# 10. AUTO-RECOVERY SETTING
# =========================================================

@app.route("/api/error-lab/settings", methods=["GET", "POST"])

def error_lab_settings():
    global AUTO_RECOVERY_ENABLED

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        value = data.get("auto_recovery")

        if not isinstance(value, bool):
            return jsonify({
                "success": False,
                "message": "auto_recovery must be true or false."
            }), 400

        with STATE_LOCK:
            AUTO_RECOVERY_ENABLED = value

    return jsonify({
        "success": True,
        "auto_recovery": AUTO_RECOVERY_ENABLED
    })


# =========================================================
# 11. RECOVERY ACTION
# =========================================================

def perform_recovery():
    with STATE_LOCK:
        active = ERROR_LAB_STATE["active_error"]

    if not active:
        return {
            "success": False,
            "status": "No active failure",
            "message": "Generate a test error first."
        }

    incident_id = active["incident_id"]
    error_type = active["type"]
    start = active["started_monotonic"]
    action_at = utc_now()

    try:
        if error_type == "service":
            # Keep the failure active while demonstrating fallback.
            fallback = call_dependency_with_resilience()

            with STATE_LOCK:
                ERROR_LAB_STATE["service_down"] = False
                ERROR_LAB_STATE["circuit_open_until"] = 0.0

            verification, attempts = retry_with_backoff(
                dependency_call, attempts=3
            )

            recovery = {
                "fallback_used": fallback.get("fallback", False),
                "verification": verification,
                "verification_attempts": attempts
            }

        elif error_type in ("database", "corrupt_record"):
            recovery = repair_test_data()
            verify_test_database()

        elif error_type == "load":
            timings = []

            for _ in range(100):
                t0 = time.monotonic()
                with get_db() as conn:
                    conn.execute("SELECT 1").fetchone()
                timings.append((time.monotonic() - t0) * 1000)

            recovery = {
                "requests": 100,
                "average_ms": round(sum(timings) / len(timings), 2),
                "max_ms": round(max(timings), 2)
            }

        else:
            raise ValueError("Unknown active test failure.")

        recovered_at = utc_now()
        recovery_ms = round((time.monotonic() - start) * 1000, 2)

        update_incident(
            incident_id,
            "recovered",
            action_at=action_at,
            recovered_at=recovered_at,
            recovery_ms=recovery_ms,
            details=json.dumps(recovery)
        )

        with STATE_LOCK:
            ERROR_LAB_STATE["active_error"] = None

        return {
            "success": True,
            "status": "Recovered and verified",
            "failure": error_type,
            "detection_ms": active["detection_ms"],
            "recovery_ms": recovery_ms,
            "recovery": recovery,
            "message": "Recovery completed and verification passed."
        }

    except Exception as exc:
        app.logger.exception("Recovery action failed.")

        update_incident(
            incident_id,
            "recovery_failed",
            action_at=action_at,
            details=str(exc)
        )

        # Keep the active failure available for another manual attempt.
        with STATE_LOCK:
            ERROR_LAB_STATE["active_error"] = active

        return {
            "success": False,
            "status": "Recovery failed",
            "message": str(exc),
            "failure": error_type
        }


# =========================================================
# 12. GENERATE CONTROLLED FAILURE
# =========================================================

@app.route("/api/error-lab/generate", methods=["POST"])
def generate_error():
    data = request.get_json(silent=True) or {}
    error_type = data.get("type", "service")

    allowed = {"service", "database", "corrupt_record", "load"}

    if error_type not in allowed:
        return jsonify({
            "success": False,
            "message": "Choose service, database, corrupt_record, or load."
        }), 400

    with STATE_LOCK:
        if ERROR_LAB_STATE["active_error"]:
            return jsonify({
                "success": False,
                "message": "A test failure is already active. Recover it first."
            }), 409

        auto_recovery = AUTO_RECOVERY_ENABLED

    start = time.monotonic()
    detected_at = utc_now()

    issue = {
        "service": "Controlled dependency outage",
        "database": "Test database table failure",
        "corrupt_record": "Invalid record in isolated test database",
        "load": "Controlled request burst"
    }[error_type]

    details = ""

    try:
        # Inject failure only into the test environment.
        if error_type in ("database", "corrupt_record"):
            ensure_test_database()

            with sqlite3.connect(TEST_DATABASE) as conn:
                if error_type == "corrupt_record":
                    conn.execute("""
                        UPDATE test_results SET marks = 999 WHERE id = 1
                    """)
                    details = (
                        "Injected invalid marks into smartheal_test.db. "
                        "Production student data is untouched."
                    )
                else:
                    conn.execute("DROP TABLE test_results")
                    details = (
                        "Dropped test_results in smartheal_test.db only. "
                        "Production student data is untouched."
                    )

        elif error_type == "service":
            with STATE_LOCK:
                ERROR_LAB_STATE["service_down"] = True

            details = "Dependency simulator has been set offline."

        elif error_type == "load":
            details = "A bounded local 100-query test will run during recovery."

        diagnosed_at = utc_now()
        detection_ms = round((time.monotonic() - start) * 1000, 2)

        mechanism = (
            "retry/backoff+circuit-breaker+fallback"
            if error_type == "service"
            else "isolated-chaos-test"
        )

        incident_id = record_incident(
            issue,
            "detected",
            detected_at,
            diagnosed_at,
            None,
            None,
            detection_ms,
            None,
            mechanism,
            details
        )

        active = {
            "type": error_type,
            "issue": issue,
            "started_monotonic": start,
            "incident_id": incident_id,
            "detected_at": detected_at,
            "diagnosed_at": diagnosed_at,
            "detection_ms": detection_ms
        }

        with STATE_LOCK:
            ERROR_LAB_STATE["active_error"] = active

        # OFF means stop here and wait for the manual recovery button.
        if not auto_recovery:
            update_incident(
                incident_id,
                "awaiting_recovery",
                details=details
            )

            return jsonify({
                "success": True,
                "status": "Failure detected — awaiting manual recovery",
                "failure": error_type,
                "details": details,
                "detection_ms": detection_ms,
                "recovery_ms": None,
                "message": (
                    "Auto-recovery is OFF. The failure remains active. "
                    "Click Run Recovery to attempt repair."
                )
            })

        # ON means attempt recovery now.
        result = perform_recovery()
        result["details"] = details

        return jsonify(result), (200 if result["success"] else 500)

    except Exception as exc:
        app.logger.exception("Failure injection failed.")

        with STATE_LOCK:
            ERROR_LAB_STATE["active_error"] = None
            if error_type == "service":
                ERROR_LAB_STATE["service_down"] = False

        try:
            record_incident(
                issue,
                "injection_failed",
                detected_at=detected_at,
                mechanism="isolated-chaos-test",
                details=str(exc)
            )
        except sqlite3.Error:
            app.logger.exception("Could not record injection failure.")

        return jsonify({
            "success": False,
            "status": "Failure injection failed",
            "message": str(exc)
        }), 500


# =========================================================
# 13. MANUAL RECOVERY BUTTON
# =========================================================

@app.route("/api/error-lab/fix", methods=["POST"])
def fix_error():
    result = perform_recovery()
    return jsonify(result), (200 if result["success"] else 400)


# =========================================================
# 14. START SERVER
# =========================================================

if __name__ == "__main__":
    init_db()
    ensure_test_database()

    print("SmartHeal starting...")
    print("Project folder:", BASE_DIR)
    print("Auto-recovery starts OFF.")
    print("Main student database:", DATABASE)
    print("Isolated test database:", TEST_DATABASE)

    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
        use_reloader=False,
        threaded=True
    )
