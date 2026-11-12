import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


DOCTORS = (
    {
        "name": "Dr. Ananya Rao",
        "specialty": "Cardiology",
        "department": "Heart & Vascular",
        "experience": "12 years",
        "rating": 4.9,
        "fee": 800,
        "emoji": "👩‍⚕️",
        "about": "Preventive cardiology, heart health and non-invasive cardiac care.",
        "days": [1, 3, 5],
        "slots": ["09:00 AM", "10:30 AM", "12:00 PM", "03:00 PM"],
    },
    {
        "name": "Dr. Vikram Menon",
        "specialty": "Dermatology",
        "department": "Skin & Hair",
        "experience": "9 years",
        "rating": 4.8,
        "fee": 600,
        "emoji": "👨‍⚕️",
        "about": "Clinical dermatology, acne care and skin allergy management.",
        "days": [2, 4, 6],
        "slots": ["09:30 AM", "11:00 AM", "02:00 PM", "04:30 PM"],
    },
    {
        "name": "Dr. Meera Iyer",
        "specialty": "Paediatrics",
        "department": "Child Care",
        "experience": "15 years",
        "rating": 5.0,
        "fee": 700,
        "emoji": "👩‍⚕️",
        "about": "Child wellness, vaccination guidance and childhood illnesses.",
        "days": [1, 2, 4],
        "slots": ["10:00 AM", "11:30 AM", "01:30 PM", "04:00 PM"],
    },
    {
        "name": "Dr. Arjun Shah",
        "specialty": "Orthopaedics",
        "department": "Bones & Joints",
        "experience": "11 years",
        "rating": 4.8,
        "fee": 750,
        "emoji": "👨‍⚕️",
        "about": "Sports injuries, joint pain and rehabilitation-focused care.",
        "days": [1, 3, 6],
        "slots": ["09:00 AM", "10:00 AM", "01:00 PM", "03:30 PM"],
    },
    {
        "name": "Dr. Nisha Thomas",
        "specialty": "Neurology",
        "department": "Brain & Nerves",
        "experience": "13 years",
        "rating": 4.9,
        "fee": 900,
        "emoji": "👩‍⚕️",
        "about": "Headache, migraine and neurological assessment.",
        "days": [2, 4, 5],
        "slots": ["09:30 AM", "12:30 PM", "02:30 PM", "05:00 PM"],
    },
    {
        "name": "Dr. Rahul Kapoor",
        "specialty": "General Medicine",
        "department": "Primary Care",
        "experience": "8 years",
        "rating": 4.7,
        "fee": 500,
        "emoji": "👨‍⚕️",
        "about": "Routine consultations, fever, infections and preventive care.",
        "days": [1, 2, 3, 4, 5, 6],
        "slots": ["08:30 AM", "10:30 AM", "01:00 PM", "04:00 PM"],
    },
)

DEMO_VISITS = (
    {
        "doctor": "Dr. Ananya Rao",
        "date": "2026-10-12",
        "time": "10:30 AM",
        "diagnosis": "Preventive cardiology follow-up (demo)",
        "notes": "Sample visit for demonstrating the patient history and records workflow.",
        "prescription": "Demo placeholder: the treating clinician must enter and verify any medication and instructions.",
        "receipt_number": "MC-2026-DEMO01",
        "transaction_id": "MC-TXN-DEMO00001",
    },
    {
        "doctor": "Dr. Meera Iyer",
        "date": "2026-10-13",
        "time": "11:30 AM",
        "diagnosis": "Child wellness consultation (demo)",
        "notes": "Illustrative wellness visit only; this record contains no real patient findings.",
        "prescription": "No medication recorded in this demo visit; follow-up instructions should be entered by a clinician.",
        "receipt_number": "MC-2026-DEMO02",
        "transaction_id": "MC-TXN-DEMO00002",
    },
    {
        "doctor": "Dr. Rahul Kapoor",
        "date": "2026-10-20",
        "time": "10:30 AM",
        "diagnosis": "General medicine follow-up (demo)",
        "notes": "Sample follow-up note for the portal demonstration; not a clinical assessment.",
        "prescription": "Demo placeholder: treatment and dosage must be determined and verified by the treating clinician.",
        "receipt_number": "MC-2026-DEMO03",
        "transaction_id": "MC-TXN-DEMO00003",
    },
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER UNIQUE REFERENCES patients(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'admin')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    specialty TEXT NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    experience TEXT NOT NULL DEFAULT '',
    rating REAL NOT NULL DEFAULT 0,
    fee INTEGER NOT NULL CHECK (fee >= 0),
    emoji TEXT NOT NULL DEFAULT '👨‍⚕️',
    about TEXT NOT NULL DEFAULT '',
    availability_json TEXT NOT NULL,
    slots_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    appointment_date TEXT NOT NULL,
    appointment_time TEXT NOT NULL,
    fee INTEGER NOT NULL CHECK (fee >= 0),
    status TEXT NOT NULL CHECK (status IN ('Confirmed', 'Cancelled', 'Completed')),
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_active_appointment_slot
ON appointments (doctor_id, appointment_date, appointment_time)
WHERE status = 'Confirmed';

CREATE TABLE IF NOT EXISTS medical_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    diagnosis TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prescriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    medical_record_id INTEGER NOT NULL UNIQUE REFERENCES medical_records(id),
    instructions TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
    receipt_number TEXT NOT NULL UNIQUE,
    transaction_id TEXT NOT NULL UNIQUE,
    consultation_fee INTEGER NOT NULL,
    processing_fee INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'INR',
    payment_method TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Paid', 'Refunded')),
    paid_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    notification_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1))
);
"""


@contextmanager
def connection(database_path: str | Path):
    db = sqlite3.connect(database_path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database(database_path: str | Path) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connection(path) as db:
        db.executescript(SCHEMA)
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "password_hash" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        for doctor in DOCTORS:
            db.execute(
                "INSERT OR IGNORE INTO departments (name) VALUES (?)",
                (doctor["department"],),
            )
        db.execute(
            """INSERT OR IGNORE INTO patients (id, name, email, phone, created_at)
               VALUES (1, 'Alex Smith', 'alex@example.com', '+91 98765 43210', datetime('now'))"""
        )
        db.execute(
            """INSERT OR IGNORE INTO users (patient_id, email, role, created_at)
               VALUES (1, 'alex@example.com', 'patient', datetime('now'))"""
        )
        for doctor in DOCTORS:
            department = db.execute(
                "SELECT id FROM departments WHERE name = ?",
                (doctor["department"],),
            ).fetchone()
            db.execute(
                """INSERT OR IGNORE INTO doctors
                   (name, specialty, department_id, experience, rating, fee, emoji,
                    about, availability_json, slots_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doctor["name"],
                    doctor["specialty"],
                    department["id"],
                    doctor["experience"],
                    doctor["rating"],
                    doctor["fee"],
                    doctor["emoji"],
                    doctor["about"],
                    json.dumps(doctor["days"]),
                    json.dumps(doctor["slots"]),
                ),
            )
        for visit in DEMO_VISITS:
            doctor = db.execute(
                "SELECT id, fee FROM doctors WHERE name = ?",
                (visit["doctor"],),
            ).fetchone()
            if doctor is None:
                raise RuntimeError(f"Demo visit references unknown doctor: {visit['doctor']}")

            existing_record = db.execute(
                "SELECT 1 FROM medical_records WHERE patient_id = 1 AND diagnosis = ?",
                (visit["diagnosis"],),
            ).fetchone()
            if existing_record:
                continue

            existing_slot = db.execute(
                """SELECT 1 FROM appointments
                   WHERE patient_id = 1 AND doctor_id = ? AND appointment_date = ?
                     AND appointment_time = ?""",
                (doctor["id"], visit["date"], visit["time"]),
            ).fetchone()
            if existing_slot:
                continue

            created_at = f"{visit['date']}T12:00:00"
            appointment = db.execute(
                """INSERT INTO appointments
                   (patient_id, doctor_id, appointment_date, appointment_time, fee, status, created_at)
                   VALUES (1, ?, ?, ?, ?, 'Completed', ?)""",
                (doctor["id"], visit["date"], visit["time"], doctor["fee"], created_at),
            )
            record = db.execute(
                """INSERT INTO medical_records
                   (appointment_id, patient_id, doctor_id, diagnosis, notes, created_at)
                   VALUES (?, 1, ?, ?, ?, ?)""",
                (
                    appointment.lastrowid,
                    doctor["id"],
                    visit["diagnosis"],
                    visit["notes"],
                    created_at,
                ),
            )
            db.execute(
                """INSERT INTO prescriptions (medical_record_id, instructions, created_at)
                   VALUES (?, ?, ?)""",
                (record.lastrowid, visit["prescription"], created_at),
            )
            db.execute(
                """INSERT INTO payments
                   (appointment_id, receipt_number, transaction_id, consultation_fee,
                    processing_fee, amount, payment_method, status, paid_at)
                   VALUES (?, ?, ?, ?, 15, ?, 'UPI (demo)', 'Paid', ?)""",
                (
                    appointment.lastrowid,
                    visit["receipt_number"],
                    visit["transaction_id"],
                    doctor["fee"],
                    doctor["fee"] + 15,
                    created_at,
                ),
            )
