import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "syllabus.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('student','instructor')),
        department TEXT DEFAULT '',
        full_name TEXT DEFAULT '',
        title TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        instructor_id INTEGER NOT NULL,
        department TEXT DEFAULT '',
        credit INTEGER DEFAULT 3,
        delivery TEXT DEFAULT 'face-to-face',
        course_type TEXT DEFAULT 'Departmental Elective',
        classroom TEXT DEFAULT '',
        schedule TEXT DEFAULT '',
        office TEXT DEFAULT '',
        office_hours TEXT DEFAULT '',
        email TEXT DEFAULT '',
        cv_link TEXT DEFAULT '',
        FOREIGN KEY(instructor_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS syllabus_sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        section_name TEXT NOT NULL,
        content TEXT DEFAULT '',
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );

    CREATE TABLE IF NOT EXISTS deadlines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        due_date TEXT NOT NULL,
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );

    CREATE TABLE IF NOT EXISTS enrollments (
        student_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        PRIMARY KEY(student_id, course_id),
        FOREIGN KEY(student_id) REFERENCES users(id),
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );

    CREATE TABLE IF NOT EXISTS deadline_progress (
        student_id INTEGER NOT NULL,
        deadline_id INTEGER NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(student_id, deadline_id),
        FOREIGN KEY(student_id) REFERENCES users(id),
        FOREIGN KEY(deadline_id) REFERENCES deadlines(id)
    );

    CREATE TABLE IF NOT EXISTS syllabus_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        section_name TEXT NOT NULL,
        content TEXT,
        changed_by INTEGER NOT NULL,
        changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(section_id) REFERENCES syllabus_sections(id),
        FOREIGN KEY(changed_by) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        notif_type TEXT DEFAULT 'info',
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );

    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        rating INTEGER CHECK(rating BETWEEN 1 AND 5),
        is_approved INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(course_id) REFERENCES courses(id),
        FOREIGN KEY(student_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS analytics_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        page TEXT,
        course_id INTEGER,
        extra TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS course_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        original_name TEXT NOT NULL,
        file_type TEXT,
        uploaded_by INTEGER NOT NULL,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(course_id) REFERENCES courses(id),
        FOREIGN KEY(uploaded_by) REFERENCES users(id)
    );
    """)

    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:

        # KULLANICILAR
        c.execute("""INSERT INTO users(username,password,role,department)
                     VALUES('ozgeyucelkasap','123456','instructor','Software Engineering')""")
        c.execute("""INSERT INTO users(username,password,role,department)
                     VALUES('oguzhanerdinc','123456','instructor','Industrial Engineering')""")
        c.execute("""INSERT INTO users(username,password,role,department)
                     VALUES('aslıaslan','123456','student','Software Engineering')""")
        c.execute("""INSERT INTO users(username,password,role,department)
                     VALUES('aslıaslan2','123456','student','Industrial Engineering')""")
        c.execute("""INSERT INTO users(username,password,role,department)
                     VALUES('aslıaslan3','123456','student','Software Engineering')""")
        conn.commit()

        inst1 = c.execute("SELECT id FROM users WHERE username='ozgeyucelkasap'").fetchone()[0]
        inst2 = c.execute("SELECT id FROM users WHERE username='oguzhanerdinc'").fetchone()[0]
        s1    = c.execute("SELECT id FROM users WHERE username='aslıaslan'").fetchone()[0]
        s2    = c.execute("SELECT id FROM users WHERE username='aslıaslan2'").fetchone()[0]
        s3    = c.execute("SELECT id FROM users WHERE username='aslıaslan3'").fetchone()[0]

        # INE4211 — Industrial Engineering — oguzhan hoca
        c.execute("""INSERT INTO courses(code,name,instructor_id,department,credit,delivery,
                     course_type,classroom,schedule,office,office_hours,email,cv_link)
                     VALUES('INE4211','Digital Interaction and User Experience (UX)',?,
                     'Industrial Engineering',6,'face-to-face','Departmental Elective','DSC02',
                     'Monday 13:30-17:20 / Wednesday 13:30-17:20',
                     'D440','Monday 11:00-12:00 / Wednesday 11:00-12:00',
                     'ine4211diux@gmail.com','2116_en.pdf (bau.edu.tr)')""", (inst2,))
        conn.commit()

        ine_id = c.execute("SELECT id FROM courses WHERE code='INE4211'").fetchone()[0]

        for s_name, s_content in [
            ("Course Overview", "This course covers the principles of digital interaction and user experience design. Students will learn how to analyze, design, and evaluate digital interfaces using UX methodologies."),
            ("Prerequisites", "No formal prerequisites. Basic familiarity with computers and software is expected."),
            ("Course Learning Outcomes", "1. Understand core UX principles and methodologies.\n2. Conduct user research and usability testing.\n3. Design wireframes and interactive prototypes.\n4. Evaluate digital products using heuristic analysis."),
            ("Course Objectives", "To equip students with the knowledge and skills to design effective, user-centered digital products."),
            ("Contribution to the Program", "This course contributes to program outcomes related to engineering design, communication, and professional responsibility."),
            ("Grading Policy", "Midterm Exam: 30%\nFinal Exam: 40%\nProject: 20%\nParticipation: 10%"),
            ("Weekly Plan", "Week 1: Introduction to UX\nWeek 2: User Research Methods\nWeek 3: Personas and Scenarios\nWeek 4: Information Architecture\nWeek 5: Wireframing\nWeek 6: Prototyping\nWeek 7: Midterm\nWeek 8: Usability Testing\nWeek 9: Heuristic Evaluation\nWeek 10: Visual Design\nWeek 11: Accessibility\nWeek 12: Mobile UX\nWeek 13: AI in UX\nWeek 14: Final Presentations"),
            ("Course Policies", "Attendance is mandatory. Late submissions receive a 10% deduction per day. Academic integrity must be maintained at all times."),
        ]:
            c.execute("INSERT INTO syllabus_sections(course_id,section_name,content) VALUES(?,?,?)",
                      (ine_id, s_name, s_content))

        c.execute("INSERT INTO announcements(course_id,title,body) VALUES(?,?,?)",
                  (ine_id, "Welcome to INE4211!", "Welcome to Digital Interaction and UX. Please review the syllabus carefully."))
        c.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                  (ine_id, "Project Proposal", "2026-03-20"))
        c.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                  (ine_id, "Midterm Exam", "2026-04-07"))
        c.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                  (ine_id, "Final Project Submission", "2026-05-25"))

        c.execute("INSERT INTO enrollments VALUES(?,?)", (s2, ine_id))

        # CSE3011 — Software Engineering — ozge hoca
        c.execute("""INSERT INTO courses(code,name,instructor_id,department,credit,delivery,
                     course_type,classroom,schedule,office,office_hours,email,cv_link)
                     VALUES('CSE3011','Introduction to Artificial Intelligence',?,
                     'Software Engineering',3,'face-to-face','Departmental Elective','B201',
                     'Tuesday 10:00-12:00',
                     'C310','Tuesday 13:00-14:00',
                     'cse3011ai@bau.edu.tr','')""", (inst1,))
        conn.commit()

        cse_id = c.execute("SELECT id FROM courses WHERE code='CSE3011'").fetchone()[0]

        for s_name, s_content in [
            ("Course Overview", "This course introduces the fundamental concepts of Artificial Intelligence including search algorithms, knowledge representation, machine learning, and neural networks."),
            ("Prerequisites", "CSE2001 Data Structures and Algorithms. Basic Python programming knowledge required."),
            ("Course Learning Outcomes", "1. Understand core AI concepts and algorithms.\n2. Implement search and optimization algorithms.\n3. Apply machine learning techniques to real problems.\n4. Design and train basic neural networks."),
            ("Course Objectives", "To provide students with a solid foundation in AI theory and practical implementation skills."),
            ("Contribution to the Program", "Contributes to program outcomes in computational thinking, algorithm design, and modern software engineering practices."),
            ("Grading Policy", "Midterm Exam: 30%\nFinal Exam: 40%\nHomework Assignments: 20%\nParticipation: 10%"),
            ("Weekly Plan", "Week 1: Introduction to AI\nWeek 2: Search Algorithms\nWeek 3: Heuristic Search\nWeek 4: Knowledge Representation\nWeek 5: Logic and Inference\nWeek 6: Planning\nWeek 7: Midterm\nWeek 8: Machine Learning Basics\nWeek 9: Supervised Learning\nWeek 10: Unsupervised Learning\nWeek 11: Neural Networks\nWeek 12: Deep Learning\nWeek 13: NLP Basics\nWeek 14: AI Ethics and Final Review"),
            ("Course Policies", "Attendance is mandatory. Homework must be submitted before class. Collaboration is allowed but copying is not tolerated."),
        ]:
            c.execute("INSERT INTO syllabus_sections(course_id,section_name,content) VALUES(?,?,?)",
                      (cse_id, s_name, s_content))

        c.execute("INSERT INTO announcements(course_id,title,body) VALUES(?,?,?)",
                  (cse_id, "Welcome to CSE3011!", "Welcome to Introduction to AI. Please install Python 3.10+ and Jupyter Notebook before Week 1."))
        c.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                  (cse_id, "Homework 1", "2026-03-15"))
        c.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                  (cse_id, "Midterm Exam", "2026-04-14"))
        c.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                  (cse_id, "Final Project", "2026-05-30"))

        c.execute("INSERT INTO enrollments VALUES(?,?)", (s1, cse_id))
        c.execute("INSERT INTO enrollments VALUES(?,?)", (s3, cse_id))

        # CSE4022 — Software Engineering — ozge hoca
        c.execute("""INSERT INTO courses(code,name,instructor_id,department,credit,delivery,
                     course_type,classroom,schedule,office,office_hours,email,cv_link)
                     VALUES('CSE4022','Software Testing and Quality Assurance',?,
                     'Software Engineering',3,'face-to-face','Departmental Elective','A105',
                     'Thursday 14:00-16:00',
                     'C310','Thursday 16:00-17:00',
                     'cse4022qa@bau.edu.tr','')""", (inst1,))
        conn.commit()

        qa_id = c.execute("SELECT id FROM courses WHERE code='CSE4022'").fetchone()[0]

        for s_name, s_content in [
            ("Course Overview", "This course covers the principles and practices of software testing, including unit testing, integration testing, system testing, and quality assurance methodologies."),
            ("Prerequisites", "CSE2010 Software Engineering Fundamentals."),
            ("Course Learning Outcomes", "1. Design and execute test plans.\n2. Apply unit and integration testing.\n3. Use automated testing tools.\n4. Understand quality assurance processes."),
            ("Grading Policy", "Midterm Exam: 25%\nFinal Exam: 35%\nLab Work: 25%\nParticipation: 15%"),
            ("Weekly Plan", "Week 1: Introduction to Software Testing\nWeek 2: Test Planning\nWeek 3: Unit Testing\nWeek 4: Integration Testing\nWeek 5: System Testing\nWeek 6: Test Automation\nWeek 7: Midterm\nWeek 8: Performance Testing\nWeek 9: Security Testing\nWeek 10: Agile Testing\nWeek 11: CI/CD Pipelines\nWeek 12: Code Coverage\nWeek 13: QA Processes\nWeek 14: Review and Final"),
            ("Course Policies", "Lab attendance is mandatory. All assignments must be submitted via the course portal."),
        ]:
            c.execute("INSERT INTO syllabus_sections(course_id,section_name,content) VALUES(?,?,?)",
                      (qa_id, s_name, s_content))

        c.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                  (qa_id, "Lab 1 Submission", "2026-03-20"))
        c.execute("INSERT INTO deadlines(course_id,title,due_date) VALUES(?,?,?)",
                  (qa_id, "Midterm Exam", "2026-04-10"))

        c.execute("INSERT INTO enrollments VALUES(?,?)", (s1, qa_id))

    # Add title column if missing (migration for existing DBs)
    existing_cols = [row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()]
    if "title" not in existing_cols:
        c.execute("ALTER TABLE users ADD COLUMN title TEXT DEFAULT ''")
    # Migrate old misspelled username on existing databases (only if the new
    # one isn't already present, to avoid a UNIQUE clash).
    has_old = c.execute("SELECT 1 FROM users WHERE username='oguzhanerdınc'").fetchone()
    has_new = c.execute("SELECT 1 FROM users WHERE username='oguzhanerdinc'").fetchone()
    if has_old and not has_new:
        c.execute("UPDATE users SET username='oguzhanerdinc' WHERE username='oguzhanerdınc'")
    # Seed full_name + title for the two advisors (corrects any earlier values)
    c.execute("UPDATE users SET full_name='Özge Yücel Kasap', title='Asst. Prof.' WHERE username='ozgeyucelkasap'")
    c.execute("UPDATE users SET full_name='Oğuzhan Erdinç', title='Asst. Prof.' WHERE username='oguzhanerdinc'")
    conn.commit()

    # Hash any plaintext passwords in place (idempotent). Existing databases
    # seeded before hashing was added get upgraded transparently; werkzeug
    # hashes start with a method prefix like "pbkdf2:" or "scrypt:".
    for u in c.execute("SELECT id, password FROM users").fetchall():
        pw = u["password"] if not isinstance(u, tuple) else u[1]
        if not str(pw).startswith(("pbkdf2:", "scrypt:")):
            c.execute("UPDATE users SET password=? WHERE id=?",
                      (generate_password_hash(pw), u["id"]))

    conn.commit()
    conn.close()