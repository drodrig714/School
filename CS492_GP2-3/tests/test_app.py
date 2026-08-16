import os
import tempfile
import unittest

fd, path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["SCHOOL_DB"] = path

import app as school_app


class SchoolManagementTests(unittest.TestCase):
    def setUp(self):
        self.app = school_app.app
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        with self.app.app_context():
            school_app.init_db()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db = school_app.get_db()
            db.execute("DELETE FROM notifications")
            db.execute("DELETE FROM parent_students")
            db.execute("DELETE FROM attendance")
            db.execute("DELETE FROM grades")
            db.execute("DELETE FROM enrollments")
            db.execute("DELETE FROM teachers")
            db.execute("DELETE FROM students")
            db.execute("DELETE FROM users WHERE username <> 'admin'")
            db.commit()

    def login(self, username="admin", password="Admin123!"):
        return self.client.post("/login", data={"username": username, "password": password})

    def create_student(self, student_id="S100"):
        self.login()
        return self.client.post("/students/new", data={
            "student_id": student_id, "first_name": "Ava", "last_name": "Lee",
            "date_of_birth": "2012-01-02", "grade_level": "7"
        }, follow_redirects=True)

    def get_ids(self, course_code="MATH-101"):
        with self.app.app_context():
            db = school_app.get_db()
            student = db.execute("SELECT id FROM students ORDER BY id DESC LIMIT 1").fetchone()[0]
            course = db.execute("SELECT id FROM courses WHERE course_code=?", (course_code,)).fetchone()[0]
            return student, course

    def enroll_latest_student(self, course_code="MATH-101"):
        student, course = self.get_ids(course_code)
        return self.client.post("/enrollments", data={"student_id": student, "course_id": course}, follow_redirects=True)

    def test_valid_and_invalid_login(self):
        bad = self.client.post("/login", data={"username": "admin", "password": "wrong"})
        self.assertIn(b"Invalid username or password", bad.data)
        good = self.login()
        self.assertEqual(good.status_code, 302)
        self.assertIn("/dashboard", good.location)

    def test_student_registration_and_duplicate_prevention(self):
        first = self.create_student()
        self.assertIn(b"Student registered successfully", first.data)
        second = self.client.post("/students/new", data={
            "student_id":"S100","first_name":"Ava","last_name":"Lee","date_of_birth":"2012-01-02","grade_level":"7"
        }, follow_redirects=True)
        self.assertIn(b"already exists", second.data)

    def test_teacher_registration_hashes_password(self):
        self.login()
        data = {"employee_id":"T100","first_name":"Sam","last_name":"Patel","email":"sam@example.com","department":"Math","username":"spatel","password":"Teacher123!"}
        result = self.client.post("/teachers/new", data=data, follow_redirects=True)
        self.assertIn(b"Teacher registered successfully", result.data)
        with self.app.app_context():
            row = school_app.get_db().execute("SELECT password_hash FROM users WHERE username='spatel'").fetchone()
            self.assertIsNotNone(row)
            self.assertNotEqual(row[0], "Teacher123!")

    def test_role_based_access_blocks_teacher_admin_pages(self):
        self.login()
        self.client.post("/teachers/new", data={"employee_id":"T101","first_name":"Jo","last_name":"Kim","email":"jo@example.com","department":"Science","username":"jkim","password":"Teacher123!"})
        self.client.post("/logout")
        self.login("jkim", "Teacher123!")
        response = self.client.get("/students", follow_redirects=True)
        self.assertIn(b"not authorized", response.data)

    def test_admin_can_enroll_student_and_duplicate_is_blocked(self):
        self.create_student()
        first = self.enroll_latest_student()
        self.assertIn(b"Student enrolled successfully", first.data)
        second = self.enroll_latest_student()
        self.assertIn(b"already has an enrollment", second.data)

    def test_prerequisite_validation_and_completion(self):
        self.create_student()
        blocked = self.enroll_latest_student("MATH-201")
        self.assertIn(b"Prerequisite not met", blocked.data)

        self.enroll_latest_student("MATH-101")
        with self.app.app_context():
            db = school_app.get_db()
            enrollment = db.execute("SELECT id FROM enrollments ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.client.post(f"/enrollments/{enrollment}/status", data={"status": "completed"})
        allowed = self.enroll_latest_student("MATH-201")
        self.assertIn(b"Student enrolled successfully", allowed.data)

    def test_attendance_can_be_recorded_and_edited(self):
        self.create_student()
        self.enroll_latest_student()
        with self.app.app_context():
            db = school_app.get_db()
            enrollment_id = db.execute("SELECT id FROM enrollments ORDER BY id DESC LIMIT 1").fetchone()[0]
            course_id = db.execute("SELECT course_id FROM enrollments WHERE id=?", (enrollment_id,)).fetchone()[0]
        first = self.client.post("/attendance", data={
            "course_id": course_id, "attendance_date": "2026-08-09", f"status_{enrollment_id}": "present"
        }, follow_redirects=True)
        self.assertIn(b"Attendance saved successfully", first.data)
        second = self.client.post("/attendance", data={
            "course_id": course_id, "attendance_date": "2026-08-09", f"status_{enrollment_id}": "tardy"
        }, follow_redirects=True)
        self.assertIn(b"Attendance saved successfully", second.data)
        with self.app.app_context():
            status = school_app.get_db().execute(
                "SELECT status FROM attendance WHERE enrollment_id=?", (enrollment_id,)
            ).fetchone()[0]
            self.assertEqual(status, "tardy")

    def test_grade_validation_and_final_calculation(self):
        self.create_student()
        self.enroll_latest_student()
        with self.app.app_context():
            db = school_app.get_db()
            enrollment_id = db.execute("SELECT id FROM enrollments ORDER BY id DESC LIMIT 1").fetchone()[0]
            course_id = db.execute("SELECT course_id FROM enrollments WHERE id=?", (enrollment_id,)).fetchone()[0]

        bad = self.client.post("/grades", data={
            "course_id": course_id, "enrollment_id": enrollment_id, "assignment_name": "Quiz 1",
            "points_earned": "12", "points_possible": "10"
        }, follow_redirects=True)
        self.assertIn(b"earned points cannot", bad.data)

        self.client.post("/grades", data={
            "course_id": course_id, "enrollment_id": enrollment_id, "assignment_name": "Quiz 1",
            "points_earned": "8", "points_possible": "10"
        })
        result = self.client.post("/grades", data={
            "course_id": course_id, "enrollment_id": enrollment_id, "assignment_name": "Quiz 2",
            "points_earned": "18", "points_possible": "20"
        }, follow_redirects=True)
        self.assertIn(b"86.67%", result.data)

    def test_performance_report_and_csv_export(self):
        self.create_student()
        self.enroll_latest_student()
        with self.app.app_context():
            db = school_app.get_db()
            student_id = db.execute("SELECT id FROM students ORDER BY id DESC LIMIT 1").fetchone()[0]
            enrollment_id = db.execute("SELECT id FROM enrollments ORDER BY id DESC LIMIT 1").fetchone()[0]
            course_id = db.execute("SELECT course_id FROM enrollments WHERE id=?", (enrollment_id,)).fetchone()[0]
        self.client.post("/grades", data={
            "course_id": course_id, "enrollment_id": enrollment_id, "assignment_name": "Quiz 1",
            "points_earned": "9", "points_possible": "10"
        })
        self.client.post("/attendance", data={
            "course_id": course_id, "attendance_date": "2026-08-10", f"status_{enrollment_id}": "present"
        })
        report = self.client.get(f"/reports?student_id={student_id}")
        self.assertIn(b"Student Performance Reports", report.data)
        self.assertIn(b"90.00%", report.data)
        export = self.client.get(f"/reports/{student_id}/export.csv")
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export.mimetype, "text/csv")
        self.assertIn(b"Student Performance Report", export.data)
        self.assertIn(b"MATH-101", export.data)

    def test_parent_portal_displays_grades_attendance_and_notifications(self):
        self.create_student()
        self.enroll_latest_student()
        with self.app.app_context():
            db = school_app.get_db()
            student_id = db.execute("SELECT id FROM students ORDER BY id DESC LIMIT 1").fetchone()[0]
            enrollment_id = db.execute("SELECT id FROM enrollments ORDER BY id DESC LIMIT 1").fetchone()[0]
            course_id = db.execute("SELECT course_id FROM enrollments WHERE id=?", (enrollment_id,)).fetchone()[0]

        created = self.client.post("/parents", data={
            "username": "parent1", "password": "Parent123!", "student_id": student_id
        }, follow_redirects=True)
        self.assertIn(b"Parent account created", created.data)

        self.client.post("/grades", data={
            "course_id": course_id, "enrollment_id": enrollment_id, "assignment_name": "Project",
            "points_earned": "18", "points_possible": "20"
        })
        self.client.post("/attendance", data={
            "course_id": course_id, "attendance_date": "2026-08-11", f"status_{enrollment_id}": "tardy"
        })
        self.client.post("/logout")
        login = self.login("parent1", "Parent123!")
        self.assertIn("/parent-portal", login.location)
        portal = self.client.get("/parent-portal")
        self.assertIn(b"Recent Grades", portal.data)
        self.assertIn(b"Project", portal.data)
        self.assertIn(b"Recent Attendance", portal.data)
        self.assertIn(b"Tardy", portal.data)
        self.assertIn(b"Grade posted", portal.data)
        self.assertIn(b"Attendance for", portal.data)

        with self.app.app_context():
            count = school_app.get_db().execute(
                "SELECT COUNT(*) FROM notifications WHERE recipient_user_id=(SELECT id FROM users WHERE username='parent1')"
            ).fetchone()[0]
            self.assertGreaterEqual(count, 2)



if __name__ == "__main__":
    unittest.main()
