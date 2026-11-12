import json
import sqlite3
import uuid
from datetime import date, datetime
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash


PROCESSING_FEE = 15
PAYMENT_METHODS = {"UPI (demo)", "Credit / Debit card (demo)", "Net banking (demo)"}


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def doctor_data(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "specialty": row["specialty"],
        "dept": row["department"],
        "exp": row["experience"],
        "rating": row["rating"],
        "fee": row["fee"],
        "emoji": row["emoji"],
        "about": row["about"],
        "days": json.loads(row["availability_json"]),
        "slots": json.loads(row["slots_json"]),
    }


def list_doctors(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT doctors.*, departments.name AS department
           FROM doctors JOIN departments ON departments.id = doctors.department_id
           ORDER BY doctors.id"""
    )
    return [doctor_data(row) for row in rows]


def patient_data(db: sqlite3.Connection, patient_id: int) -> dict[str, Any]:
    patient = db.execute(
        "SELECT id, name, email, phone FROM patients WHERE id = ?",
        (patient_id,),
    ).fetchone()
    if patient is None:
        raise ServiceError("Patient account was not found.", 404)
    return dict(patient)


def register_patient(
    db: sqlite3.Connection,
    payload: dict[str, Any],
) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    phone = str(payload.get("phone", "")).strip()
    password = str(payload.get("password", ""))
    if not name or len(name) > 120:
        raise ServiceError("Enter a valid full name.")
    if "@" not in email or len(email) > 254:
        raise ServiceError("Enter a valid email address.")
    if len(phone) > 40:
        raise ServiceError("Phone number is too long.")
    if len(password) < 8 or len(password) > 128:
        raise ServiceError("Password must be between 8 and 128 characters.")

    password_hash = generate_password_hash(password)
    existing = db.execute(
        "SELECT id, patient_id, role, password_hash FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if existing:
        if existing["role"] != "patient" or existing["patient_id"] is None:
            raise ServiceError("That email address is already in use.", 409)
        if existing["password_hash"]:
            raise ServiceError("An account already exists for that email.", 409)
        patient_id = existing["patient_id"]
        user_id = existing["id"]
        db.execute(
            "UPDATE patients SET name = ?, phone = ? WHERE id = ?",
            (name, phone, patient_id),
        )
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
    else:
        try:
            cursor = db.execute(
                "INSERT INTO patients (name, email, phone, created_at) VALUES (?, ?, ?, ?)",
                (name, email, phone, datetime.now().astimezone().isoformat(timespec="seconds")),
            )
            patient_id = cursor.lastrowid
            cursor = db.execute(
                """INSERT INTO users (patient_id, email, password_hash, role, created_at)
                   VALUES (?, ?, ?, 'patient', ?)""",
                (
                    patient_id,
                    email,
                    password_hash,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )
            user_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            raise ServiceError("An account already exists for that email.", 409) from None

    return {
        "userId": user_id,
        "patientId": patient_id,
        "role": "patient",
        "user": patient_data(db, patient_id),
    }


def authenticate_patient(
    db: sqlite3.Connection,
    email: str,
    password: str,
) -> dict[str, Any]:
    email = email.strip().lower()
    account = db.execute(
        "SELECT id, patient_id, role, password_hash FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if (
        account is None
        or account["role"] != "patient"
        or account["patient_id"] is None
        or not account["password_hash"]
        or not check_password_hash(account["password_hash"], password)
    ):
        raise ServiceError("Email or password is incorrect.", 401)
    return {
        "userId": account["id"],
        "patientId": account["patient_id"],
        "role": account["role"],
        "user": patient_data(db, account["patient_id"]),
    }


def provision_staff_account(
    db: sqlite3.Connection,
    role: str,
    email: str,
    password: str,
) -> None:
    if role not in {"doctor", "admin"}:
        raise ValueError("Staff role must be doctor or admin.")
    email = email.strip().lower()
    if "@" not in email or len(email) > 254:
        raise ValueError(f"Configure a valid {role} login email.")
    if len(password) < 12 or len(password) > 128:
        raise ValueError(f"Configure a {role} password between 12 and 128 characters.")

    existing = db.execute(
        "SELECT id, patient_id, role FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    if existing is not None:
        if existing["patient_id"] is not None or existing["role"] != role:
            raise RuntimeError(f"The configured {role} login email is already assigned.")
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), existing["id"]),
        )
        return

    db.execute(
        """INSERT INTO users (patient_id, email, password_hash, role, created_at)
           VALUES (NULL, ?, ?, ?, ?)""",
        (
            email,
            generate_password_hash(password),
            role,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        ),
    )


def authenticate_staff(
    db: sqlite3.Connection,
    email: str,
    password: str,
    role: str,
) -> dict[str, Any]:
    if role not in {"doctor", "admin"}:
        raise ServiceError("Choose a supported staff sign-in.")
    account = db.execute(
        "SELECT id, patient_id, role, password_hash FROM users WHERE email = ?",
        (email.strip().lower(),),
    ).fetchone()
    if (
        account is None
        or account["patient_id"] is not None
        or account["role"] != role
        or not account["password_hash"]
        or not check_password_hash(account["password_hash"], password)
    ):
        raise ServiceError("Email or password is incorrect.", 401)
    return {"userId": account["id"], "email": email.strip().lower(), "role": role}


def appointment_data(db: sqlite3.Connection, appointment_id: int) -> dict[str, Any]:
    row = db.execute(
        """SELECT a.id, a.patient_id, a.doctor_id, a.appointment_date, a.appointment_time,
                  a.fee, a.status, d.name AS doctor, d.specialty,
                  patients.name AS patient, patients.email AS patient_email,
                  patients.phone AS patient_phone, payments.receipt_number,
                  payments.transaction_id, payments.payment_method, payments.amount,
                  payments.paid_at
           FROM appointments AS a
           JOIN doctors AS d ON d.id = a.doctor_id
           JOIN patients ON patients.id = a.patient_id
           LEFT JOIN payments ON payments.appointment_id = a.id
           WHERE a.id = ?""",
        (appointment_id,),
    ).fetchone()
    if row is None:
        raise ServiceError("Appointment was not found.", 404)
    paid_at = row["paid_at"]
    return {
        "id": row["id"],
        "patientId": row["patient_id"],
        "patient": row["patient"],
        "patientEmail": row["patient_email"],
        "patientPhone": row["patient_phone"],
        "doctorId": row["doctor_id"],
        "doctor": row["doctor"],
        "specialty": row["specialty"],
        "date": row["appointment_date"],
        "time": row["appointment_time"],
        "fee": row["fee"],
        "status": row["status"],
        "paid": paid_at is not None,
        "paidOn": paid_at[:10] if paid_at else None,
        "paidAt": paid_at,
        "receipt": row["receipt_number"],
        "transactionId": row["transaction_id"],
        "paymentMethod": row["payment_method"],
        "amountPaid": row["amount"],
    }


def list_appointments(db: sqlite3.Connection, patient_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id FROM appointments WHERE patient_id = ? ORDER BY created_at, id",
        (patient_id,),
    )
    return [appointment_data(db, row["id"]) for row in rows]


def list_all_appointments(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute("SELECT id FROM appointments ORDER BY appointment_date, appointment_time, id")
    return [appointment_data(db, row["id"]) for row in rows]


def _records_data(
    db: sqlite3.Connection,
    patient_id: int | None,
) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT records.id, records.appointment_id, records.diagnosis, records.notes,
                  records.patient_id, records.created_at, patients.name AS patient,
                  doctors.name AS doctor,
                  appointments.appointment_date,
                  COALESCE(prescriptions.instructions, '') AS prescription
           FROM medical_records AS records
           JOIN patients ON patients.id = records.patient_id
           JOIN doctors ON doctors.id = records.doctor_id
           JOIN appointments ON appointments.id = records.appointment_id
           LEFT JOIN prescriptions ON prescriptions.medical_record_id = records.id
           WHERE (? IS NULL OR records.patient_id = ?)
           ORDER BY records.created_at, records.id""",
        (patient_id, patient_id),
    )
    return [
        {
            "id": row["id"],
            "appointmentId": row["appointment_id"],
            "patientId": row["patient_id"],
            "diagnosis": row["diagnosis"],
            "notes": row["notes"],
            "prescription": row["prescription"],
            "date": row["appointment_date"],
            "patient": row["patient"],
            "doctor": row["doctor"],
        }
        for row in rows
    ]


def list_records(db: sqlite3.Connection, patient_id: int) -> list[dict[str, Any]]:
    return _records_data(db, patient_id)


def list_all_records(db: sqlite3.Connection) -> list[dict[str, Any]]:
    return _records_data(db, None)


def list_notifications(db: sqlite3.Connection, patient_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT id, notification_type AS type, message, created_at AS createdAt, is_read AS isRead
           FROM notifications WHERE patient_id = ? ORDER BY id DESC LIMIT 20""",
        (patient_id,),
    )
    return [dict(row) for row in rows]


def _notify(
    db: sqlite3.Connection,
    patient_id: int,
    notification_type: str,
    message: str,
) -> None:
    db.execute(
        """INSERT INTO notifications (patient_id, notification_type, message, created_at)
           VALUES (?, ?, ?, ?)""",
        (patient_id, notification_type, message, datetime.now().astimezone().isoformat(timespec="seconds")),
    )


def create_booking(
    db: sqlite3.Connection,
    patient_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    db.execute("BEGIN IMMEDIATE")
    try:
        doctor_id = int(payload.get("doctorId"))
        appointment_date = date.fromisoformat(str(payload.get("date", "")))
    except (TypeError, ValueError):
        raise ServiceError("Choose a valid doctor and appointment date.") from None

    appointment_time = str(payload.get("time", "")).strip()
    payment_method = str(payload.get("paymentMethod", "")).strip()
    if appointment_date < date.today():
        raise ServiceError("Appointment date must be today or later.")
    if payment_method not in PAYMENT_METHODS:
        raise ServiceError("Choose a supported demo payment method.")

    doctor = db.execute(
        """SELECT doctors.*, departments.name AS department
           FROM doctors JOIN departments ON departments.id = doctors.department_id
           WHERE doctors.id = ?""",
        (doctor_id,),
    ).fetchone()
    if doctor is None:
        raise ServiceError("Doctor was not found.", 404)

    clinic_weekday = (appointment_date.weekday() + 1) % 7
    if clinic_weekday not in json.loads(doctor["availability_json"]):
        raise ServiceError("This doctor is not available on the selected date.")
    if appointment_time not in json.loads(doctor["slots_json"]):
        raise ServiceError("Choose one of this doctor's available time slots.")

    existing = db.execute(
        """SELECT 1 FROM appointments
           WHERE doctor_id = ? AND appointment_date = ? AND appointment_time = ?
             AND status = 'Confirmed'""",
        (doctor_id, appointment_date.isoformat(), appointment_time),
    ).fetchone()
    if existing:
        raise ServiceError("That appointment slot has already been booked.", 409)

    now = datetime.now().astimezone()
    try:
        cursor = db.execute(
            """INSERT INTO appointments
               (patient_id, doctor_id, appointment_date, appointment_time, fee, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'Confirmed', ?)""",
            (
                patient_id,
                doctor_id,
                appointment_date.isoformat(),
                appointment_time,
                doctor["fee"],
                now.isoformat(timespec="seconds"),
            ),
        )
    except sqlite3.IntegrityError:
        raise ServiceError("That appointment slot has already been booked.", 409) from None

    appointment_id = cursor.lastrowid
    receipt = f"MC-{now.year}-{uuid.uuid4().hex[:8].upper()}"
    transaction = f"MC-TXN-{uuid.uuid4().hex[:12].upper()}"
    db.execute(
        """INSERT INTO payments
           (appointment_id, receipt_number, transaction_id, consultation_fee,
            processing_fee, amount, payment_method, status, paid_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'Paid', ?)""",
        (
            appointment_id,
            receipt,
            transaction,
            doctor["fee"],
            PROCESSING_FEE,
            doctor["fee"] + PROCESSING_FEE,
            payment_method,
            now.isoformat(timespec="seconds"),
        ),
    )
    _notify(
        db,
        patient_id,
        "appointment_booked",
        f"Appointment with {doctor['name']} confirmed for {appointment_date.isoformat()} at {appointment_time}.",
    )
    return appointment_data(db, appointment_id)


def cancel_booking(
    db: sqlite3.Connection,
    patient_id: int,
    appointment_id: int,
) -> dict[str, Any]:
    appointment = db.execute(
        "SELECT status, doctor_id FROM appointments WHERE id = ? AND patient_id = ?",
        (appointment_id, patient_id),
    ).fetchone()
    if appointment is None:
        raise ServiceError("Appointment was not found.", 404)
    if appointment["status"] != "Confirmed":
        raise ServiceError("Only confirmed appointments can be cancelled.")
    db.execute(
        "UPDATE appointments SET status = 'Cancelled' WHERE id = ?",
        (appointment_id,),
    )
    doctor_name = db.execute(
        "SELECT name FROM doctors WHERE id = ?",
        (appointment["doctor_id"],),
    ).fetchone()["name"]
    _notify(
        db,
        patient_id,
        "appointment_cancelled",
        f"Your appointment with {doctor_name} was cancelled. No real payment was charged.",
    )
    return appointment_data(db, appointment_id)


def complete_consultation(
    db: sqlite3.Connection,
    appointment_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    appointment = db.execute(
        """SELECT patient_id, doctor_id, status FROM appointments
           WHERE id = ?""",
        (appointment_id,),
    ).fetchone()
    if appointment is None:
        raise ServiceError("Appointment was not found.", 404)
    if appointment["status"] != "Confirmed":
        raise ServiceError("This appointment is not awaiting a consultation.")

    diagnosis = str(payload.get("diagnosis", "")).strip()
    if not diagnosis:
        raise ServiceError("Diagnosis is required.")
    notes = str(payload.get("notes", "")).strip()
    prescription_text = str(payload.get("prescription", "")).strip()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    cursor = db.execute(
        """INSERT INTO medical_records
           (appointment_id, patient_id, doctor_id, diagnosis, notes, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            appointment_id,
            appointment["patient_id"],
            appointment["doctor_id"],
            diagnosis,
            notes,
            now,
        ),
    )
    db.execute(
        """INSERT INTO prescriptions (medical_record_id, instructions, created_at)
           VALUES (?, ?, ?)""",
        (cursor.lastrowid, prescription_text, now),
    )
    db.execute(
        "UPDATE appointments SET status = 'Completed' WHERE id = ?",
        (appointment_id,),
    )
    _notify(
        db,
        appointment["patient_id"],
        "consultation_completed",
        "Your consultation record and prescription are now available.",
    )
    return appointment_data(db, appointment_id)


def pay_completed_appointment(
    db: sqlite3.Connection,
    patient_id: int,
    appointment_id: int,
    payment_method: str,
) -> dict[str, Any]:
    if payment_method not in PAYMENT_METHODS:
        raise ServiceError("Choose a supported demo payment method.")
    row = db.execute(
        """SELECT id, fee, status FROM appointments
           WHERE id = ? AND patient_id = ?""",
        (appointment_id, patient_id),
    ).fetchone()
    if row is None:
        raise ServiceError("Appointment was not found.", 404)
    if row["status"] != "Completed":
        raise ServiceError("Payment is available after the consultation is completed.")
    existing = db.execute(
        "SELECT 1 FROM payments WHERE appointment_id = ?",
        (appointment_id,),
    ).fetchone()
    if not existing:
        now = datetime.now().astimezone()
        db.execute(
            """INSERT INTO payments
               (appointment_id, receipt_number, transaction_id, consultation_fee,
                processing_fee, amount, payment_method, status, paid_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'Paid', ?)""",
            (
                appointment_id,
                f"MC-{now.year}-{uuid.uuid4().hex[:8].upper()}",
                f"MC-TXN-{uuid.uuid4().hex[:12].upper()}",
                row["fee"],
                PROCESSING_FEE,
                row["fee"] + PROCESSING_FEE,
                payment_method,
                now.isoformat(timespec="seconds"),
            ),
        )
        _notify(db, patient_id, "payment_recorded", "Your demo payment receipt is ready.")
    return appointment_data(db, appointment_id)


def update_patient(
    db: sqlite3.Connection,
    patient_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    phone = str(payload.get("phone", "")).strip()
    if not name or len(name) > 120:
        raise ServiceError("Enter a valid patient name.")
    if "@" not in email or len(email) > 254:
        raise ServiceError("Enter a valid email address.")
    if len(phone) > 40:
        raise ServiceError("Phone number is too long.")
    try:
        db.execute(
            "UPDATE patients SET name = ?, email = ?, phone = ? WHERE id = ?",
            (name, email, phone, patient_id),
        )
        db.execute(
            "UPDATE users SET email = ? WHERE patient_id = ?",
            (email, patient_id),
        )
    except sqlite3.IntegrityError:
        raise ServiceError("That email address is already in use.", 409) from None
    return patient_data(db, patient_id)


def list_departments(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT departments.id, departments.name, COUNT(doctors.id) AS doctor_count
           FROM departments LEFT JOIN doctors ON doctors.department_id = departments.id
           GROUP BY departments.id ORDER BY departments.name"""
    )
    return [dict(row) for row in rows]


def create_department(db: sqlite3.Connection, name: str) -> dict[str, Any]:
    name = name.strip()
    if not name or len(name) > 80:
        raise ServiceError("Enter a department name of 1–80 characters.")
    try:
        cursor = db.execute("INSERT INTO departments (name) VALUES (?)", (name,))
    except sqlite3.IntegrityError:
        raise ServiceError("That department already exists.", 409) from None
    return {"id": cursor.lastrowid, "name": name, "doctor_count": 0}


def create_doctor(db: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        department_id = int(payload.get("departmentId"))
        fee = int(payload.get("fee"))
        rating = float(payload.get("rating", 0))
        days = sorted({int(day) for day in payload.get("days", [])})
    except (TypeError, ValueError):
        raise ServiceError("Provide valid department, fee, rating, and clinic days.") from None

    name = str(payload.get("name", "")).strip()
    specialty = str(payload.get("specialty", "")).strip()
    experience = str(payload.get("experience", "")).strip()
    about = str(payload.get("about", "")).strip()
    slots = [str(slot).strip() for slot in payload.get("slots", []) if str(slot).strip()]
    if not name or not specialty or not 1 <= fee <= 100000:
        raise ServiceError("Doctor name, specialty, and a valid consultation fee are required.")
    if not days or any(day not in range(1, 7) for day in days):
        raise ServiceError("Select at least one clinic day from Monday to Saturday.")
    if not slots or len(slots) > 12:
        raise ServiceError("Provide between 1 and 12 appointment time slots.")
    if not 0 <= rating <= 5:
        raise ServiceError("Doctor rating must be between 0 and 5.")
    if db.execute("SELECT 1 FROM departments WHERE id = ?", (department_id,)).fetchone() is None:
        raise ServiceError("Department was not found.", 404)

    try:
        cursor = db.execute(
            """INSERT INTO doctors
               (name, specialty, department_id, experience, rating, fee, emoji, about,
                availability_json, slots_json)
               VALUES (?, ?, ?, ?, ?, ?, '👨‍⚕️', ?, ?, ?)""",
            (
                name,
                specialty,
                department_id,
                experience,
                rating,
                fee,
                about,
                json.dumps(days),
                json.dumps(slots),
            ),
        )
    except sqlite3.IntegrityError:
        raise ServiceError("A doctor with that name already exists.", 409) from None
    return doctor_data(
        db.execute(
            """SELECT doctors.*, departments.name AS department
               FROM doctors JOIN departments ON departments.id = doctors.department_id
               WHERE doctors.id = ?""",
            (cursor.lastrowid,),
        ).fetchone()
    )


def admin_summary(db: sqlite3.Connection) -> dict[str, Any]:
    counts = {
        "patients": db.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
        "doctors": db.execute("SELECT COUNT(*) FROM doctors").fetchone()[0],
        "appointments": db.execute("SELECT COUNT(*) FROM appointments").fetchone()[0],
        "departments": db.execute("SELECT COUNT(*) FROM departments").fetchone()[0],
    }
    return {"counts": counts, "departments": list_departments(db), "doctors": list_doctors(db)}


def mark_notification_read(
    db: sqlite3.Connection,
    patient_id: int,
    notification_id: int,
) -> None:
    result = db.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND patient_id = ?",
        (notification_id, patient_id),
    )
    if result.rowcount == 0:
        raise ServiceError("Notification was not found.", 404)


def receipt_data(
    db: sqlite3.Connection,
    patient_id: int,
    appointment_id: int,
) -> dict[str, Any]:
    appointment = appointment_data(db, appointment_id)
    if appointment["patientId"] != patient_id:
        raise ServiceError("Receipt was not found.", 404)
    if not appointment["paid"]:
        raise ServiceError("A receipt is available after payment.", 404)
    return appointment
