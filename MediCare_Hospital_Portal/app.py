import os
import secrets
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request, send_from_directory, session

from database import connection, initialize_database
from services import (
    ServiceError,
    admin_summary,
    cancel_booking,
    complete_consultation,
    create_booking,
    create_department,
    create_doctor,
    list_appointments,
    list_all_appointments,
    list_all_records,
    list_doctors,
    list_notifications,
    list_records,
    mark_notification_read,
    authenticate_patient,
    authenticate_staff,
    patient_data,
    pay_completed_appointment,
    register_patient,
    provision_staff_account,
    receipt_data,
    update_patient,
)


BASE_DIR = Path(__file__).resolve().parent
ASSET_FILES = {"app.js", "styles.css", "responsive.css"}


def _json_body() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ServiceError("Request body must be a JSON object.")
    return payload


def _current_patient_id() -> int:
    patient_id = session.get("patient_id")
    if not session.get("user_id"):
        raise ServiceError("Please sign in to continue.", 401)
    if session.get("role") != "patient" or patient_id is None:
        raise ServiceError("This feature is only available to patient accounts.", 403)
    return int(patient_id)


def _require_role(role: str) -> None:
    if not session.get("user_id"):
        raise ServiceError("Please sign in to continue.", 401)
    if session.get("role") != role:
        raise ServiceError(f"A {role} account is required.", 403)
    if role in {"doctor", "admin"} and not session.get("staff_email"):
        raise ServiceError(f"A {role} account is required.", 403)


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))
    app.config.from_mapping(
        DATABASE=os.environ.get("MEDICARE_DATABASE", str(BASE_DIR / "hospital.db")),
        SECRET_KEY=os.environ.get("MEDICARE_SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        DOCTOR_LOGIN_EMAIL=os.environ.get("MEDICARE_DOCTOR_EMAIL", ""),
        DOCTOR_LOGIN_PASSWORD=os.environ.get("MEDICARE_DOCTOR_PASSWORD", ""),
        DOCTOR_LOGIN_NAME=os.environ.get("MEDICARE_DOCTOR_NAME", "Doctor"),
        ADMIN_LOGIN_EMAIL=os.environ.get("MEDICARE_ADMIN_EMAIL", ""),
        ADMIN_LOGIN_PASSWORD=os.environ.get("MEDICARE_ADMIN_PASSWORD", ""),
        ADMIN_LOGIN_NAME=os.environ.get("MEDICARE_ADMIN_NAME", "Administrator"),
    )
    if test_config:
        app.config.update(test_config)
    initialize_database(app.config["DATABASE"])
    with connection(app.config["DATABASE"]) as db:
        for role in ("doctor", "admin"):
            email = str(app.config[f"{role.upper()}_LOGIN_EMAIL"]).strip()
            password = str(app.config[f"{role.upper()}_LOGIN_PASSWORD"])
            if bool(email) != bool(password):
                raise RuntimeError(f"Configure both the {role} login email and password.")
            if email:
                provision_staff_account(db, role, email, password)

    @app.errorhandler(ServiceError)
    def handle_service_error(error: ServiceError):
        return jsonify({"error": str(error)}), error.status

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        if filename not in ASSET_FILES:
            abort(404)
        return send_from_directory(BASE_DIR, filename)

    @app.post("/api/auth/register")
    def register():
        payload = _json_body()
        with connection(app.config["DATABASE"]) as db:
            account = register_patient(db, payload)
        session.clear()
        session["user_id"] = account["userId"]
        session["patient_id"] = account["patientId"]
        session["role"] = account["role"]
        return jsonify({"user": account["user"], "role": account["role"]}), 201

    @app.post("/api/auth/login")
    def login():
        payload = _json_body()
        with connection(app.config["DATABASE"]) as db:
            account = authenticate_patient(
                db,
                str(payload.get("email", "")),
                str(payload.get("password", "")),
            )
        session.clear()
        session["user_id"] = account["userId"]
        session["patient_id"] = account["patientId"]
        session["role"] = account["role"]
        return jsonify({"user": account["user"], "role": account["role"]})

    @app.post("/api/auth/staff/<role>")
    def staff_login(role: str):
        if role not in {"doctor", "admin"}:
            raise ServiceError("Choose a supported staff sign-in.")
        if not app.config[f"{role.upper()}_LOGIN_EMAIL"]:
            raise ServiceError(
                f"{role.title()} sign-in is not configured. Contact the portal administrator.",
                503,
            )
        payload = _json_body()
        with connection(app.config["DATABASE"]) as db:
            account = authenticate_staff(
                db,
                str(payload.get("email", "")),
                str(payload.get("password", "")),
                role,
            )
        session.clear()
        session["user_id"] = account["userId"]
        session["staff_email"] = account["email"]
        session["staff_name"] = app.config[f"{role.upper()}_LOGIN_NAME"]
        session["role"] = role
        return jsonify(
            {
                "user": {
                    "name": session["staff_name"],
                    "email": account["email"],
                },
                "role": role,
            }
        )

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/bootstrap")
    def bootstrap():
        if not session.get("user_id"):
            return jsonify({"authenticated": False})
        role = session.get("role")
        with connection(app.config["DATABASE"]) as db:
            summary = admin_summary(db)
            if role == "patient":
                patient_id = _current_patient_id()
                user = patient_data(db, patient_id)
                appointments = list_appointments(db, patient_id)
                records = list_records(db, patient_id)
                notifications = list_notifications(db, patient_id)
            elif role == "doctor" and session.get("staff_email"):
                user = {
                    "name": session.get("staff_name", "Doctor"),
                    "email": session["staff_email"],
                }
                appointments = list_all_appointments(db)
                records = list_all_records(db)
                notifications = []
            elif role == "admin" and session.get("staff_email"):
                user = {
                    "name": session.get("staff_name", "Administrator"),
                    "email": session["staff_email"],
                }
                appointments = []
                records = []
                notifications = []
            else:
                session.clear()
                return jsonify({"authenticated": False})
            return jsonify(
                {
                    "authenticated": True,
                    "user": user,
                    "role": role,
                    "doctors": list_doctors(db),
                    "appointments": appointments,
                    "records": records,
                    "departments": summary["departments"],
                    "notifications": notifications,
                    "adminSummary": summary["counts"],
                }
            )

    @app.get("/api/doctors")
    def doctors():
        with connection(app.config["DATABASE"]) as db:
            return jsonify({"doctors": list_doctors(db)})

    @app.get("/api/appointments")
    def appointments():
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            return jsonify({"appointments": list_appointments(db, patient_id)})

    @app.post("/api/appointments")
    def book_appointment():
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            appointment = create_booking(db, patient_id, _json_body())
            return jsonify({"appointment": appointment}), 201

    @app.post("/api/appointments/<int:appointment_id>/cancel")
    def cancel_appointment(appointment_id: int):
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            appointment = cancel_booking(db, patient_id, appointment_id)
            return jsonify({"appointment": appointment})

    @app.post("/api/doctor/appointments/<int:appointment_id>/consultation")
    def save_consultation(appointment_id: int):
        _require_role("doctor")
        with connection(app.config["DATABASE"]) as db:
            appointment = complete_consultation(
                db,
                appointment_id,
                _json_body(),
            )
            return jsonify(
                {
                    "appointment": appointment,
                    "records": list_all_records(db),
                }
            ), 201

    @app.post("/api/appointments/<int:appointment_id>/payment")
    def pay_appointment(appointment_id: int):
        patient_id = _current_patient_id()
        payload = _json_body()
        with connection(app.config["DATABASE"]) as db:
            appointment = pay_completed_appointment(
                db,
                patient_id,
                appointment_id,
                str(payload.get("paymentMethod", "")),
            )
            return jsonify({"appointment": appointment})

    @app.get("/api/receipts/<int:appointment_id>")
    def get_receipt(appointment_id: int):
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            return jsonify(
                {"receipt": receipt_data(db, patient_id, appointment_id)}
            )

    @app.get("/api/payments")
    def payments():
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            paid = [
                appointment
                for appointment in list_appointments(db, patient_id)
                if appointment["paid"]
            ]
            return jsonify({"payments": paid})

    @app.get("/api/records")
    def records():
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            return jsonify({"records": list_records(db, patient_id)})

    @app.put("/api/profile")
    def update_profile():
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            patient = update_patient(db, patient_id, _json_body())
            return jsonify({"user": patient})

    @app.get("/api/notifications")
    def notifications():
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            return jsonify({"notifications": list_notifications(db, patient_id)})

    @app.post("/api/notifications/<int:notification_id>/read")
    def read_notification(notification_id: int):
        patient_id = _current_patient_id()
        with connection(app.config["DATABASE"]) as db:
            mark_notification_read(db, patient_id, notification_id)
            return jsonify({"ok": True})

    def require_admin() -> None:
        _require_role("admin")

    @app.get("/api/admin/summary")
    def admin_dashboard():
        require_admin()
        with connection(app.config["DATABASE"]) as db:
            return jsonify(admin_summary(db))

    @app.post("/api/admin/departments")
    def add_department():
        require_admin()
        payload = _json_body()
        with connection(app.config["DATABASE"]) as db:
            department = create_department(db, str(payload.get("name", "")))
            return jsonify({"department": department}), 201

    @app.post("/api/admin/doctors")
    def add_doctor():
        require_admin()
        with connection(app.config["DATABASE"]) as db:
            doctor = create_doctor(db, _json_body())
            return jsonify({"doctor": doctor}), 201

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
