from flask import Flask, render_template, request, session, redirect, url_for, jsonify, Response, abort, flash, get_flashed_messages
from dotenv import load_dotenv
from datetime import date, datetime, timedelta
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename
import os
import uuid
import json
import calendar as _calmod
load_dotenv()
from db import get_conn, init_db
from ai_chat import ask_ai

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "pptx", "ppt", "docx", "doc", "png", "jpg", "jpeg"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me-in-.env")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# ── CONTEXT PROCESSOR (bildirim sayısı her sayfada mevcut) ───────────────────
@app.context_processor
def inject_notif_count():
    if "user_id" in session:
        try:
            conn = get_conn()
            cnt = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                (session["user_id"],)
            ).fetchone()[0]
            conn.close()
            return {"notif_count": cnt}
        except Exception:
            pass
    return {"notif_count": 0}

# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        selected_role = request.form.get("selected_role", "student").strip()

        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND role=?",
            (u, selected_role)
        ).fetchone()
        conn.close()

        if not row or not check_password_hash(row["password"], p):
            return render_template(
                "login.html",
                error=f"Invalid {selected_role} credentials."
            )

        session["user_id"]   = row["id"]
        session["username"]  = row["username"]
        session["full_name"] = row["full_name"] or row["username"]
        session["role"]      = row["role"]
        session["chat_history"] = []

        return redirect(url_for("dashboard"))

    return render_template("login.html", error=None)
 


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ── HELPERS ───────────────────────────────────────────────────────────────────

def get_user_courses():
    conn = get_conn()
    if session["role"] == "student":
        rows = conn.execute("""SELECT c.* FROM courses c
                               JOIN enrollments e ON e.course_id=c.id
                               WHERE e.student_id=?""", (session["user_id"],)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM courses WHERE instructor_id=?",
                            (session["user_id"],)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_course(course_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_upcoming_deadlines(courses, limit=5):
    """Collect future deadlines across the given courses, soonest first."""
    today = date.today()
    conn = get_conn()
    items = []
    for c in courses:
        rows = conn.execute(
            "SELECT title, due_date FROM deadlines WHERE course_id=?", (c["id"],)
        ).fetchall()
        for r in rows:
            try:
                due = datetime.strptime(r["due_date"].strip(), "%Y-%m-%d").date()
            except (ValueError, AttributeError):
                continue  # skip unparseable dates rather than crashing
            days = (due - today).days
            if days < 0:
                continue  # past
            items.append({
                "title": r["title"],
                "due_date": r["due_date"],
                "course_code": c["code"],
                "course_id": c["id"],
                "days": days,
            })
    conn.close()
    items.sort(key=lambda x: x["days"])
    return items[:limit]

def can_access_course(course):
    """Instructor: kendi dersi. Öğrenci: SADECE kayıtlı olduğu ders (bölüm geneli erişim yok)."""
    if not course:
        return False
    if session.get("role") == "instructor":
        return course["instructor_id"] == session.get("user_id")
    conn = get_conn()
    enrolled = conn.execute(
        "SELECT 1 FROM enrollments WHERE student_id=? AND course_id=?",
        (session.get("user_id"), course["id"])
    ).fetchone()
    conn.close()
    return bool(enrolled)

def instructor_owns_course(course_id):
    """True only if the logged-in instructor owns this course."""
    if session.get("role") != "instructor":
        return False
    course = get_course(course_id)
    return bool(course) and course["instructor_id"] == session.get("user_id")

def _create_notifications(course_id, message, notif_type="info"):
    """Bir dersteki tüm kayıtlı öğrencilere bildirim oluştur."""
    conn = get_conn()
    students = conn.execute(
        "SELECT student_id FROM enrollments WHERE course_id=?", (course_id,)
    ).fetchall()
    for s in students:
        conn.execute(
            "INSERT INTO notifications(user_id, course_id, message, notif_type) VALUES(?,?,?,?)",
            (s["student_id"], course_id, message, notif_type)
        )
    conn.commit()
    conn.close()

def _log_event(event_type, page=None, course_id=None, extra=None):
    """Kullanım analitiği için olay kaydı."""
    if "user_id" not in session:
        return
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO analytics_events(user_id, event_type, page, course_id, extra) VALUES(?,?,?,?,?)",
            (session["user_id"], event_type, page, course_id,
             json.dumps(extra) if extra else None)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ── DASHBOARD ─────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    courses = get_user_courses()
    return render_template("dashboard.html",
                           user=session, courses=courses,
                           current_course=courses[0] if courses else None,
                           upcoming=get_upcoming_deadlines(courses))

@app.route("/account")
@login_required
def account():
    return render_template(
        "account.html",
        user=session,
        courses=get_user_courses(),
        current_course=get_user_courses()[0] if get_user_courses() else None
    )
# ── COURSE INFO ───────────────────────────────────────────────────────────────

@app.route("/course/<int:course_id>/info")
@login_required
def course_info(course_id):
    course = get_course(course_id)
    if not course:
        return redirect(url_for('dashboard'))
    if not can_access_course(course):
        return redirect(url_for('dashboard'))
    conn = get_conn()
    instructor = conn.execute("SELECT username, full_name, title FROM users WHERE id=?",
                              (course["instructor_id"],)).fetchone()
    sections = conn.execute("SELECT * FROM syllabus_sections WHERE course_id=?",
                            (course_id,)).fetchall()
    conn.close()
    return render_template("course_info.html",
                           user=session, courses=get_user_courses(),
                           course=course, instructor=instructor,
                           sections=[dict(s) for s in sections])

# ── SYLLABUS ──────────────────────────────────────────────────────────────────

@app.route("/course/<int:course_id>/syllabus")
@login_required
def syllabus(course_id):
    course = get_course(course_id)
    if not course:
        return redirect(url_for('dashboard'))
    if not can_access_course(course):
        return redirect(url_for('dashboard'))
    conn = get_conn()
    sections = conn.execute("SELECT * FROM syllabus_sections WHERE course_id=?",
                            (course_id,)).fetchall()
    conn.close()
    return render_template("syllabus.html",
                           user=session, courses=get_user_courses(),
                           course=course, sections=[dict(s) for s in sections])

# ── SYLLABUS SEARCH (ders kodu/adına göre) ────────────────────────────────────


@app.route("/syllabus/search")
@login_required
def syllabus_search():
    q = request.args.get("q", "").strip()
    found_course = None
    sections = []

    if q:
        conn = get_conn()
        if session["role"] == "student":
            # Kayıtlı olduğu VEYA aynı bölümdeki dersleri görebilir
            row = conn.execute("""
                SELECT c.* FROM courses c
                JOIN enrollments e ON e.course_id = c.id
                WHERE e.student_id = ?
                AND (LOWER(c.code) LIKE ? OR LOWER(c.name) LIKE ?)
            """, (session["user_id"],
                f"%{q.lower()}%", f"%{q.lower()}%")).fetchone()
        else:
            # Instructor sadece kendi derslerini görür
            row = conn.execute("""
                SELECT * FROM courses
                WHERE instructor_id = ?
                AND (LOWER(code) LIKE ? OR LOWER(name) LIKE ?)
            """, (session["user_id"],
                  f"%{q.lower()}%", f"%{q.lower()}%")).fetchone()

        if row:
            found_course = dict(row)
            sections = [dict(s) for s in conn.execute(
                "SELECT * FROM syllabus_sections WHERE course_id=?",
                (found_course["id"],)
            ).fetchall()]
        conn.close()

    user_courses = get_user_courses()
    return render_template("syllabus.html",
                           user=session,
                           courses=user_courses,
                           current_course=user_courses[0] if user_courses else None,
                           course=found_course,
                           sections=sections,
                           q=q)

@app.route("/syllabus/dept-search")
@login_required
def syllabus_dept_search():
    q = request.args.get("q", "").strip()
    found_course = None
    sections = []

    if q:
        conn = get_conn()
        if session["role"] == "student":
            # Sadece kayıtlı olduğu dersleri ara
            row = conn.execute("""
                SELECT c.* FROM courses c
                JOIN enrollments e ON e.course_id = c.id
                WHERE e.student_id = ?
                AND (LOWER(c.code) LIKE ? OR LOWER(c.name) LIKE ?)
            """, (session["user_id"],
                  f"%{q.lower()}%", f"%{q.lower()}%")).fetchone()
        else:
            row = conn.execute("""
                SELECT * FROM courses
                WHERE instructor_id = ?
                AND (LOWER(code) LIKE ? OR LOWER(name) LIKE ?)
            """, (session["user_id"],
                  f"%{q.lower()}%", f"%{q.lower()}%")).fetchone()

        if row:
            found_course = dict(row)
            sections = [dict(s) for s in conn.execute(
                "SELECT * FROM syllabus_sections WHERE course_id=?",
                (found_course["id"],)
            ).fetchall()]
        conn.close()

    _log_event("search", page="syllabus_search", extra={"q": q})
    user_courses = get_user_courses()
    return render_template("search.html",
                           user=session,
                           courses=user_courses,
                           current_course=user_courses[0] if user_courses else None,
                           course=found_course,
                           sections=sections,
                           q=q)
# ── DEADLINES ─────────────────────────────────────────────────────────────────

@app.route("/course/<int:course_id>/deadlines", methods=["GET", "POST"])
@login_required
def deadlines(course_id):
    course = get_course(course_id)
    if not course:
        return redirect(url_for('dashboard'))
    if not can_access_course(course):
        return redirect(url_for('dashboard'))
    conn = get_conn()
    if request.method == "POST" and session["role"] == "instructor":
        title    = request.form.get("title", "").strip()
        due_date = request.form.get("due_date", "").strip()
        if title and due_date:
            conn.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                         (course_id, title, due_date))
            conn.commit()
            _create_notifications(
                course_id,
                f"📅 Yeni deadline ({course['code']}): {title} — {due_date}",
                "deadline"
            )
            _log_event("deadline_add", course_id=course_id)

    filter_type = request.args.get("filter", "")  

    if filter_type == "exams":
        rows = conn.execute("""SELECT * FROM deadlines WHERE course_id=?
                               AND (LOWER(title) LIKE '%exam%'
                                 OR LOWER(title) LIKE '%midterm%'
                                 OR LOWER(title) LIKE '%final%')
                               ORDER BY due_date""", (course_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM deadlines WHERE course_id=? ORDER BY due_date",
                            (course_id,)).fetchall()

    conn.close()

    # Student progress: mark which deadlines this student has checked off.
    progress = None
    if session["role"] == "student":
        pconn = get_conn()
        done_rows = pconn.execute(
            "SELECT deadline_id FROM deadline_progress WHERE student_id=? AND done=1",
            (session["user_id"],)
        ).fetchall()
        pconn.close()
        done_ids = {r["deadline_id"] for r in done_rows}
        dl_list = [dict(r) for r in rows]
        for d in dl_list:
            d["done"] = d["id"] in done_ids
        total = len(dl_list)
        done = sum(1 for d in dl_list if d["done"])
        progress = {"done": done, "total": total,
                    "pct": round(done / total * 100) if total else 0}
        return render_template("deadlines.html",
                               user=session, courses=get_user_courses(),
                               course=course, deadlines=dl_list,
                               filter_type=filter_type, progress=progress)

    return render_template("deadlines.html",
                           user=session, courses=get_user_courses(),
                           course=course, deadlines=[dict(r) for r in rows],
                           filter_type=filter_type)   

@app.route("/course/<int:course_id>/deadlines/<int:dl_id>/delete", methods=["POST"])
@login_required
def delete_deadline(course_id, dl_id):
    if instructor_owns_course(course_id):
        conn = get_conn()
        conn.execute("DELETE FROM deadlines WHERE id=? AND course_id=?", (dl_id, course_id))
        conn.commit()
        conn.close()
    return redirect(url_for("deadlines", course_id=course_id))


@app.route("/course-schedule")
@login_required
def course_schedule():
    courses = get_user_courses()
    return render_template("course_schedule.html",
                           user=session,
                           courses=courses,
                           current_course=courses[0] if courses else None)
@app.route("/exam-schedule")
@login_required
def exam_schedule():
    courses = get_user_courses()
    conn = get_conn()
    all_exams = []
    for c in courses:
        exams = conn.execute("""
            SELECT d.*, c.code, c.name FROM deadlines d
            JOIN courses c ON c.id = d.course_id
            WHERE d.course_id = ?
            AND (LOWER(d.title) LIKE '%exam%'
            OR LOWER(d.title) LIKE '%midterm%'
            OR LOWER(d.title) LIKE '%final%')
            AND LOWER(d.title) NOT LIKE '%project%'
            AND LOWER(d.title) NOT LIKE '%proposal%'
            AND LOWER(d.title) NOT LIKE '%submission%'
            AND LOWER(d.title) NOT LIKE '%lab%'
            AND LOWER(d.title) NOT LIKE '%homework%'
            ORDER BY d.due_date
        """, (c["id"],)).fetchall()
        all_exams.extend([dict(e) for e in exams])
    conn.close()
    return render_template("exam_schedule.html",
                           user=session,
                           courses=courses,
                           current_course=courses[0] if courses else None,
                           exams=all_exams)
# ── ANNOUNCEMENTS ─────────────────────────────────────────────────────────────

@app.route("/course/<int:course_id>/announcements", methods=["GET", "POST"])
@login_required
def announcements(course_id):
    course = get_course(course_id)
    if not course:
        return redirect(url_for('dashboard'))
    if not can_access_course(course):
        return redirect(url_for('dashboard'))
    conn = get_conn()
    if request.method == "POST" and session["role"] == "instructor":
        title = request.form.get("title", "").strip()
        body  = request.form.get("body", "").strip()
        # Allow the instructor to pick which of their courses to post to.
        target_id = request.form.get("target_course_id", type=int) or course_id
        target_course = get_course(target_id)
        # Only post if the instructor actually owns the chosen course.
        if title and body and target_course and instructor_owns_course(target_id):
            conn.execute("INSERT INTO announcements(course_id,title,body) VALUES(?,?,?)",
                         (target_id, title, body))
            conn.commit()
            _create_notifications(
                target_id,
                f"📢 Yeni duyuru ({target_course['code']}): {title}",
                "announcement"
            )
            _log_event("announcement_post", course_id=target_id)
            conn.close()
            # Redirect to the chosen course's announcements page so the new
            # post is visible and a refresh doesn't re-submit the form.
            return redirect(url_for("announcements", course_id=target_id))
    rows = conn.execute("SELECT * FROM announcements WHERE course_id=? ORDER BY created_at DESC",
                        (course_id,)).fetchall()
    conn.close()
    return render_template("announcements.html",
                           user=session, courses=get_user_courses(),
                           course=course, announcements=[dict(r) for r in rows])

@app.route("/course/<int:course_id>/announcements/<int:ann_id>/delete", methods=["POST"])
@login_required
def delete_announcement(course_id, ann_id):
    if instructor_owns_course(course_id):
        conn = get_conn()
        conn.execute("DELETE FROM announcements WHERE id=? AND course_id=?", (ann_id, course_id))
        conn.commit()
        conn.close()
    return redirect(url_for("announcements", course_id=course_id))

# ── SEARCH ────────────────────────────────────────────────────────────────────

@app.route("/course/<int:course_id>/search")
@login_required
def search(course_id):
    course = get_course(course_id)
    if not course:
        return redirect(url_for('dashboard'))
    if not can_access_course(course):
        return redirect(url_for('dashboard'))
    q = request.args.get("q", "").strip().lower()
    results = []
    if q:
        conn = get_conn()
        sections = conn.execute("SELECT * FROM syllabus_sections WHERE course_id=?",
                                (course_id,)).fetchall()
        conn.close()
        results = [dict(s) for s in sections
                   if q in s["section_name"].lower() or q in s["content"].lower()]
    return render_template("search.html",
                           user=session, courses=get_user_courses(),
                           course=course, results=results, q=q)

# ── AI CHAT ───────────────────────────────────────────────────────────────────

@app.route("/ai")
@login_required
def ai_chat_page():
    session["chat_history"] = []
    user_courses = get_user_courses()
    return render_template("ai_chat.html",
                           user=session,
                           courses=user_courses,
                           current_course=user_courses[0] if user_courses else None)

@app.route("/ai/ask", methods=["POST"])
@login_required
def ai_ask():
    data     = request.get_json()
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"answer": "Please enter a question."})
    history = session.get("chat_history", [])
    
    # Kullanıcının bölümünü veritabanından çek
    conn = get_conn()
    user_row = conn.execute("SELECT department FROM users WHERE id=?", 
                            (session["user_id"],)).fetchone()
    conn.close()
    user_department = user_row["department"] if user_row else ""

    try:
        answer = ask_ai(
            session["user_id"],
            session["role"],
            user_department,
            question,
            history
        )
        history.append({"role": "user",      "content": question})
        history.append({"role": "assistant", "content": answer})
        session["chat_history"] = history
        session.modified = True
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"answer": f"Error: {str(e)}"})

# ── INSTRUCTOR: EDIT SYLLABUS ─────────────────────────────────────────────────

@app.route("/course/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
def edit_syllabus(course_id):
    if session["role"] != "instructor":
        return redirect(url_for("dashboard"))
    course = get_course(course_id)
    if not course:
        return redirect(url_for('dashboard'))
    if not can_access_course(course):
        return redirect(url_for('dashboard'))
    REQUIRED_SECTIONS = {
        "course overview", "prerequisites", "course learning outcomes",
        "course objectives", "grading policy", "weekly plan", "course policies"
    }

    conn = get_conn()
    if request.method == "POST":
        changed = False

        # 1. New section addition
        new_name = request.form.get("new_section_name", "").strip()
        new_content = request.form.get("new_section_content", "").strip()
        if new_name:
            conn.execute(
                "INSERT INTO syllabus_sections (course_id, section_name, content) VALUES (?,?,?)",
                (course_id, new_name, new_content)
            )
            changed = True

        # 2. Deletions — only allow non-required sections
        delete_ids = request.form.getlist("delete_section")
        for sid_str in delete_ids:
            try:
                sid = int(sid_str)
                old = conn.execute(
                    "SELECT section_name, content FROM syllabus_sections WHERE id=? AND course_id=?",
                    (sid, course_id)
                ).fetchone()
                if old and old["section_name"].lower().strip() not in REQUIRED_SECTIONS:
                    conn.execute(
                        """INSERT INTO syllabus_history(section_id, course_id, section_name, content, changed_by)
                           VALUES(?,?,?,?,?)""",
                        (sid, course_id, old["section_name"], old["content"] or "", session["user_id"])
                    )
                    conn.execute("DELETE FROM syllabus_sections WHERE id=? AND course_id=?", (sid, course_id))
                    changed = True
            except (ValueError, TypeError):
                pass

        # 3. Content updates
        for key, value in request.form.items():
            if key.startswith("section_"):
                try:
                    sec_id = int(key.split("_")[1])
                except ValueError:
                    continue
                if str(sec_id) in delete_ids:
                    continue
                old = conn.execute(
                    "SELECT section_name, content FROM syllabus_sections WHERE id=? AND course_id=?",
                    (sec_id, course_id)
                ).fetchone()
                if old and (old["content"] or "") != value:
                    conn.execute(
                        """INSERT INTO syllabus_history(section_id, course_id, section_name, content, changed_by)
                           VALUES(?,?,?,?,?)""",
                        (sec_id, course_id, old["section_name"], old["content"] or "", session["user_id"])
                    )
                    conn.execute("UPDATE syllabus_sections SET content=? WHERE id=? AND course_id=?",
                                 (value, sec_id, course_id))
                    changed = True

        conn.commit()
        if changed:
            _create_notifications(
                course_id,
                f"✏️ Syllabus güncellendi ({course['code']})",
                "syllabus_change"
            )
            _log_event("syllabus_edit", course_id=course_id)
        return redirect(url_for("edit_syllabus", course_id=course_id))
    sections = conn.execute("SELECT * FROM syllabus_sections WHERE course_id=?",
                            (course_id,)).fetchall()
    conn.close()
    return render_template("edit_syllabus.html",
                       user=session, courses=get_user_courses(),
                       current_course=get_course(course_id),   # ← bunu ekle
                       course=course, sections=[dict(s) for s in sections])
# ── INSTRUCTOR: COURSE POLICIES ───────────────────────────────────────────────

@app.route("/course/<int:course_id>/policies", methods=["GET", "POST"])
@login_required
def course_policies(course_id):
    course = get_course(course_id)
    if not course:
        return redirect(url_for('dashboard'))
    if not can_access_course(course):
        return redirect(url_for('dashboard'))
    conn = get_conn()
    if request.method == "POST" and session["role"] == "instructor":
        content = request.form.get("content", "").strip()
        sec = conn.execute("""SELECT * FROM syllabus_sections
                              WHERE course_id=? AND section_name='Course Policies'""",
                           (course_id,)).fetchone()
        if sec:
            conn.execute("UPDATE syllabus_sections SET content=? WHERE id=?",
                         (content, sec["id"]))
        else:
            conn.execute("""INSERT INTO syllabus_sections(course_id,section_name,content)
                            VALUES(?,?,?)""", (course_id, "Course Policies", content))
        conn.commit()
        flash("✅ Course Policies kaydedildi.", "success")
        conn.close()
        return redirect(url_for("course_policies", course_id=course_id))
    sec = conn.execute("""SELECT * FROM syllabus_sections
                          WHERE course_id=? AND section_name='Course Policies'""",
                       (course_id,)).fetchone()
    conn.close()
    return render_template("policies.html",
                           user=session, courses=get_user_courses(),
                           current_course=course,
                           course=course, policy=dict(sec) if sec else None)

@app.route("/all-policies")
@login_required
def all_policies():
    courses = get_user_courses()
    conn = get_conn()
    all_course_policies = []
    for c in courses:
        sec = conn.execute("""SELECT content FROM syllabus_sections
                              WHERE course_id=? AND section_name='Course Policies'""",
                           (c["id"],)).fetchone()
        all_course_policies.append({
            "code": c["code"],
            "name": c["name"],
            "content": sec["content"] if sec else "No policies defined yet."
        })
    conn.close()
    return render_template("all_policies.html",
                           user=session,
                           courses=courses,
                           current_course=courses[0] if courses else None,
                           all_course_policies=all_course_policies)
# ── NEW COURSE (instructor) ───────────────────────────────────────────────────

@app.route("/course/new", methods=["GET", "POST"])
@login_required
def new_course():
    if session["role"] != "instructor":
        return redirect(url_for("dashboard"))
    import re as _re
    errors = []
    form_data = {}
    if request.method == "POST":
        code  = request.form.get("code", "").strip().upper()
        name  = request.form.get("name", "").strip()
        cred  = request.form.get("credit", "3").strip()
        cls   = request.form.get("classroom", "").strip().upper()
        sched = request.form.get("schedule", "").strip()
        email = request.form.get("email", "").strip().lower()
        dept  = request.form.get("department", "").strip()
        form_data = {"code": code, "name": name, "credit": cred,
                     "classroom": cls, "schedule": sched, "email": email, "department": dept}

        if not code:
            errors.append("Ders kodu zorunludur.")
        if not name:
            errors.append("Ders adı zorunludur.")
        if email and not _re.match(r'^[\w\.\-\+]+@[\w\-]+\.[a-z]{2,}(\.[a-z]{2,})?$', email):
            errors.append("Geçersiz e-posta adresi. Örn: ders@bau.edu.tr")
        if cls and not _re.match(r'^[A-Z]{1,4}\d{2,4}[A-Z]?$', cls):
            errors.append("Geçersiz derslik formatı. Örn: A105, DSC02, B201")

        if not errors:
            conn = get_conn()
            try:
                conn.execute(
                    """INSERT INTO courses(code,name,instructor_id,credit,classroom,schedule,email,department)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (code, name, session["user_id"], int(cred) if cred.isdigit() else 3,
                     cls, sched, email, dept))
                conn.commit()
            except Exception:
                pass
            conn.close()
            return redirect(url_for("dashboard"))

    return render_template("new_course.html", user=session, courses=get_user_courses(),
                           current_course=None, errors=errors, form_data=form_data)


# ── GLOBAL SEARCH (across all accessible courses) ─────────────────────────────

def _snippet(text, q, length=160):
    """Return a short excerpt of text centered on the first match of q."""
    if not text:
        return ""
    low = text.lower()
    pos = low.find(q)
    if pos == -1:
        return (text[:length] + "…") if len(text) > length else text
    start = max(0, pos - 40)
    end = min(len(text), pos + length - 40)
    snip = text[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snip}{suffix}"

@app.route("/search/global")
@login_required
def global_search():
    q = request.args.get("q", "").strip()
    user_courses = get_user_courses()  # for sidebar
    groups = []

    if q:
        ql = q.lower()
        conn = get_conn()
        # Search ALL courses in the database regardless of enrollment
        all_courses = conn.execute("SELECT * FROM courses").fetchall()
        for c in all_courses:
            items = []

            if ql in c["code"].lower() or ql in c["name"].lower() or ql in (c["department"] or "").lower():
                items.append({
                    "tag": "Course",
                    "title": f"{c['code']} — {c['name']}",
                    "snippet": c["department"] or "",
                    "url": url_for("syllabus", course_id=c["id"]),
                })

            for s in conn.execute(
                "SELECT section_name, content FROM syllabus_sections WHERE course_id=?",
                (c["id"],)
            ).fetchall():
                if ql in s["section_name"].lower() or ql in (s["content"] or "").lower():
                    items.append({
                        "tag": "Syllabus",
                        "title": s["section_name"],
                        "snippet": _snippet(s["content"] or "", ql),
                        "url": url_for("syllabus", course_id=c["id"]),
                    })

            for d in conn.execute(
                "SELECT title, due_date FROM deadlines WHERE course_id=?", (c["id"],)
            ).fetchall():
                if ql in d["title"].lower():
                    items.append({
                        "tag": "Deadline",
                        "title": d["title"],
                        "snippet": f"Due: {d['due_date']}",
                        "url": url_for("deadlines", course_id=c["id"]),
                    })

            for a in conn.execute(
                "SELECT title, body FROM announcements WHERE course_id=?", (c["id"],)
            ).fetchall():
                if ql in a["title"].lower() or ql in (a["body"] or "").lower():
                    items.append({
                        "tag": "Announcement",
                        "title": a["title"],
                        "snippet": _snippet(a["body"] or "", ql),
                        "url": url_for("announcements", course_id=c["id"]),
                    })

            if items:
                groups.append({"course": c, "results": items})
        conn.close()

    total = sum(len(g["results"]) for g in groups)
    return render_template("global_search.html",
                           user=session, courses=user_courses,
                           current_course=user_courses[0] if user_courses else None,
                           q=q, groups=groups, total=total)

# ── EXPORTS: CALENDAR (.ics) ───────────────────────────────────────────────────

def _ics_escape(text):
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

def _build_ics(deadlines, cal_name="BAU Deadlines"):
    """Build an iCalendar string from a list of deadlines (all-day events)."""
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BAU Syllabus System//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_ics_escape(cal_name)}",
    ]
    for i, d in enumerate(deadlines):
        try:
            due = datetime.strptime(d["due_date"].strip(), "%Y-%m-%d").date()
        except (ValueError, AttributeError):
            continue
        start = due.strftime("%Y%m%d")
        end = (due + timedelta(days=1)).strftime("%Y%m%d")
        summary = f"{d.get('course_code','')} – {d['title']}".strip(" –")
        lines += [
            "BEGIN:VEVENT",
            f"UID:bau-{d.get('course_code','x')}-{i}-{start}@bau.local",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{start}",
            f"DTEND;VALUE=DATE:{end}",
            f"SUMMARY:{_ics_escape(summary)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"

def _ics_response(ics_text, filename):
    return Response(ics_text, mimetype="text/calendar",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.route("/course/<int:course_id>/deadlines.ics")
@login_required
def course_ics(course_id):
    course = get_course(course_id)
    if not course:
        abort(404)
    if not can_access_course(course):
        abort(403)
    conn = get_conn()
    rows = conn.execute("SELECT title, due_date FROM deadlines WHERE course_id=?",
                        (course_id,)).fetchall()
    conn.close()
    deadlines = [{"title": r["title"], "due_date": r["due_date"],
                  "course_code": course["code"]} for r in rows]
    ics = _build_ics(deadlines, cal_name=f"{course['code']} Deadlines")
    return _ics_response(ics, f"{course['code']}_deadlines.ics")

@app.route("/calendar.ics")
@login_required
def all_ics():
    courses = get_user_courses()
    conn = get_conn()
    deadlines = []
    for c in courses:
        for r in conn.execute("SELECT title, due_date FROM deadlines WHERE course_id=?",
                              (c["id"],)).fetchall():
            deadlines.append({"title": r["title"], "due_date": r["due_date"],
                              "course_code": c["code"]})
    conn.close()
    ics = _build_ics(deadlines, cal_name="BAU – All My Deadlines")
    return _ics_response(ics, "bau_all_deadlines.ics")

# ── EXPORTS: PRINT / PDF SYLLABUS ──────────────────────────────────────────────

@app.route("/course/<int:course_id>/syllabus/print")
@login_required
def syllabus_print(course_id):
    course = get_course(course_id)
    if not course:
        abort(404)
    if not can_access_course(course):
        abort(403)
    conn = get_conn()
    instructor = conn.execute("SELECT username, full_name, title FROM users WHERE id=?",
                              (course["instructor_id"],)).fetchone()
    sections = conn.execute("SELECT * FROM syllabus_sections WHERE course_id=?",
                            (course_id,)).fetchall()
    deadlines = conn.execute("SELECT title, due_date FROM deadlines WHERE course_id=? ORDER BY due_date",
                             (course_id,)).fetchall()
    conn.close()
    return render_template("print_syllabus.html",
                           course=course,
                           instructor=instructor["full_name"] or instructor["username"] if instructor else "",
                           sections=[dict(s) for s in sections],
                           deadlines=[dict(d) for d in deadlines],
                           generated=date.today().isoformat())

# ── COURSE AT A GLANCE (overview + timeline) ───────────────────────────────────

def _build_overview(courses):
    today = date.today()
    conn = get_conn()
    overview = []
    for c in courses:
        instructor = conn.execute("SELECT username, full_name, title FROM users WHERE id=?",
                                  (c["instructor_id"],)).fetchone()
        n_sections = conn.execute("SELECT COUNT(*) AS n FROM syllabus_sections WHERE course_id=?",
                                  (c["id"],)).fetchone()["n"]
        rows = conn.execute("SELECT title, due_date FROM deadlines WHERE course_id=?",
                            (c["id"],)).fetchall()
        parsed = []
        for r in rows:
            try:
                due = datetime.strptime(r["due_date"].strip(), "%Y-%m-%d").date()
            except (ValueError, AttributeError):
                continue
            t = r["title"].lower()
            kind = "exam" if ("exam" in t or "midterm" in t or "final" in t) else "task"
            parsed.append({"title": r["title"], "due_date": r["due_date"],
                           "date": due, "kind": kind, "days": (due - today).days})
        parsed.sort(key=lambda x: x["date"])

        points = []
        start = end = None
        if parsed:
            start = parsed[0]["date"]
            end = parsed[-1]["date"]
            span = (end - start).days or 1
            for p in parsed:
                pct = 50.0 if end == start else round((p["date"] - start).days / span * 100, 1)
                points.append({**p, "pct": pct})

        upcoming = [p for p in parsed if p["days"] >= 0]
        overview.append({
            "course": c,
            "instructor": instructor["full_name"] or instructor["username"] if instructor else "",
            "n_sections": n_sections,
            "n_deadlines": len(parsed),
            "next": upcoming[0] if upcoming else None,
            "timeline": {
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "points": points,
            },
        })
    conn.close()
    return overview

@app.route("/overview")
@login_required
def overview():
    courses = get_user_courses()
    return render_template("overview.html",
                           user=session, courses=courses,
                           current_course=courses[0] if courses else None,
                           overview=_build_overview(courses))

# ── MONTH CALENDAR VIEW ────────────────────────────────────────────────────────

def _all_deadline_dates(courses):
    conn = get_conn()
    out = []
    for c in courses:
        for r in conn.execute("SELECT title, due_date FROM deadlines WHERE course_id=?",
                              (c["id"],)).fetchall():
            try:
                d = datetime.strptime(r["due_date"].strip(), "%Y-%m-%d").date()
            except (ValueError, AttributeError):
                continue
            t = r["title"].lower()
            kind = "exam" if ("exam" in t or "midterm" in t or "final" in t) else "task"
            out.append({"date": d, "title": r["title"], "code": c["code"], "kind": kind})
    conn.close()
    return out

@app.route("/calendar")
@login_required
def calendar_view():
    courses = get_user_courses()
    items = _all_deadline_dates(courses)
    today = date.today()

    # Default to the month nearest to today that actually has data (nicer demo),
    # else the current month.
    if "y" in request.args and "m" in request.args:
        try:
            year = int(request.args["y"]); month = int(request.args["m"])
        except ValueError:
            year, month = today.year, today.month
    elif items:
        nearest = min(items, key=lambda x: abs((x["date"] - today).days))["date"]
        year, month = nearest.year, nearest.month
    else:
        year, month = today.year, today.month

    if not (1 <= month <= 12):
        year, month = today.year, today.month

    # bucket events by day-of-month
    by_day = {}
    for it in items:
        if it["date"].year == year and it["date"].month == month:
            by_day.setdefault(it["date"].day, []).append(it)

    weeks = []
    for week in _calmod.monthcalendar(year, month):
        cells = []
        for day in week:
            cells.append({
                "day": day,
                "events": by_day.get(day, []) if day else [],
                "is_today": (day == today.day and month == today.month and year == today.year),
            })
        weeks.append(cells)

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)

    return render_template("calendar.html",
                           user=session, courses=courses,
                           current_course=courses[0] if courses else None,
                           weeks=weeks,
                           month_name=_calmod.month_name[month], year=year, month=month,
                           prev_y=prev_y, prev_m=prev_m, next_y=next_y, next_m=next_m,
                           weekday_names=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

# ── PROGRESS TRACKING (students check off deadlines) ───────────────────────────

@app.route("/course/<int:course_id>/deadlines/<int:dl_id>/toggle", methods=["POST"])
@login_required
def toggle_deadline(course_id, dl_id):
    if session.get("role") == "student" and can_access_course(get_course(course_id)):
        conn = get_conn()
        belongs = conn.execute(
            "SELECT 1 FROM deadlines WHERE id=? AND course_id=?", (dl_id, course_id)
        ).fetchone()
        if belongs:
            row = conn.execute(
                "SELECT done FROM deadline_progress WHERE student_id=? AND deadline_id=?",
                (session["user_id"], dl_id)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO deadline_progress(student_id, deadline_id, done) VALUES(?,?,1)",
                    (session["user_id"], dl_id)
                )
            else:
                conn.execute(
                    "UPDATE deadline_progress SET done=? WHERE student_id=? AND deadline_id=?",
                    (0 if row["done"] else 1, session["user_id"], dl_id)
                )
            conn.commit()
        conn.close()
    return redirect(url_for("deadlines", course_id=course_id))

# ── BİLDİRİMLER ───────────────────────────────────────────────────────────────

@app.route("/notifications")
@login_required
def notifications():
    _log_event("page_view", page="notifications")
    conn = get_conn()
    rows = conn.execute(
        """SELECT n.*, c.code, c.name FROM notifications n
           JOIN courses c ON c.id = n.course_id
           WHERE n.user_id=? ORDER BY n.created_at DESC""",
        (session["user_id"],)
    ).fetchall()
    conn.close()
    courses = get_user_courses()
    return render_template("notifications.html",
                           user=session, courses=courses,
                           current_course=courses[0] if courses else None,
                           notifications=[dict(r) for r in rows])

@app.route("/notifications/<int:nid>/read", methods=["POST"])
@login_required
def mark_notification_read(nid):
    conn = get_conn()
    conn.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
                 (nid, session["user_id"]))
    conn.commit()
    conn.close()
    return redirect(url_for("notifications"))

@app.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    conn = get_conn()
    conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    conn.commit()
    conn.close()
    return redirect(url_for("notifications"))

# ── SİLABUS GEÇMİŞİ (sürüm kontrol) ──────────────────────────────────────────

@app.route("/course/<int:course_id>/syllabus/history")
@login_required
def syllabus_history(course_id):
    if not instructor_owns_course(course_id):
        return redirect(url_for("dashboard"))
    course = get_course(course_id)
    conn = get_conn()
    rows = conn.execute(
        """SELECT h.*, u.username FROM syllabus_history h
           JOIN users u ON u.id = h.changed_by
           WHERE h.course_id=? ORDER BY h.changed_at DESC""",
        (course_id,)
    ).fetchall()
    conn.close()
    _log_event("page_view", page="syllabus_history", course_id=course_id)
    return render_template("syllabus_history.html",
                           user=session, courses=get_user_courses(),
                           current_course=course, course=course,
                           history=[dict(r) for r in rows])

@app.route("/course/<int:course_id>/syllabus/section/<int:sec_id>/restore", methods=["POST"])
@login_required
def restore_section(course_id, sec_id):
    if not instructor_owns_course(course_id):
        return redirect(url_for("dashboard"))
    hist_id = request.form.get("hist_id", type=int)
    if not hist_id:
        return redirect(url_for("syllabus_history", course_id=course_id))
    conn = get_conn()
    h = conn.execute("SELECT * FROM syllabus_history WHERE id=? AND course_id=?",
                     (hist_id, course_id)).fetchone()
    if h:
        existing = conn.execute(
            "SELECT id FROM syllabus_sections WHERE id=? AND course_id=?",
            (sec_id, course_id)
        ).fetchone()
        if existing:
            # Section still exists — update content
            conn.execute("UPDATE syllabus_sections SET content=? WHERE id=? AND course_id=?",
                         (h["content"], sec_id, course_id))
        else:
            # Section was deleted — re-insert with original name
            conn.execute(
                "INSERT INTO syllabus_sections (course_id, section_name, content) VALUES (?,?,?)",
                (course_id, h["section_name"], h["content"])
            )
        # Save the restore action itself to history
        conn.execute(
            """INSERT INTO syllabus_history(section_id, course_id, section_name, content, changed_by)
               VALUES(?,?,?,?,?)""",
            (sec_id, course_id, h["section_name"], h["content"], session["user_id"])
        )
        conn.commit()
        flash(f"✅ '{h['section_name']}' bölümü geri yüklendi.", "success")
    conn.close()
    return redirect(url_for("syllabus_history", course_id=course_id))

# ── ÖĞRENCİ GERİ BİLDİRİMİ ───────────────────────────────────────────────────

@app.route("/course/<int:course_id>/feedback", methods=["GET", "POST"])
@login_required
def course_feedback(course_id):
    course = get_course(course_id)
    if not course or not can_access_course(course):
        return redirect(url_for("dashboard"))
    conn = get_conn()
    if request.method == "POST" and session["role"] == "student":
        content = request.form.get("content", "").strip()
        rating  = request.form.get("rating", "0").strip()
        if content:
            try:
                r = max(1, min(5, int(rating)))
            except ValueError:
                r = 0
            conn.execute(
                "INSERT INTO feedback(course_id,student_id,content,rating) VALUES(?,?,?,?)",
                (course_id, session["user_id"], content, r if r else None)
            )
            conn.commit()
            _log_event("feedback_submit", course_id=course_id)
    if session["role"] == "instructor":
        rows = conn.execute(
            """SELECT f.*, u.username FROM feedback f
               JOIN users u ON u.id = f.student_id
               WHERE f.course_id=? ORDER BY f.created_at DESC""",
            (course_id,)
        ).fetchall()
        avg = conn.execute(
            "SELECT AVG(rating) as avg_rating, COUNT(*) as total FROM feedback WHERE course_id=? AND rating IS NOT NULL",
            (course_id,)
        ).fetchone()
        avg_rating = round(avg["avg_rating"], 1) if avg["avg_rating"] else None
        total_rated = avg["total"]
    else:
        rows = conn.execute(
            "SELECT * FROM feedback WHERE course_id=? AND is_approved=1 ORDER BY created_at DESC",
            (course_id,)
        ).fetchall()
        avg_rating = None
        total_rated = 0
    conn.close()
    _log_event("page_view", page="feedback", course_id=course_id)
    return render_template("feedback.html",
                           user=session, courses=get_user_courses(),
                           current_course=course, course=course,
                           feedbacks=[dict(r) for r in rows],
                           avg_rating=avg_rating, total_rated=total_rated)

# ── ANALİTİK DASHBOARD (instructor) ───────────────────────────────────────────

@app.route("/analytics")
@login_required
def analytics_dashboard():
    if session["role"] != "instructor":
        return redirect(url_for("dashboard"))
    courses = get_user_courses()
    course_ids = [c["id"] for c in courses]
    conn = get_conn()
    events = []
    if course_ids:
        placeholders = ",".join("?" * len(course_ids))
        events = conn.execute(
            f"""SELECT event_type, COUNT(*) as cnt, course_id
                FROM analytics_events
                WHERE course_id IN ({placeholders})
                GROUP BY event_type, course_id
                ORDER BY cnt DESC""",
            course_ids
        ).fetchall()
    page_views = conn.execute(
        """SELECT page, COUNT(*) as cnt FROM analytics_events
           WHERE user_id=? GROUP BY page ORDER BY cnt DESC""",
        (session["user_id"],)
    ).fetchall()
    recent = conn.execute(
        """SELECT a.event_type, a.page, a.course_id, a.created_at, u.username
           FROM analytics_events a
           JOIN users u ON u.id = a.user_id
           WHERE a.course_id IN ({})
           ORDER BY a.created_at DESC LIMIT 50""".format(
               ",".join("?" * len(course_ids)) if course_ids else "NULL"
           ),
        course_ids
    ).fetchall() if course_ids else []
    conn.close()
    _log_event("page_view", page="analytics")
    return render_template("analytics.html",
                           user=session, courses=courses,
                           current_course=courses[0] if courses else None,
                           events=[dict(e) for e in events],
                           page_views=[dict(p) for p in page_views],
                           recent=[dict(r) for r in recent])

@app.route("/analytics/event", methods=["POST"])
@login_required
def log_event_api():
    # sendBeacon sends text/plain; get_json fails → fall back to raw parse
    if request.is_json:
        data = request.get_json() or {}
    else:
        try:
            data = json.loads(request.get_data(as_text=True)) or {}
        except Exception:
            data = {}
    _log_event(
        data.get("event_type", "custom"),
        page=data.get("page"),
        course_id=data.get("course_id"),
        extra=data.get("extra")
    )
    return jsonify({"ok": True})

# ── SYLLABUS DOSYASINDAN AI İLE ÇIKARMA ────────────────────────────────────────

def _extract_text_from_upload(file_storage):
    """Read raw text from an uploaded PDF, Word (.docx) or .txt file.
    Returns (text, error). Keeps dependencies optional so a missing library
    yields a clear message instead of a crash."""
    filename = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if filename.endswith(".txt"):
        try:
            return raw.decode("utf-8", errors="ignore"), None
        except Exception as e:
            return "", f"Metin dosyası okunamadı: {e}"
    if filename.endswith(".pdf"):
        try:
            import pdfplumber, io
            text = []
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for page in pdf.pages:
                    text.append(page.extract_text() or "")
            return "\n".join(text), None
        except ImportError:
            return "", "PDF okuma kütüphanesi (pdfplumber) kurulu değil."
        except Exception as e:
            return "", f"PDF okunamadı: {e}"
    if filename.endswith(".docx"):
        try:
            import docx, io
            doc = docx.Document(io.BytesIO(raw))
            return "\n".join(p.text for p in doc.paragraphs), None
        except ImportError:
            return "", "Word okuma kütüphanesi (python-docx) kurulu değil."
        except Exception as e:
            return "", f"Word dosyası okunamadı: {e}"
    return "", "Desteklenmeyen dosya türü. PDF, Word (.docx) veya .txt yükleyin."

@app.route("/course/<int:course_id>/syllabus/extract", methods=["POST"])
@login_required
def syllabus_extract(course_id):
    """Instructor uploads a syllabus file; AI extracts sections + deadlines and
    returns them as a preview (no DB writes here — the instructor confirms)."""
    if session["role"] != "instructor":
        return jsonify({"error": "Yetkisiz"}), 403
    if not instructor_owns_course(course_id):
        return jsonify({"error": "Bu derse erişiminiz yok"}), 403

    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Dosya seçilmedi"}), 400

    text, err = _extract_text_from_upload(f)
    if err:
        return jsonify({"error": err}), 400
    text = (text or "").strip()
    if not text:
        return jsonify({"error": "Dosyadan metin çıkarılamadı. Dosya boş veya taranmış görüntü olabilir."}), 400

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return jsonify({"error": "AI servisi yapılandırılmamış"}), 503

    # Cap the text size sent to the model to stay within token limits.
    text = text[:12000]
    today = date.today().isoformat()
    prompt = f"""You are parsing a university course syllabus. Today is {today}.
From the syllabus text below, extract:
1. "sections": the standard syllabus sections you can identify. Use these canonical
   section names where they apply: "Course Overview", "Prerequisites",
   "Course Objectives", "Course Learning Outcomes", "Grading Policy",
   "Weekly Plan", "Course Policies". Only include a section if the text actually
   contains relevant content. Put the section's content as clean plain text.
2. "deadlines": any dated assessments (exams, assignments, projects, quizzes).
   Each has "title" and "date" in YYYY-MM-DD. If the year is missing assume the
   current academic year. Omit items without an identifiable date.

Respond with ONLY valid JSON, no markdown:
{{"sections":[{{"name":"...","content":"..."}}],"deadlines":[{{"title":"...","date":"YYYY-MM-DD"}}]}}

Syllabus text:
{text}"""

    import urllib.request, ssl
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.1}
    }).encode()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=40, context=ctx) as resp:
            raw = json.loads(resp.read().decode())
        out = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
        if "```" in out:
            for part in out.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    out = part
                    break
        parsed = json.loads(out)
        _log_event("syllabus_extract", course_id=course_id)
        return jsonify({
            "ok": True,
            "sections": parsed.get("sections", []),
            "deadlines": parsed.get("deadlines", []),
        })
    except Exception as e:
        return jsonify({"error": f"AI içeriği işlenemedi: {e}"}), 500

@app.route("/course/<int:course_id>/syllabus/apply-extracted", methods=["POST"])
@login_required
def syllabus_apply_extracted(course_id):
    """Persist the sections + deadlines the instructor approved from the preview."""
    if session["role"] != "instructor":
        return jsonify({"error": "Yetkisiz"}), 403
    if not instructor_owns_course(course_id):
        return jsonify({"error": "Bu derse erişiminiz yok"}), 403
    data = request.get_json() or {}
    sections = data.get("sections", [])
    deadlines = data.get("deadlines", [])
    course = get_course(course_id)

    conn = get_conn()
    applied_sections = 0
    for s in sections:
        name = (s.get("name") or "").strip()
        content = (s.get("content") or "").strip()
        if not name:
            continue
        existing = conn.execute(
            "SELECT id, content FROM syllabus_sections WHERE course_id=? AND lower(section_name)=lower(?)",
            (course_id, name)
        ).fetchone()
        if existing:
            # archive old content, then overwrite
            conn.execute(
                """INSERT INTO syllabus_history(section_id, course_id, section_name, content, changed_by)
                   VALUES(?,?,?,?,?)""",
                (existing["id"], course_id, name, existing["content"] or "", session["user_id"])
            )
            conn.execute("UPDATE syllabus_sections SET content=? WHERE id=?",
                         (content, existing["id"]))
        else:
            conn.execute(
                "INSERT INTO syllabus_sections (course_id, section_name, content) VALUES (?,?,?)",
                (course_id, name, content)
            )
        applied_sections += 1

    applied_deadlines = 0
    for d in deadlines:
        title = (d.get("title") or "").strip()
        due = (d.get("date") or "").strip()
        if not title or not due:
            continue
        dup = conn.execute(
            "SELECT 1 FROM deadlines WHERE course_id=? AND title=? AND due_date=?",
            (course_id, title, due)
        ).fetchone()
        if not dup:
            conn.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                         (course_id, title, due))
            applied_deadlines += 1
    conn.commit()
    conn.close()

    if applied_sections or applied_deadlines:
        _create_notifications(
            course_id,
            f"✏️ Syllabus güncellendi ({course['code']})" if course else "Syllabus güncellendi",
            "syllabus_change"
        )
        _log_event("syllabus_apply_extracted", course_id=course_id,
                   extra={"sections": applied_sections, "deadlines": applied_deadlines})
    return jsonify({"ok": True, "sections": applied_sections, "deadlines": applied_deadlines})

# ── AI: SEMANTİK ARAMA ────────────────────────────────────────────────────────

@app.route("/ai/semantic-search", methods=["POST"])
@login_required
def ai_semantic_search():
    data = request.get_json() or {}
    query = data.get("q", "").strip()
    if not query:
        return jsonify({"error": "Boş sorgu"})

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return jsonify({"error": "AI servisi yapılandırılmamış"})

    conn = get_conn()
    all_sections = []
    # Search ALL courses in the database
    for c in conn.execute("SELECT * FROM courses").fetchall():
        for s in conn.execute("SELECT section_name, content FROM syllabus_sections WHERE course_id=?",
                              (c["id"],)).fetchall():
            all_sections.append({
                "course_code": c["code"],
                "course_name": c["name"],
                "course_id": c["id"],
                "section": s["section_name"],
                "content": (s["content"] or "")[:400]
            })
    conn.close()

    if not all_sections:
        return jsonify({"error": "Aranacak syllabus içeriği bulunamadı."})

    # Build a lookup so we can enrich AI results with course_id after parsing
    section_lookup = {}
    for s in all_sections:
        key = (s["course_code"].upper(), s["section"].lower())
        section_lookup[key] = {"course_id": s["course_id"], "course_name": s["course_name"]}

    sections_text = "\n".join(
        f"[{s['course_code']} | {s['section']}]: {s['content']}" for s in all_sections
    )
    prompt = f"""You are a semantic search engine for a university syllabus system.
User query: "{query}"

Available syllabus content (format: [COURSE_CODE | Section Name]: excerpt):
{sections_text}

Instructions:
1. Return the 1-5 most semantically relevant sections for the user's query.
   - Use semantic understanding, not just keyword matching.
   - The query may be in Turkish or English; match across both.
2. For each match, write a one-sentence reason in the same language as the query.
3. Suggest 3 alternative search keywords in the same language as the query.

You MUST respond with ONLY valid JSON. No markdown, no explanation outside JSON.
Format:
{{"results":[{{"course_code":"EXACT_CODE","section":"EXACT_SECTION_NAME","reason":"..."}}],"keywords":["...","...","..."]}}"""

    import urllib.request, ssl
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 800, "temperature": 0.1}
    }).encode()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            raw = json.loads(resp.read().decode())
        text = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Strip markdown code fences if present
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    text = part
                    break
        parsed = json.loads(text)

        # Enrich each result with course_id and course_name via lookup
        enriched = []
        for r in parsed.get("results", []):
            code = (r.get("course_code") or "").strip().upper()
            section = (r.get("section") or "").strip().lower()
            info = section_lookup.get((code, section), {})
            # Fallback: match by course_code only if section not found
            if not info:
                for (c_code, c_sec), c_info in section_lookup.items():
                    if c_code == code:
                        info = c_info
                        break
            enriched.append({
                "course_code": r.get("course_code", ""),
                "course_name": info.get("course_name", ""),
                "course_id": info.get("course_id"),
                "section": r.get("section", ""),
                "reason": r.get("reason", ""),
            })

        _log_event("semantic_search", extra={"q": query})
        return jsonify({"ok": True, "data": {"results": enriched, "keywords": parsed.get("keywords", [])}})
    except Exception as e:
        return jsonify({"error": str(e)})

# ── AI: SECTION FORMATLAMA ────────────────────────────────────────────────────

@app.route("/ai/format-section", methods=["POST"])
@login_required
def ai_format_section():
    if session["role"] != "instructor":
        return jsonify({"error": "Yetkisiz"})
    data = request.get_json() or {}
    section_name = data.get("section_name", "")
    content      = data.get("content", "").strip()
    if not content:
        return jsonify({"error": "İçerik boş"})
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return jsonify({"error": "AI servisi yapılandırılmamış"})

    prompt = f"""You are a university syllabus formatting assistant.
Reformat the following content for the section "{section_name}" to be clear, well-structured, and professional for university students.
Keep all information; only improve formatting, clarity, and structure.
Use numbered lists, bullet points, or clear headings where appropriate.
Return only the reformatted content, no explanation.

Content:
{content}"""

    import urllib.request, ssl
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                          "generationConfig": {"maxOutputTokens": 800, "temperature": 0.3}}).encode()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            raw = json.loads(resp.read().decode())
        formatted = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
        _log_event("ai_format_section")
        return jsonify({"ok": True, "formatted": formatted})
    except Exception as e:
        return jsonify({"error": str(e)})

# ── AI: EKSİK SYLLABUS BİLEŞENİ TESPİTİ ──────────────────────────────────────

@app.route("/course/<int:course_id>/ai/check-syllabus")
@login_required
def ai_check_syllabus(course_id):
    if not instructor_owns_course(course_id):
        return jsonify({"error": "Yetkisiz"})

    conn = get_conn()
    sections = conn.execute(
        "SELECT section_name, content FROM syllabus_sections WHERE course_id=?", (course_id,)
    ).fetchall()
    conn.close()

    # Weak sections: content < 30 chars (simple local check)
    weak = [s["section_name"] for s in sections
            if not s["content"] or len((s["content"] or "").strip()) < 30]

    # Missing: use Gemini to decide what a university syllabus should have
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        # Fallback: simple local check without AI
        REQUIRED = ["Course Overview", "Course Objectives", "Course Learning Outcomes",
                    "Prerequisites", "Grading Policy", "Weekly Plan", "Course Policies"]
        existing_names = [s["section_name"] for s in sections]
        missing = [r for r in REQUIRED
                   if not any(r.lower() in e.lower() or e.lower() in r.lower()
                              for e in existing_names)]
        _log_event("ai_check_syllabus", course_id=course_id)
        return jsonify({"ok": True, "missing": missing, "weak": weak})

    section_list = "\n".join(
        f"- {s['section_name']}: {(s['content'] or '').strip()[:120]}" for s in sections
    )
    prompt = f"""You are a university syllabus quality checker.
The following sections currently exist in a course syllabus:
{section_list if section_list else "(no sections yet)"}

Task: Identify which STANDARD university syllabus components are TRULY MISSING from the above list.
Standard components to check: Course Overview/Description, Learning Outcomes/Objectives, Prerequisites,
Grading/Assessment Policy, Weekly Schedule/Plan, Course/Academic Policies.

Rules:
- Only flag a component as missing if there is NO section that covers it (even partially or under a different name).
- If a component exists under a slightly different name (e.g. "Course Objectives" covers "Learning Objectives"), do NOT flag it as missing.
- Return at most 4 missing items.
- If nothing important is missing, return an empty list.

Respond ONLY with valid JSON, no markdown:
{{"missing": ["component name", ...]}}\n"""

    import urllib.request, ssl
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 300, "temperature": 0.1}
    }).encode()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            raw = json.loads(resp.read().decode())
        text = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
        if "```" in text:
            for part in text.split("```"):
                part = part.strip().lstrip("json").strip()
                if part.startswith("{"):
                    text = part
                    break
        parsed = json.loads(text)
        missing = parsed.get("missing", [])
    except Exception:
        missing = []

    _log_event("ai_check_syllabus", course_id=course_id)
    return jsonify({"ok": True, "missing": missing, "weak": weak})

# ── AI: DEADLINE ÇIKARIMI ─────────────────────────────────────────────────────

@app.route("/ai/extract-deadlines", methods=["POST"])
@login_required
def ai_extract_deadlines():
    if session["role"] != "instructor":
        return jsonify({"error": "Yetkisiz"})
    data = request.get_json() or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Metin boş"})
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return jsonify({"error": "AI servisi yapılandırılmamış"})

    today = date.today().isoformat()
    prompt = f"""Extract all dates, deadlines, exams, and assignments from the following text.
Today's date is {today}.
Return a JSON array of objects with fields: "title" (event name) and "date" (YYYY-MM-DD format).
If year is missing, assume current year. Only include items with identifiable dates.
Return only the JSON array, nothing else.

Text:
{text}"""

    import urllib.request, ssl
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                          "generationConfig": {"maxOutputTokens": 512, "temperature": 0.1}}).encode()
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            raw = json.loads(resp.read().decode())
        text_out = raw["candidates"][0]["content"]["parts"][0]["text"].strip()
        if text_out.startswith("```"):
            text_out = text_out.split("```")[1]
            if text_out.startswith("json"):
                text_out = text_out[4:]
        deadlines = json.loads(text_out)
        _log_event("ai_extract_deadlines")
        return jsonify({"ok": True, "deadlines": deadlines})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)