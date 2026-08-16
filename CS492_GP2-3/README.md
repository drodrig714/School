# CS492 School Management System — Sprint 2

This runnable Flask/SQLite application represents the completed Sprint 2 product and retains the Sprint 1 foundation.

## Sprint 2 functionality — final tasks
- **T-029 / US-008 — Generate student performance reports:** administrators and teachers can select a student and generate a combined report with course grades, attendance totals, overall grade percentage, and present-rate percentage.
- **T-030 / US-008 — Export reports:** generated student performance reports can be downloaded as CSV files for sharing or further analysis.
- **T-031 / US-009 — Develop parent portal:** administrators can create secure parent accounts linked to student records; parent users are routed to a dedicated portal after login.
- **T-032 / US-009 — Display attendance and grades in parent portal:** parents can view overall performance, per-course grade/attendance summaries, recent assignment grades, and recent attendance entries for linked students.
- **T-033 / US-010 — Implement notification service:** when teachers/admins save grades or attendance, the application creates in-app notifications for linked parent accounts. Parents can review and mark notifications as read.

## Sprint 2 functionality — previously completed tasks
- **T-021 / US-005 — Attendance interface:** teachers/admins can select a course and date and view the active class roster.
- **T-022 — Record daily attendance:** each student can be marked Present, Absent, or Tardy and saved.
- **T-023 — Edit attendance records:** loading a previously saved course/date displays current values; saving updates those records.
- **T-024 / US-006 — Grade entry module:** teachers/admins can select a course/student and enter assignment scores.
- **T-025 — Calculate final grades:** the gradebook automatically totals earned/possible points and calculates a final percentage.
- **T-026 — Validate grading rules:** required fields are enforced; scores must be numeric, non-negative, earned points cannot exceed possible points, and possible points must be greater than zero.
- **T-027 / US-007 — Course enrollment:** administrators can enroll students in active courses and update enrollment status.
- **T-028 — Validate enrollment prerequisites:** enrollment rejects full courses and courses whose prerequisite has not been completed.

## Sprint 1 functionality retained
- Secure login with generic invalid-credential errors
- Password hashing using Werkzeug
- Protected sessions and logout
- Role-based access control
- Student and teacher registration
- SQLite persistence
- Unit tests

## Run on Windows
1. Install Python 3.10 or newer from python.org. During installation, select **Add Python to PATH**.
2. Double-click `run.bat`.
3. The first run installs the required packages and opens `http://127.0.0.1:5000`.

## Run on macOS/Linux
```bash
./run.sh
```

## Demo administrator
- Username: `admin`
- Password: `Admin123!`

## Suggested Sprint 2 final demo flow
1. Register a student and enroll the student in `MATH-101`.
2. Open **Parents** as admin and create a parent login linked to that student.
3. Enter one or more grades and record attendance for the student.
4. Open **Reports**, generate the student performance report, and use **Export CSV**.
5. Sign out and sign in with the parent account.
6. Show the parent portal grade summary, attendance summary, recent grade/attendance tables, and notifications.
7. Use **Mark All Read** to demonstrate notification status handling.

## Run tests
```bash
python -m unittest discover -s tests -v
```

## Data
The database file `school_management.db` is created automatically in the project folder. Delete it to reset demonstration data. Change the default password and `SCHOOL_SECRET_KEY` before any real deployment.
