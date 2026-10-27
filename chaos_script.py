"""Run controlled SmartHeal chaos tests without starting a web server.

The script imports the Flask app, uses a test client, and injects failures only into
its isolated dependency simulator / smartheal_test.db. It never corrupts smartheal.db.
"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import app as smartheal  # noqa: E402


def main():
    smartheal.init_db()
    smartheal.ensure_test_database()
    client = smartheal.app.test_client()
    with client.session_transaction() as session:
        with smartheal.get_db() as conn:
            admin = conn.execute("SELECT id, username, full_name FROM users WHERE role='admin' LIMIT 1").fetchone()
        if not admin:
            print("ERROR: no admin account exists. Start app.py once to initialize the database.")
            return 1
        session["user_id"] = admin["id"]
        session["username"] = admin["username"]
        session["full_name"] = admin["full_name"]
        session["role"] = "admin"

    tests = ["service", "database", "corrupt_record", "load"]
    print("SmartHeal controlled chaos tests (isolated test database only)\n")
    passed = 0
    for test_type in tests:
        started = time.perf_counter()
        response = client.post("/api/error-lab/generate", json={"type": test_type})
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        try:
            result = response.get_json() or {}
        except Exception:
            result = {}
        ok = response.status_code == 200 and result.get("success") is True
        recovery_message = ""

        if ok and result.get("recovery_ms") is None:
            recovery_response = client.post("/api/error-lab/fix")
            try:
                recovery_result = recovery_response.get_json() or {}
            except Exception:
                recovery_result = {}

            ok = (
                recovery_response.status_code == 200
                and recovery_result.get("success") is True
            )
            recovery_message = recovery_result.get(
                "message", "No recovery message returned"
            )
        elif ok:
            recovery_message = result.get("message", "Recovery completed.")

        print(f"{'PASS' if ok else 'FAIL'} | {test_type} | HTTP {response.status_code} | wall={elapsed_ms} ms")
        print(f"  {result.get('message', 'No message returned')}")
        if recovery_message:
            print(f"  recovery: {recovery_message}")
        if result.get("recovery_ms") is not None:
            print(f"  measured detection={result.get('detection_ms')} ms; recovery={result.get('recovery_ms')} ms")
        passed += int(ok)
    print(f"\nResult: {passed}/{len(tests)} tests recovered and verified.")
    print("Note: process-crash recovery is tested separately by running watchdog.py and ending its child process.")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(main())
