import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from app import create_app
from database import initialize_database


class PortalApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test-hospital.db"
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(database_path),
                "SECRET_KEY": "test-only-secret",
                "DOCTOR_LOGIN_EMAIL": "doctor@medicare.test",
                "DOCTOR_LOGIN_PASSWORD": "TestDoctorPass123!",
                "ADMIN_LOGIN_EMAIL": "admin@medicare.test",
                "ADMIN_LOGIN_PASSWORD": "TestAdminPass123!",
            }
        )
        self.client = self.app.test_client()
        registration = self.client.post(
            "/api/auth/register",
            json={
                "name": "Test Patient",
                "email": "patient@example.com",
                "phone": "+91 90000 00000",
                "password": "TestPassword123!",
                "role": "admin",
            },
        )
        self.assertEqual(registration.status_code, 201)
        self.assertEqual(registration.json["role"], "patient")
        self.doctor = self.client.get("/api/doctors").json["doctors"][0]

    def tearDown(self):
        self.temp_dir.cleanup()

    def next_doctor_day(self):
        candidate = date.today() + timedelta(days=1)
        while (candidate.weekday() + 1) % 7 not in self.doctor["days"]:
            candidate += timedelta(days=1)
        return candidate.isoformat()

    def book(self, **overrides):
        payload = {
            "doctorId": self.doctor["id"],
            "date": self.next_doctor_day(),
            "time": self.doctor["slots"][0],
            "paymentMethod": "UPI (demo)",
        }
        payload.update(overrides)
        return self.client.post("/api/appointments", json=payload)

    def test_booking_persists_paid_receipt_and_notification(self):
        response = self.book()
        self.assertEqual(response.status_code, 201)
        appointment = response.json["appointment"]
        self.assertEqual(appointment["status"], "Confirmed")
        self.assertTrue(appointment["paid"])
        self.assertEqual(appointment["amountPaid"], self.doctor["fee"] + 15)
        self.assertTrue(appointment["receipt"].startswith("MC-"))

        receipt = self.client.get(f"/api/receipts/{appointment['id']}")
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.json["receipt"]["transactionId"], appointment["transactionId"])
        self.assertEqual(len(self.client.get("/api/notifications").json["notifications"]), 1)

    def test_unavailable_day_and_duplicate_slot_are_rejected(self):
        unavailable = date.today() + timedelta(days=1)
        while (unavailable.weekday() + 1) % 7 in self.doctor["days"]:
            unavailable += timedelta(days=1)
        self.assertEqual(self.book(date=unavailable.isoformat()).status_code, 400)

        date_value = self.next_doctor_day()
        self.assertEqual(self.book(date=date_value).status_code, 201)
        duplicate = self.book(date=date_value)
        self.assertEqual(duplicate.status_code, 409)

    def test_cancellation_releases_slot_and_consultation_saves_record(self):
        booked = self.book()
        appointment = booked.json["appointment"]
        cancelled = self.client.post(f"/api/appointments/{appointment['id']}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json["appointment"]["status"], "Cancelled")

        rebooked = self.book(date=appointment["date"], time=appointment["time"])
        self.assertEqual(rebooked.status_code, 201)
        appointment_id = rebooked.json["appointment"]["id"]
        doctor_client = self.app.test_client()
        doctor_login = doctor_client.post(
            "/api/auth/staff/doctor",
            json={
                "email": "doctor@medicare.test",
                "password": "TestDoctorPass123!",
            },
        )
        self.assertEqual(doctor_login.status_code, 200)
        completed = doctor_client.post(
            f"/api/doctor/appointments/{appointment_id}/consultation",
            json={
                "diagnosis": "Routine follow-up",
                "notes": "Vitals reviewed.",
                "prescription": "Continue current care plan.",
            },
        )
        self.assertEqual(completed.status_code, 201)
        self.assertEqual(completed.json["appointment"]["status"], "Completed")
        record = self.client.get("/api/records").json["records"][0]
        self.assertEqual(record["diagnosis"], "Routine follow-up")
        self.assertEqual(record["prescription"], "Continue current care plan.")

    def test_admin_role_can_manage_departments_and_doctors(self):
        self.assertEqual(self.client.get("/api/admin/summary").status_code, 403)
        admin_client = self.app.test_client()
        login = admin_client.post(
            "/api/auth/staff/admin",
            json={
                "email": "admin@medicare.test",
                "password": "TestAdminPass123!",
            },
        )
        self.assertEqual(login.status_code, 200)
        department = admin_client.post(
            "/api/admin/departments",
            json={"name": "Rehabilitation"},
        )
        self.assertEqual(department.status_code, 201)
        doctor = admin_client.post(
            "/api/admin/doctors",
            json={
                "name": "Dr. Test User",
                "specialty": "Rehabilitation",
                "departmentId": department.json["department"]["id"],
                "fee": 450,
                "rating": 4.5,
                "days": [1, 3],
                "slots": ["09:00 AM"],
                "experience": "5 years",
                "about": "Rehabilitation care.",
            },
        )
        self.assertEqual(doctor.status_code, 201)
        self.assertEqual(doctor.json["doctor"]["dept"], "Rehabilitation")

    def test_staff_workspaces_require_separate_staff_sign_in(self):
        self.assertEqual(
            self.client.post(
                "/api/auth/staff/doctor",
                json={"email": "patient@example.com", "password": "TestPassword123!"},
            ).status_code,
            401,
        )
        self.assertEqual(self.client.get("/api/admin/summary").status_code, 403)
        self.assertEqual(self.client.get("/api/records").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/doctor/appointments/1/consultation",
                json={"diagnosis": "Not permitted"},
            ).status_code,
            403,
        )
        self.assertEqual(self.client.put("/api/session/role", json={"role": "admin"}).status_code, 404)

        doctor_client = self.app.test_client()
        doctor_login = doctor_client.post(
            "/api/auth/staff/doctor",
            json={
                "email": "doctor@medicare.test",
                "password": "TestDoctorPass123!",
            },
        )
        self.assertEqual(doctor_login.status_code, 200)
        bootstrap = doctor_client.get("/api/bootstrap").json
        self.assertEqual(bootstrap["role"], "doctor")
        self.assertEqual(len(bootstrap["records"]), 3)
        self.assertEqual(doctor_client.get("/api/admin/summary").status_code, 403)
        self.assertEqual(doctor_client.get("/api/records").status_code, 403)

        admin_client = self.app.test_client()
        admin_login = admin_client.post(
            "/api/auth/staff/admin",
            json={
                "email": "admin@medicare.test",
                "password": "TestAdminPass123!",
            },
        )
        self.assertEqual(admin_login.status_code, 200)
        admin_bootstrap = admin_client.get("/api/bootstrap").json
        self.assertEqual(admin_bootstrap["role"], "admin")
        self.assertEqual(admin_bootstrap["records"], [])
        self.assertEqual(admin_client.get("/api/admin/summary").status_code, 200)

    def test_profile_update_and_asset_serving(self):
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("/assets/app.js", index.get_data(as_text=True))
        profile = self.client.put(
            "/api/profile",
            json={
                "name": "Alex Patient",
                "email": "alex.patient@example.com",
                "phone": "+91 90000 00000",
            },
        )
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json["user"]["name"], "Alex Patient")
        asset = self.client.get("/assets/app.js")
        self.assertEqual(asset.status_code, 200)
        asset.close()
        self.assertEqual(self.client.get("/assets/app.py").status_code, 404)

    def test_registration_login_logout_and_account_data_persistence(self):
        client = self.app.test_client()
        self.assertFalse(client.get("/api/bootstrap").json["authenticated"])
        self.assertEqual(client.get("/api/appointments").status_code, 401)

        payload = {
            "name": "New Patient",
            "email": "new.patient@example.com",
            "phone": "+91 91111 11111",
            "password": "StrongPassword123!",
        }
        registered = client.post("/api/auth/register", json=payload)
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.json["user"]["email"], payload["email"])
        self.assertEqual(client.post("/api/auth/register", json=payload).status_code, 409)

        booked = client.post(
            "/api/appointments",
            json={
                "doctorId": self.doctor["id"],
                "date": self.next_doctor_day(),
                "time": self.doctor["slots"][0],
                "paymentMethod": "UPI (demo)",
            },
        )
        self.assertEqual(booked.status_code, 201)
        appointment_id = booked.json["appointment"]["id"]
        self.assertEqual(client.post("/api/auth/logout").status_code, 200)
        self.assertFalse(client.get("/api/bootstrap").json["authenticated"])
        self.assertEqual(
            client.post(
                "/api/auth/login",
                json={"email": payload["email"], "password": "incorrect"},
            ).status_code,
            401,
        )
        login = client.post(
            "/api/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
        self.assertEqual(login.status_code, 200)
        appointments = client.get("/api/appointments").json["appointments"]
        self.assertEqual([item["id"] for item in appointments], [appointment_id])
        self.assertEqual(client.post("/api/auth/logout").status_code, 200)

    def test_seeded_demo_history_connects_appointments_records_prescriptions_and_payments(self):
        client = self.app.test_client()
        registration = client.post(
            "/api/auth/register",
            json={
                "name": "Alex Smith",
                "email": "alex@example.com",
                "phone": "+91 98765 43210",
                "password": "DemoPatientPass123!",
            },
        )
        self.assertEqual(registration.status_code, 201)

        appointments = client.get("/api/appointments").json["appointments"]
        records = client.get("/api/records").json["records"]
        self.assertEqual(len(appointments), 3)
        self.assertTrue(all(item["status"] == "Completed" and item["paid"] for item in appointments))
        self.assertEqual(len(records), 3)
        self.assertTrue(all(record["prescription"] for record in records))
        self.assertTrue(all("(demo)" in record["diagnosis"] for record in records))

        initialize_database(self.app.config["DATABASE"])
        self.assertEqual(len(client.get("/api/records").json["records"]), 3)


if __name__ == "__main__":
    unittest.main()
