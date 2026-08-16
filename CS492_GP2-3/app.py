import csv
import io
import os
import sqlite3
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import Flask, Response, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("SCHOOL_DB", BASE_DIR / "school_management.db"))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SCHOOL_SECRET_KEY", "change-this-key-before-production"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=1800,
)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','teacher','student','parent')),
            created_at TEXT NOT NULL,
            last_login_at TEXT
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            date_of_birth TEXT NOT NULL,
            grade_level TEXT NOT NULL,
            guardian_name TEXT,
            guardian_email TEXT,
            created_at TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT NOT NULL UNIQUE COLLATE NOCASE,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            department TEXT NOT NULL,
            user_id INTEGER NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT NOT NULL UNIQUE COLLATE NOCASE,
            course_name TEXT NOT NULL,
            capacity INTEGER NOT NULL DEFAULT 30 CHECK(capacity > 0),
            prerequisite_course_id INTEGER,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            FOREIGN KEY(prerequisite_course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed','dropped')),
            enrolled_at TEXT NOT NULL,
            enrolled_by INTEGER NOT NULL,
            UNIQUE(student_id, course_id),
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses(id),
            FOREIGN KEY(enrolled_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enrollment_id INTEGER NOT NULL,
            attendance_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('present','absent','tardy')),
            recorded_by INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(enrollment_id, attendance_date),
            FOREIGN KEY(enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE,
            FOREIGN KEY(recorded_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enrollment_id INTEGER NOT NULL,
            assignment_name TEXT NOT NULL,
            points_earned REAL NOT NULL CHECK(points_earned >= 0),
            points_possible REAL NOT NULL CHECK(points_possible > 0),
            recorded_by INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(enrollment_id, assignment_name),
            FOREIGN KEY(enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE,
            FOREIGN KEY(recorded_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS parent_students (
            parent_user_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            PRIMARY KEY(parent_user_id, student_id),
            FOREIGN KEY(parent_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_user_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL CHECK(notification_type IN ('attendance','grade','system')),
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            read_at TEXT,
            FOREIGN KEY(recipient_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """
    )
    existing = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if existing is None:
        db.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            ("admin", generate_password_hash("Admin123!"), "admin", datetime.utcnow().isoformat()),
        )

    # Seed a few demonstration courses so Sprint 2 functions are usable immediately.
    for code, name, capacity in (
        ("MATH-101", "Foundations of Mathematics", 30),
        ("ENG-101", "English Composition", 30),
        ("SCI-101", "General Science", 24),
    ):
        db.execute(
            "INSERT OR IGNORE INTO courses (course_code, course_name, capacity) VALUES (?, ?, ?)",
            (code, name, capacity),
        )
    math101 = db.execute("SELECT id FROM courses WHERE course_code='MATH-101'").fetchone()
    db.execute(
        "INSERT OR IGNORE INTO courses (course_code, course_name, capacity, prerequisite_course_id) VALUES (?, ?, ?, ?)",
        ("MATH-201", "Intermediate Mathematics", 25, math101["id"] if math101 else None),
    )
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if "user_id" not in session:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login"))
        return view(**kwargs)
    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(**kwargs):
            if session.get("role") not in roles:
                flash("You are not authorized to access that page.", "danger")
                return redirect(url_for("dashboard"))
            return view(**kwargs)
        return wrapped
    return decorator


@app.before_request
def load_logged_in_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        g.user = get_db().execute(
            "SELECT id, username, role, created_at, last_login_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()


@app.route("/")
def index():
    if not g.user:
        return redirect(url_for("login"))
    return redirect(url_for("parent_portal" if g.user["role"] == "parent" else "dashboard"))


@app.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "danger")
        else:
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            get_db().execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), user["id"]),
            )
            get_db().commit()
            destination = "parent_portal" if user["role"] == "parent" else "dashboard"
            return redirect(url_for(destination))
    return render_template("login.html")


@app.route("/logout", methods=("POST",))
@login_required
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    if session.get("role") == "parent":
        return redirect(url_for("parent_portal"))
    db = get_db()
    stats = {
        "students": db.execute("SELECT COUNT(*) FROM students").fetchone()[0],
        "teachers": db.execute("SELECT COUNT(*) FROM teachers").fetchone()[0],
        "users": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "courses": db.execute("SELECT COUNT(*) FROM courses WHERE active=1").fetchone()[0],
        "enrollments": db.execute("SELECT COUNT(*) FROM enrollments WHERE status='active'").fetchone()[0],
    }
    recent_students = db.execute(
        "SELECT student_id, first_name, last_name, grade_level FROM students ORDER BY id DESC LIMIT 5"
    ).fetchall()
    return render_template("dashboard.html", stats=stats, recent_students=recent_students)


@app.route("/students")
@role_required("admin")
def students():
    records = get_db().execute("SELECT * FROM students ORDER BY last_name, first_name").fetchall()
    return render_template("students.html", students=records)


@app.route("/students/new", methods=("GET", "POST"))
@role_required("admin")
def register_student():
    if request.method == "POST":
        fields = {k: request.form.get(k, "").strip() for k in (
            "student_id", "first_name", "last_name", "date_of_birth", "grade_level",
            "guardian_name", "guardian_email"
        )}
        required = ("student_id", "first_name", "last_name", "date_of_birth", "grade_level")
        if any(not fields[k] for k in required):
            flash("Please complete all required student fields.", "danger")
        else:
            try:
                get_db().execute(
                    """INSERT INTO students
                    (student_id, first_name, last_name, date_of_birth, grade_level,
                     guardian_name, guardian_email, created_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*[fields[k] for k in ("student_id", "first_name", "last_name", "date_of_birth", "grade_level", "guardian_name", "guardian_email")],
                     datetime.utcnow().isoformat(), session["user_id"]),
                )
                get_db().commit()
                flash("Student registered successfully.", "success")
                return redirect(url_for("students"))
            except sqlite3.IntegrityError:
                flash("That student ID already exists.", "danger")
    return render_template("student_form.html")


@app.route("/teachers")
@role_required("admin")
def teachers():
    records = get_db().execute(
        """SELECT t.*, u.username FROM teachers t JOIN users u ON u.id=t.user_id
        ORDER BY t.last_name, t.first_name"""
    ).fetchall()
    return render_template("teachers.html", teachers=records)


@app.route("/teachers/new", methods=("GET", "POST"))
@role_required("admin")
def register_teacher():
    if request.method == "POST":
        fields = {k: request.form.get(k, "").strip() for k in (
            "employee_id", "first_name", "last_name", "email", "department", "username"
        )}
        password = request.form.get("password", "")
        if any(not value for value in fields.values()) or not password:
            flash("Please complete all required teacher fields.", "danger")
        elif len(password) < 8:
            flash("Teacher password must contain at least 8 characters.", "danger")
        else:
            db = get_db()
            try:
                cursor = db.execute(
                    "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'teacher', ?)",
                    (fields["username"], generate_password_hash(password), datetime.utcnow().isoformat()),
                )
                db.execute(
                    """INSERT INTO teachers
                    (employee_id, first_name, last_name, email, department, user_id, created_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fields["employee_id"], fields["first_name"], fields["last_name"], fields["email"],
                     fields["department"], cursor.lastrowid, datetime.utcnow().isoformat(), session["user_id"]),
                )
                db.commit()
                flash("Teacher registered successfully.", "success")
                return redirect(url_for("teachers"))
            except sqlite3.IntegrityError:
                db.rollback()
                flash("Employee ID, email, or username is already in use.", "danger")
    return render_template("teacher_form.html")


@app.route("/users")
@role_required("admin")
def users():
    records = get_db().execute(
        "SELECT id, username, role, created_at, last_login_at FROM users ORDER BY username"
    ).fetchall()
    return render_template("users.html", users=records)


# ----------------------------- Sprint 2: Shared services -----------------------------
def student_performance(db, student_id):
    student = db.execute(
        "SELECT * FROM students WHERE id=?", (student_id,)
    ).fetchone()
    if not student:
        return None

    courses = db.execute(
        """SELECT e.id AS enrollment_id, e.status AS enrollment_status,
        c.course_code, c.course_name
        FROM enrollments e JOIN courses c ON c.id=e.course_id
        WHERE e.student_id=? ORDER BY c.course_code""",
        (student_id,),
    ).fetchall()

    rows = []
    total_earned = total_possible = 0.0
    attendance_totals = {"present": 0, "absent": 0, "tardy": 0, "total": 0}
    for course in courses:
        grade = db.execute(
            "SELECT COALESCE(SUM(points_earned),0), COALESCE(SUM(points_possible),0), COUNT(*) FROM grades WHERE enrollment_id=?",
            (course["enrollment_id"],),
        ).fetchone()
        attendance = db.execute(
            """SELECT
            SUM(CASE WHEN status='present' THEN 1 ELSE 0 END),
            SUM(CASE WHEN status='absent' THEN 1 ELSE 0 END),
            SUM(CASE WHEN status='tardy' THEN 1 ELSE 0 END), COUNT(*)
            FROM attendance WHERE enrollment_id=?""",
            (course["enrollment_id"],),
        ).fetchone()
        earned, possible, grade_items = float(grade[0]), float(grade[1]), int(grade[2])
        present, absent, tardy, attendance_count = [int(v or 0) for v in attendance]
        grade_percent = round(earned / possible * 100, 2) if possible else None
        attendance_percent = round(present / attendance_count * 100, 2) if attendance_count else None
        total_earned += earned
        total_possible += possible
        attendance_totals["present"] += present
        attendance_totals["absent"] += absent
        attendance_totals["tardy"] += tardy
        attendance_totals["total"] += attendance_count
        rows.append({
            "course_code": course["course_code"], "course_name": course["course_name"],
            "enrollment_status": course["enrollment_status"], "points_earned": earned,
            "points_possible": possible, "grade_items": grade_items, "grade_percent": grade_percent,
            "present": present, "absent": absent, "tardy": tardy,
            "attendance_count": attendance_count, "attendance_percent": attendance_percent,
        })

    overall_grade = round(total_earned / total_possible * 100, 2) if total_possible else None
    overall_attendance = (
        round(attendance_totals["present"] / attendance_totals["total"] * 100, 2)
        if attendance_totals["total"] else None
    )
    return {
        "student": student, "courses": rows, "total_earned": total_earned,
        "total_possible": total_possible, "overall_grade": overall_grade,
        "attendance": attendance_totals, "overall_attendance": overall_attendance,
    }


def notify_parents(db, student_id, notification_type, message):
    parents = db.execute(
        "SELECT parent_user_id FROM parent_students WHERE student_id=?", (student_id,)
    ).fetchall()
    now = datetime.utcnow().isoformat()
    for parent in parents:
        db.execute(
            """INSERT INTO notifications
            (recipient_user_id, student_id, notification_type, message, created_at)
            VALUES (?, ?, ?, ?, ?)""",
            (parent["parent_user_id"], student_id, notification_type, message, now),
        )


# ----------------------------- Sprint 2: Enrollment -----------------------------
@app.route("/enrollments", methods=("GET", "POST"))
@role_required("admin")
def enrollments():
    db = get_db()
    if request.method == "POST":
        try:
            student_id = int(request.form.get("student_id", ""))
            course_id = int(request.form.get("course_id", ""))
        except ValueError:
            flash("Select both a student and a course.", "danger")
            return redirect(url_for("enrollments"))

        student = db.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
        course = db.execute("SELECT * FROM courses WHERE id=? AND active=1", (course_id,)).fetchone()
        if not student or not course:
            flash("The selected student or course is unavailable.", "danger")
            return redirect(url_for("enrollments"))

        existing = db.execute(
            "SELECT status FROM enrollments WHERE student_id=? AND course_id=?", (student_id, course_id)
        ).fetchone()
        if existing:
            flash("That student already has an enrollment record for this course.", "danger")
            return redirect(url_for("enrollments"))

        active_count = db.execute(
            "SELECT COUNT(*) FROM enrollments WHERE course_id=? AND status='active'", (course_id,)
        ).fetchone()[0]
        if active_count >= course["capacity"]:
            flash("This course is full and cannot accept another enrollment.", "danger")
            return redirect(url_for("enrollments"))

        prereq_id = course["prerequisite_course_id"]
        if prereq_id:
            completed = db.execute(
                "SELECT id FROM enrollments WHERE student_id=? AND course_id=? AND status='completed'",
                (student_id, prereq_id),
            ).fetchone()
            if not completed:
                prereq = db.execute("SELECT course_code FROM courses WHERE id=?", (prereq_id,)).fetchone()
                flash(f"Prerequisite not met: {prereq['course_code']} must be completed first.", "danger")
                return redirect(url_for("enrollments"))

        db.execute(
            "INSERT INTO enrollments (student_id, course_id, status, enrolled_at, enrolled_by) VALUES (?, ?, 'active', ?, ?)",
            (student_id, course_id, datetime.utcnow().isoformat(), session["user_id"]),
        )
        db.commit()
        flash("Student enrolled successfully.", "success")
        return redirect(url_for("enrollments"))

    students_rows = db.execute("SELECT id, student_id, first_name, last_name FROM students ORDER BY last_name").fetchall()
    course_rows = db.execute(
        """SELECT c.*, p.course_code AS prerequisite_code,
        (SELECT COUNT(*) FROM enrollments e WHERE e.course_id=c.id AND e.status='active') AS enrolled_count
        FROM courses c LEFT JOIN courses p ON p.id=c.prerequisite_course_id
        WHERE c.active=1 ORDER BY c.course_code"""
    ).fetchall()
    records = db.execute(
        """SELECT e.id, e.status, s.student_id AS school_student_id, s.first_name, s.last_name,
        c.course_code, c.course_name
        FROM enrollments e JOIN students s ON s.id=e.student_id JOIN courses c ON c.id=e.course_id
        ORDER BY c.course_code, s.last_name, s.first_name"""
    ).fetchall()
    return render_template("enrollments.html", students=students_rows, courses=course_rows, enrollments=records)


@app.post("/enrollments/<int:enrollment_id>/status")
@role_required("admin")
def update_enrollment_status(enrollment_id):
    status = request.form.get("status", "")
    if status not in {"active", "completed", "dropped"}:
        flash("Invalid enrollment status.", "danger")
    else:
        db = get_db()
        db.execute("UPDATE enrollments SET status=? WHERE id=?", (status, enrollment_id))
        db.commit()
        flash("Enrollment status updated.", "success")
    return redirect(url_for("enrollments"))


# ----------------------------- Sprint 2: Attendance -----------------------------
@app.route("/attendance", methods=("GET", "POST"))
@role_required("admin", "teacher")
def attendance():
    db = get_db()
    courses = db.execute(
        """SELECT c.id, c.course_code, c.course_name
        FROM courses c WHERE c.active=1 AND EXISTS
        (SELECT 1 FROM enrollments e WHERE e.course_id=c.id AND e.status='active')
        ORDER BY c.course_code"""
    ).fetchall()
    course_id = request.values.get("course_id", type=int)
    attendance_date = request.values.get("attendance_date", date.today().isoformat())
    try:
        date.fromisoformat(attendance_date)
    except ValueError:
        attendance_date = date.today().isoformat()
        flash("Invalid attendance date; today's date was selected.", "warning")

    roster = []
    if course_id:
        roster = db.execute(
            """SELECT e.id AS enrollment_id, s.student_id, s.first_name, s.last_name,
            a.status AS attendance_status
            FROM enrollments e JOIN students s ON s.id=e.student_id
            LEFT JOIN attendance a ON a.enrollment_id=e.id AND a.attendance_date=?
            WHERE e.course_id=? AND e.status='active'
            ORDER BY s.last_name, s.first_name""",
            (attendance_date, course_id),
        ).fetchall()

    if request.method == "POST" and course_id:
        if not roster:
            flash("No active students are enrolled in this course.", "warning")
        else:
            valid = {"present", "absent", "tardy"}
            missing = []
            for row in roster:
                status = request.form.get(f"status_{row['enrollment_id']}", "")
                if status not in valid:
                    missing.append(row["student_id"])
                    continue
                db.execute(
                    """INSERT INTO attendance (enrollment_id, attendance_date, status, recorded_by, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(enrollment_id, attendance_date) DO UPDATE SET
                    status=excluded.status, recorded_by=excluded.recorded_by, updated_at=excluded.updated_at""",
                    (row["enrollment_id"], attendance_date, status, session["user_id"], datetime.utcnow().isoformat()),
                )
            if missing:
                db.rollback()
                flash("Every student must be marked present, absent, or tardy before saving.", "danger")
            else:
                for row in roster:
                    status = request.form.get(f"status_{row['enrollment_id']}", "")
                    student = db.execute(
                        "SELECT s.id, s.first_name, s.last_name FROM enrollments e JOIN students s ON s.id=e.student_id WHERE e.id=?",
                        (row["enrollment_id"],),
                    ).fetchone()
                    notify_parents(
                        db, student["id"], "attendance",
                        f"Attendance for {student['first_name']} {student['last_name']} on {attendance_date} was recorded as {status.title()}.",
                    )
                db.commit()
                flash("Attendance saved successfully. Existing entries were updated where needed.", "success")
                return redirect(url_for("attendance", course_id=course_id, attendance_date=attendance_date))

    return render_template(
        "attendance.html", courses=courses, roster=roster, selected_course_id=course_id,
        attendance_date=attendance_date,
    )


# ------------------------------- Sprint 2: Grades -------------------------------
def grade_summary(db, enrollment_id):
    totals = db.execute(
        "SELECT COALESCE(SUM(points_earned),0), COALESCE(SUM(points_possible),0) FROM grades WHERE enrollment_id=?",
        (enrollment_id,),
    ).fetchone()
    earned, possible = float(totals[0]), float(totals[1])
    percent = round((earned / possible * 100), 2) if possible else None
    return earned, possible, percent


@app.route("/grades", methods=("GET", "POST"))
@role_required("admin", "teacher")
def grades():
    db = get_db()
    courses = db.execute(
        """SELECT c.id, c.course_code, c.course_name FROM courses c
        WHERE c.active=1 AND EXISTS (SELECT 1 FROM enrollments e WHERE e.course_id=c.id AND e.status IN ('active','completed'))
        ORDER BY c.course_code"""
    ).fetchall()
    course_id = request.values.get("course_id", type=int)
    enrollment_id = request.values.get("enrollment_id", type=int)
    students_rows = []
    grade_rows = []
    summary = (0, 0, None)

    if course_id:
        students_rows = db.execute(
            """SELECT e.id AS enrollment_id, s.student_id, s.first_name, s.last_name
            FROM enrollments e JOIN students s ON s.id=e.student_id
            WHERE e.course_id=? AND e.status IN ('active','completed') ORDER BY s.last_name, s.first_name""",
            (course_id,),
        ).fetchall()
        if enrollment_id and not any(r["enrollment_id"] == enrollment_id for r in students_rows):
            enrollment_id = None

    if request.method == "POST" and enrollment_id:
        assignment_name = request.form.get("assignment_name", "").strip()
        earned_raw = request.form.get("points_earned", "").strip()
        possible_raw = request.form.get("points_possible", "").strip()
        if not assignment_name or not earned_raw or not possible_raw:
            flash("Assignment name, points earned, and points possible are required.", "danger")
        else:
            try:
                earned = float(earned_raw)
                possible = float(possible_raw)
                if possible <= 0 or earned < 0 or earned > possible:
                    raise ValueError
                db.execute(
                    """INSERT INTO grades (enrollment_id, assignment_name, points_earned, points_possible, recorded_by, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(enrollment_id, assignment_name) DO UPDATE SET
                    points_earned=excluded.points_earned, points_possible=excluded.points_possible,
                    recorded_by=excluded.recorded_by, updated_at=excluded.updated_at""",
                    (enrollment_id, assignment_name, earned, possible, session["user_id"], datetime.utcnow().isoformat()),
                )
                student = db.execute(
                    "SELECT s.id, s.first_name, s.last_name FROM enrollments e JOIN students s ON s.id=e.student_id WHERE e.id=?",
                    (enrollment_id,),
                ).fetchone()
                notify_parents(
                    db, student["id"], "grade",
                    f"Grade posted for {student['first_name']} {student['last_name']}: {assignment_name} — {earned:g}/{possible:g} ({earned / possible * 100:.2f}%).",
                )
                db.commit()
                flash("Grade saved successfully. Final grade was recalculated.", "success")
                return redirect(url_for("grades", course_id=course_id, enrollment_id=enrollment_id))
            except ValueError:
                flash("Scores must be numeric: earned points cannot be negative or exceed points possible, and points possible must be greater than zero.", "danger")

    if enrollment_id:
        grade_rows = db.execute(
            "SELECT * FROM grades WHERE enrollment_id=? ORDER BY assignment_name", (enrollment_id,)
        ).fetchall()
        summary = grade_summary(db, enrollment_id)

    return render_template(
        "grades.html", courses=courses, students=students_rows, grade_rows=grade_rows,
        selected_course_id=course_id, selected_enrollment_id=enrollment_id, summary=summary,
    )


@app.post("/grades/<int:grade_id>/delete")
@role_required("admin", "teacher")
def delete_grade(grade_id):
    db = get_db()
    row = db.execute(
        """SELECT g.enrollment_id, e.course_id FROM grades g JOIN enrollments e ON e.id=g.enrollment_id WHERE g.id=?""",
        (grade_id,),
    ).fetchone()
    if row:
        db.execute("DELETE FROM grades WHERE id=?", (grade_id,))
        db.commit()
        flash("Grade entry removed and final grade recalculated.", "success")
        return redirect(url_for("grades", course_id=row["course_id"], enrollment_id=row["enrollment_id"]))
    flash("Grade entry not found.", "danger")
    return redirect(url_for("grades"))


# -------------------------- Sprint 2: Performance reports --------------------------
@app.get("/reports")
@role_required("admin", "teacher")
def reports():
    db = get_db()
    students_rows = db.execute(
        "SELECT id, student_id, first_name, last_name, grade_level FROM students ORDER BY last_name, first_name"
    ).fetchall()
    student_id = request.args.get("student_id", type=int)
    report = student_performance(db, student_id) if student_id else None
    return render_template("reports.html", students=students_rows, selected_student_id=student_id, report=report)


@app.get("/reports/<int:student_id>/export.csv")
@role_required("admin", "teacher")
def export_report(student_id):
    report = student_performance(get_db(), student_id)
    if not report:
        flash("Student report not found.", "danger")
        return redirect(url_for("reports"))

    output = io.StringIO()
    writer = csv.writer(output)
    student = report["student"]
    writer.writerow(["Student Performance Report"])
    writer.writerow(["Student ID", student["student_id"]])
    writer.writerow(["Student", f"{student['first_name']} {student['last_name']}"])
    writer.writerow(["Grade Level", student["grade_level"]])
    writer.writerow(["Overall Grade", "" if report["overall_grade"] is None else f"{report['overall_grade']:.2f}%"])
    writer.writerow(["Overall Attendance", "" if report["overall_attendance"] is None else f"{report['overall_attendance']:.2f}%"])
    writer.writerow([])
    writer.writerow(["Course", "Course Name", "Status", "Earned", "Possible", "Grade %", "Present", "Absent", "Tardy", "Attendance %"])
    for row in report["courses"]:
        writer.writerow([
            row["course_code"], row["course_name"], row["enrollment_status"],
            f"{row['points_earned']:.2f}", f"{row['points_possible']:.2f}",
            "" if row["grade_percent"] is None else f"{row['grade_percent']:.2f}%",
            row["present"], row["absent"], row["tardy"],
            "" if row["attendance_percent"] is None else f"{row['attendance_percent']:.2f}%",
        ])
    filename = f"{student['student_id']}_performance_report.csv"
    return Response(
        output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------ Sprint 2: Parent portal ------------------------------
@app.route("/parents", methods=("GET", "POST"))
@role_required("admin")
def parents():
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        student_id = request.form.get("student_id", type=int)
        if not username or not password or not student_id:
            flash("Username, password, and student are required.", "danger")
        elif len(password) < 8:
            flash("Parent password must contain at least 8 characters.", "danger")
        else:
            try:
                cursor = db.execute(
                    "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'parent', ?)",
                    (username, generate_password_hash(password), datetime.utcnow().isoformat()),
                )
                db.execute(
                    "INSERT INTO parent_students (parent_user_id, student_id, created_at, created_by) VALUES (?, ?, ?, ?)",
                    (cursor.lastrowid, student_id, datetime.utcnow().isoformat(), session["user_id"]),
                )
                db.commit()
                flash("Parent account created and linked to student.", "success")
                return redirect(url_for("parents"))
            except sqlite3.IntegrityError:
                db.rollback()
                flash("That parent username is already in use.", "danger")

    students_rows = db.execute(
        "SELECT id, student_id, first_name, last_name FROM students ORDER BY last_name, first_name"
    ).fetchall()
    parent_rows = db.execute(
        """SELECT u.username, s.student_id, s.first_name, s.last_name
        FROM parent_students ps JOIN users u ON u.id=ps.parent_user_id
        JOIN students s ON s.id=ps.student_id
        ORDER BY u.username, s.last_name"""
    ).fetchall()
    return render_template("parents.html", students=students_rows, parents=parent_rows)


@app.get("/parent-portal")
@role_required("parent")
def parent_portal():
    db = get_db()
    linked = db.execute(
        """SELECT s.* FROM parent_students ps JOIN students s ON s.id=ps.student_id
        WHERE ps.parent_user_id=? ORDER BY s.last_name, s.first_name""",
        (session["user_id"],),
    ).fetchall()
    selected_student_id = request.args.get("student_id", type=int)
    allowed_ids = {row["id"] for row in linked}
    if selected_student_id not in allowed_ids:
        selected_student_id = linked[0]["id"] if linked else None
    report = student_performance(db, selected_student_id) if selected_student_id else None
    grade_rows = []
    attendance_rows = []
    if selected_student_id:
        grade_rows = db.execute(
            """SELECT c.course_code, g.assignment_name, g.points_earned, g.points_possible, g.updated_at
            FROM grades g JOIN enrollments e ON e.id=g.enrollment_id JOIN courses c ON c.id=e.course_id
            WHERE e.student_id=? ORDER BY g.updated_at DESC, c.course_code LIMIT 30""",
            (selected_student_id,),
        ).fetchall()
        attendance_rows = db.execute(
            """SELECT c.course_code, a.attendance_date, a.status
            FROM attendance a JOIN enrollments e ON e.id=a.enrollment_id JOIN courses c ON c.id=e.course_id
            WHERE e.student_id=? ORDER BY a.attendance_date DESC, c.course_code LIMIT 30""",
            (selected_student_id,),
        ).fetchall()
    notifications = db.execute(
        """SELECT n.*, s.first_name, s.last_name FROM notifications n
        JOIN students s ON s.id=n.student_id
        WHERE n.recipient_user_id=? ORDER BY n.id DESC LIMIT 20""",
        (session["user_id"],),
    ).fetchall()
    return render_template(
        "parent_portal.html", students=linked, selected_student_id=selected_student_id,
        report=report, grade_rows=grade_rows, attendance_rows=attendance_rows, notifications=notifications,
    )


@app.post("/parent-portal/notifications/read")
@role_required("parent")
def mark_notifications_read():
    db = get_db()
    db.execute(
        "UPDATE notifications SET read_at=? WHERE recipient_user_id=? AND read_at IS NULL",
        (datetime.utcnow().isoformat(), session["user_id"]),
    )
    db.commit()
    flash("Notifications marked as read.", "success")
    return redirect(url_for("parent_portal"))


with app.app_context():
    init_db()

if __name__ == "__main__":
    from waitress import serve
    print("School Management System running at http://127.0.0.1:5000")
    serve(app, host="127.0.0.1", port=5000)
