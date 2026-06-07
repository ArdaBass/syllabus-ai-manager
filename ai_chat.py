import os
from db import get_conn

def get_all_accessible_data(user_id, user_role, user_department):
    """Kullanıcının erişebildiği tüm derslerin verisini çeker."""
    conn = get_conn()

    if user_role == "student":
        # Sadece kayıtlı dersler — bölüm geneli erişim yok
        courses = conn.execute("""
            SELECT c.* FROM courses c
            JOIN enrollments e ON e.course_id = c.id
            WHERE e.student_id = ?
        """, (user_id,)).fetchall()
    else:
        # Instructor sadece kendi derslerini görür
        courses = conn.execute("""
            SELECT * FROM courses WHERE instructor_id = ?
        """, (user_id,)).fetchall()

    all_data = []
    for course in courses:
        cid = course["id"]
        sections = conn.execute(
            "SELECT section_name, content FROM syllabus_sections WHERE course_id=?", (cid,)
        ).fetchall()
        deadlines = conn.execute(
            "SELECT title, due_date FROM deadlines WHERE course_id=?", (cid,)
        ).fetchall()
        announcements = conn.execute(
            "SELECT title, body FROM announcements WHERE course_id=? ORDER BY created_at DESC LIMIT 3",
            (cid,)
        ).fetchall()

        all_data.append({
            "course": dict(course),
            "sections": [dict(s) for s in sections],
            "deadlines": [dict(d) for d in deadlines],
            "announcements": [dict(a) for a in announcements],
        })

    conn.close()
    return all_data

def build_context(all_data):
    """Tüm ders verilerini AI'a verilecek context metnine dönüştürür."""
    lines = []
    for item in all_data:
        c = item["course"]
        lines.append(f"\n{'='*50}")
        lines.append(f"COURSE: {c['name']} ({c['code']})")
        lines.append(f"Department: {c.get('department', '')}")
        lines.append(f"Email: {c.get('email', '')}")
        lines.append(f"Classroom: {c.get('classroom', '')}")
        lines.append(f"Schedule: {c.get('schedule', '')}")
        lines.append(f"Office: {c.get('office', '')}")
        lines.append(f"Office Hours: {c.get('office_hours', '')}")

        if item["sections"]:
            lines.append("\n-- Syllabus Sections --")
            for s in item["sections"]:
                lines.append(f"[{s['section_name']}]\n{s['content']}")

        if item["deadlines"]:
            lines.append("\n-- Deadlines --")
            for d in item["deadlines"]:
                lines.append(f"• {d['title']}: {d['due_date']}")

        if item["announcements"]:
            lines.append("\n-- Recent Announcements --")
            for a in item["announcements"]:
                lines.append(f"• {a['title']}: {a['body']}")

    return "\n".join(lines)

def ask_ai(user_id, user_role, user_department, question, history=None):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return "AI service is not configured. Please set the GEMINI_API_KEY environment variable."

    all_data = get_all_accessible_data(user_id, user_role, user_department)
    if not all_data:
        return "No course data found for your account."

    context = build_context(all_data)
    course_list = ", ".join([f"{d['course']['code']}" for d in all_data])

    common_rules = f"""You can respond in the same language the user writes in (Turkish or English).
Always be clear and concise. Use the course data below as your single source of truth.
When something could apply to multiple courses, say which course you mean.

COURSE DATA:
{context}
"""

    if user_role == "instructor":
        system_prompt = f"""You are an AI teaching assistant for instructors on the BAU Syllabus Management Platform.
Your job is to help the instructor REVIEW, IMPROVE, and MANAGE their own syllabi — not just look things up.

You can help the instructor in these ways:
1. Quality & completeness check — point out missing or thin syllabus sections (e.g. no grading
   policy, no academic-integrity statement, no weekly plan), and flag internal contradictions
   (e.g. grading weights that don't add up to 100%, exam dates that clash with stated holidays).
2. Student-perspective feedback — anticipate what students are most likely to misunderstand or
   ask about, and which sections are vague or under-explained.
3. Workload & schedule insight — summarize how deadlines and exams are distributed across the
   term, and highlight weeks where the load clusters or gaps appear.
4. Content drafting & improvement — when asked, draft or rewrite syllabus sections (policies,
   course descriptions, late-submission rules) in clear academic language. Mark drafts clearly
   as suggestions the instructor can edit and approve.

Guidelines:
- Be constructive and specific. Cite the actual section names, dates, or weights from the data.
- For completeness checks, compare against a typical university syllabus (description, objectives,
  grading, schedule, policies, academic integrity, contact info) and name what's missing.
- When you draft content, clearly label it as a suggestion, not an official policy.
- Do not invent facts about the course; if data is missing, say so and offer to help add it.
- {common_rules}"""
    else:
        system_prompt = f"""You are a helpful course assistant for students on the BAU Syllabus Management Platform.
Your job is to help the student quickly FIND and UNDERSTAND information in their enrolled courses.

You can help the student in these ways:
- Answer questions about exam dates, deadlines, grading policy, weekly plan, and course logistics.
- Summarize or explain syllabus sections in plain language.
- Remind them what is coming up soon.

Guidelines:
- Answer strictly from the course data below. Do not make up information.
- If something is not in the data, say you don't have that information and suggest contacting
  the instructor.
- Be friendly, clear, and concise.
- {common_rules}"""

    gemini_messages = []
    if history:
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_messages.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })

    gemini_messages.append({
        "role": "user",
        "parts": [{"text": question}]
    })

    import urllib.request
    import json
    import ssl

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": gemini_messages,
        "generationConfig": {
            "maxOutputTokens": 1024,
            "temperature": 0.3
        }
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        answer = result["candidates"][0]["content"]["parts"][0]["text"]
        return answer.strip()

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            err = json.loads(error_body)
            msg = err.get("error", {}).get("message", "Unknown error")
            return f"AI error: {msg}"
        except Exception:
            return f"AI error (HTTP {e.code}): {error_body[:200]}"
    except Exception as e:
        return f"AI service unavailable: {str(e)}"