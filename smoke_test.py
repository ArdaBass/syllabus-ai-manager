"""
Quick smoke test for the BAU Syllabus System.
Run after any change:   python smoke_test.py
It boots the app with a throwaway in-memory-ish DB copy, logs in as both
roles, and checks that every page renders without a server error.
Exit code 0 = all good, 1 = something broke.
"""
import sys
import app as A

FAILS = []

def check(label, resp, expect=200):
    code = resp.status_code
    ok = code == expect
    print(f"  [{'OK ' if ok else 'FAIL'}] {label:<48} -> {code}")
    if not ok:
        FAILS.append((label, code))

def main():
    A.init_db()

    # ---- Instructor ----
    ci = A.app.test_client()
    r = ci.post("/", data={"username": "ozgeyucelkasap", "password": "123456",
                           "selected_role": "instructor"})
    check("instructor login (redirect)", r, 302)
    for label, url in [
        ("dashboard", "/dashboard"),
        ("account", "/account"),
        ("course info", "/course/2/info"),
        ("syllabus", "/course/2/syllabus"),
        ("edit syllabus", "/course/2/edit"),
        ("deadlines", "/course/2/deadlines"),
        ("exam schedule", "/exam-schedule"),
        ("course schedule", "/course-schedule"),
        ("announcements", "/course/2/announcements"),
        ("policies", "/course/2/policies"),
        ("all policies", "/all-policies"),
        ("new course", "/course/new"),
        ("ai page", "/ai"),
        ("global search (empty)", "/search/global"),
        ("global search (query)", "/search/global?q=exam"),
        ("overview / at-a-glance", "/overview"),
        ("syllabus print view", "/course/2/syllabus/print"),
        ("month calendar", "/calendar"),
        ("calendar (specific month)", "/calendar?y=2026&m=4"),
    ]:
        check(label, ci.get(url))
    check("nonexistent course (graceful redirect)", ci.get("/course/9999/info"), 302)
    # exports return downloadable files
    r = ci.get("/course/2/deadlines.ics")
    check("course .ics export", r)
    print("        -> content-type:", r.headers.get("Content-Type"))
    check("all-courses .ics export", ci.get("/calendar.ics"))
    check("nonexistent course .ics (404)", ci.get("/course/9999/deadlines.ics"), 404)

    # ---- Access control (instructor ozge owns courses 2 & 3; course 1 is oguzhan's) ----
    print("  -- access control --")
    check("instructor BLOCKED from other's course edit (redirect)", ci.get("/course/1/edit"), 302)
    check("instructor BLOCKED from other's course info (redirect)", ci.get("/course/1/info"), 302)
    check("instructor BLOCKED from other's .ics (403)", ci.get("/course/1/deadlines.ics"), 403)

    # ---- Student ----
    cs = A.app.test_client()
    r = cs.post("/", data={"username": "aslıaslan", "password": "123456",
                           "selected_role": "student"})
    check("student login (redirect)", r, 302)
    for label, url in [
        ("dashboard", "/dashboard"),
        ("syllabus", "/course/2/syllabus"),
        ("deadlines", "/course/2/deadlines"),
        ("dept search", "/syllabus/dept-search?q=ai"),
        ("global search (query)", "/search/global?q=midterm"),
        ("overview / at-a-glance", "/overview"),
        ("month calendar", "/calendar"),
        ("ai page", "/ai"),
    ]:
        check(label, cs.get(url))

    # student aslıaslan is Software Engineering; course 1 (INE4211) is Industrial Eng -> blocked
    check("student BLOCKED from other-dept course (redirect)", cs.get("/course/1/syllabus"), 302)

    # progress tracking round-trip: toggle a CSE3011 deadline (id 5) done, confirm it persists
    check("toggle deadline (redirect)", cs.post("/course/2/deadlines/5/toggle"), 302)
    dl = cs.get("/course/2/deadlines").get_data(as_text=True)
    print("        -> progress bar + checked mark after toggle:", "Your progress" in dl and "check-btn checked" in dl)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} route(s) broke -> {FAILS}")
        sys.exit(1)
    print("ALL ROUTES OK")
    sys.exit(0)

if __name__ == "__main__":
    main()
