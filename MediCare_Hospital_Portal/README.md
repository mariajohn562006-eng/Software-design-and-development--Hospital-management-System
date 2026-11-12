# MediCare Hospital Management Portal

A responsive MediCare prototype using the supplied presentation, Flask application, business-logic, and SQLite database architecture.

## Run the Flask portal
1. Use Python 3.10 or later.
2. From this folder, install dependencies with `pip install -r requirements.txt`.
3. Run `python app.py`.
4. Open `http://127.0.0.1:5000` in a browser. The app creates `hospital.db` and seeds the demo patient, departments, and doctors on first run.

The HTML template and browser assets are served by Flask. Booking, appointment changes, profiles, consultations, payments, receipts, and notifications are handled by JSON API routes and stored in SQLite.

## Configure staff sign-in
Doctor and Admin sign in separately from patients. Patient registration and login cannot set or change an account's role. Configure a separate email and password for each staff workspace in the process environment before starting the server:

```powershell
$env:MEDICARE_DOCTOR_EMAIL = "doctor@example.com"
$env:MEDICARE_DOCTOR_PASSWORD = "<private password, at least 12 characters>"
$env:MEDICARE_ADMIN_EMAIL = "admin@example.com"
$env:MEDICARE_ADMIN_PASSWORD = "<private password, at least 12 characters>"
python app.py
```

Keep the passwords private and out of source control. The application stores password hashes; changing the environment password updates the matching staff account on startup. If credentials are not configured, that staff login is disabled.

## Included workflows
- Patient registration, password-based sign-in, and sign-out
- Patient profile editing and account details
- Browse and filter doctors by name, speciality, and department
- View each doctor's weekly clinic days and book only available dates and time slots
- Prevent duplicate active bookings for the same doctor/date/time
- Appointment list and cancellation
- Separate Doctor sign-in with a patient queue and consultation record workflow
- Record diagnosis, consultation notes, and prescription
- Patient medical-record timeline with three seeded, clearly marked demo visits and prescription placeholders
- Itemized demo checkout, saved payment details and printable receipt with a transaction reference
- Separate Admin sign-in and dashboard with department and doctor management
- SQLite-backed patients, users, doctors, departments, appointments, medical records, prescriptions, payments, and notifications
- Responsive layout for desktop, tablet, and mobile
- Data persists in `hospital.db`

## Demo flow
1. Register using `alex@example.com` and choose a password to claim the seeded demo patient, or register a new account. The demo patient includes three completed sample visits with record entries, prescription placeholders, and demo receipts.
2. Open **Medical records** to review the sample diagnoses, notes, and prescription placeholders. The same history is shown in the Doctor demo workspace.
3. Open **Find a doctor**, select an available slot, and complete the demo checkout. A receipt appears as soon as the appointment is confirmed.
4. Open **Appointments** to review the booking; use **Billing & receipts** to view its saved receipt. Signing out does not delete saved appointments, records, or payments.
5. Sign out, then use the Doctor or Admin sign-in tab with its separately configured staff account. Patient accounts cannot access either workspace.

## Important prototype limitations
- This is an academic prototype backed by a local SQLite database. It is not a production hospital information system.
- Patient accounts use password hashing and Flask sessions, but this is still an academic prototype, not a production-ready identity system.
- Doctor and Admin accounts are provisioned from server environment variables and have separate API permissions from patients. This prototype still needs production-grade deployment security and operational controls.
- Payment is simulated at booking; no payment gateway is connected and no money is charged. The receipt is marked as a demo receipt.
- Seeded visit history and prescription text are illustrative placeholders, not actual clinical advice or treatment instructions.
- A production deployment needs verified authentication and authorization, CSRF protection, secure secret management, audit logging, encryption, backups, and applicable healthcare privacy safeguards.
- Do not enter real patient-identifiable or sensitive medical information.

## Project structure
- `app.py` — Flask application and API routes
- `services.py` — appointment, consultation, payment, profile, and admin business rules
- `database.py` — SQLite schema, seed data, and connection management
- `templates/index.html` — presentation-layer template
- `app.js` — browser UI and API client
- `styles.css`, `responsive.css` — desktop/mobile presentation
- `hospital.db` — created automatically for persistent application data
- `tests/test_app.py` — focused API and business-rule tests
