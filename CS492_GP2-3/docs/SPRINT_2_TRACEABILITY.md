# Sprint 2 Traceability

| Task | User Story | Implementation | Verification |
|---|---|---|---|
| T-029 | US-008 | `/reports`, `student_performance()` and `templates/reports.html` generate combined grade/attendance reports. | `test_performance_report_and_csv_export` |
| T-030 | US-008 | `/reports/<student_id>/export.csv` exports the generated report as CSV. | `test_performance_report_and_csv_export` |
| T-031 | US-009 | `parent_students` table, `/parents`, `/parent-portal`, parent-specific navigation/login routing. | `test_parent_portal_displays_grades_attendance_and_notifications` |
| T-032 | US-009 | Parent portal displays performance summaries plus recent grade and attendance records. | `test_parent_portal_displays_grades_attendance_and_notifications` |
| T-033 | US-010 | `notifications` table and `notify_parents()` create in-app parent notifications when grades/attendance are saved; parent can mark them read. | `test_parent_portal_displays_grades_attendance_and_notifications` |
