import os
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from ai import extract_pdf_text, generate_summary, ask_question
import os
import logging
from dotenv import load_dotenv
from groq import Groq
from pypdf import PdfReader

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_from_directory, abort,jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pymysql
import pymysql.cursors


import config
load_dotenv()

app = Flask(__name__)
app.config.from_object(config)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------
def get_db():
    """Open a fresh connection for this request. Closed manually after use."""
    return pymysql.connect(
        host=app.config['DB_HOST'],
        user=app.config['DB_USER'],
        password=app.config['DB_PASSWORD'],
        database=app.config['DB_NAME'],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']
    )
def split_text(text, chunk_size=1000):
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i+chunk_size])
    return chunks


# ---------------------------------------------------------------------------
# Access-control decorators
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# One-time admin seed
# ---------------------------------------------------------------------------
def seed_admin():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM users WHERE role='admin'")
            if cur.fetchone()['c'] == 0:
                cur.execute(
                    "INSERT INTO users (name, email, password, role) VALUES (%s,%s,%s,'admin')",
                    (
                        app.config['DEFAULT_ADMIN_NAME'],
                        app.config['DEFAULT_ADMIN_EMAIL'],
                        generate_password_hash(app.config['DEFAULT_ADMIN_PASSWORD']),
                    ),
                )
                print(
                    f"[seed] Default admin created -> "
                    f"{app.config['DEFAULT_ADMIN_EMAIL']} / {app.config['DEFAULT_ADMIN_PASSWORD']} "
                    f"(change this password after logging in)"
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------
@app.route('/')
def landing():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.id, p.title, p.description, p.uploaded_at, u.name AS author
                   FROM papers p JOIN users u ON p.author_id = u.id
                   WHERE p.status = 'approved'
                   ORDER BY p.uploaded_at DESC LIMIT 6"""
            )
            papers = cur.fetchall()
    finally:
        conn.close()
    return render_template('landing.html', papers=papers)


@app.route('/papers')
def papers():
    """Published papers — visible to everyone, registered or not."""
    q = request.args.get('q', '').strip()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            if q:
                cur.execute(
                    """SELECT p.id, p.title, p.description, p.uploaded_at, u.name AS author
                       FROM papers p JOIN users u ON p.author_id = u.id
                       WHERE p.status = 'approved' AND p.title LIKE %s
                       ORDER BY p.uploaded_at DESC""",
                    (f"%{q}%",),
                )
            else:
                cur.execute(
                    """SELECT p.id, p.title, p.description, p.uploaded_at, u.name AS author
                       FROM papers p JOIN users u ON p.author_id = u.id
                       WHERE p.status = 'approved'
                       ORDER BY p.uploaded_at DESC"""
                )
            results = cur.fetchall()
    finally:
        conn.close()
    return render_template('papers.html', papers=results, q=q)
@app.route("/delete/<int:paper_id>", methods=["POST"])
@login_required
@admin_required
def delete_paper(paper_id):

    conn = get_db()

    try:
        with conn.cursor() as cur:

            # Get filename
            cur.execute(
                "SELECT filename FROM papers WHERE id=%s",
                (paper_id,)
            )

            paper = cur.fetchone()

            if not paper:
                flash("Paper not found.", "danger")
                return redirect(url_for("admin_panel"))

            # Delete database record
            cur.execute(
                "DELETE FROM papers WHERE id=%s",
                (paper_id,)
            )

        conn.commit()

    finally:
        conn.close()

    # Delete PDF file
    pdf_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        paper["filename"]
    )

    if os.path.exists(pdf_path):
        os.remove(pdf_path)

    flash("Paper deleted successfully.", "success")

    return redirect(url_for("admin_panel"))


@app.route('/view/<int:paper_id>')
def view_paper(paper_id):
    """Display a paper's details for reading (no download)."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.*, u.name AS author_name, u.email AS author_email
                   FROM papers p JOIN users u ON p.author_id = u.id
                   WHERE p.id = %s""",
                (paper_id,)
            )
            paper = cur.fetchone()
    finally:
        conn.close()

    if not paper:
        abort(404)

    is_owner = session.get('user_id') == paper['author_id']
    is_admin = session.get('role') == 'admin'
    is_logged_in = 'user_id' in session

    if paper['status'] != 'approved' and not (is_owner or is_admin):
        abort(403)

    return render_template(
        'view_paper.html',
        paper=paper,
        is_owner=is_owner,
        is_admin=is_admin,
        is_logged_in=is_logged_in
    )
@app.route('/download/<int:paper_id>')
@login_required
def download_paper(paper_id):
    """Download a paper file. Only logged-in users can download."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM papers WHERE id = %s", (paper_id,))
            paper = cur.fetchone()
    finally:
        conn.close()

    if not paper:
        abort(404)

    is_owner = session.get('user_id') == paper['author_id']
    is_admin = session.get('role') == 'admin'

    if paper['status'] != 'approved' and not (is_owner or is_admin):
        abort(403)

    return send_from_directory(
        app.config['UPLOAD_FOLDER'], paper['filename'], as_attachment=True
    )

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return render_template('register.html')
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('register.html')

        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE email = %s", (email,))
                if cur.fetchone():
                    flash('An account with this email already exists.', 'danger')
                    return render_template('register.html')
                cur.execute(
                    "INSERT INTO users (name, email, password, role) VALUES (%s,%s,%s,'user')",
                    (name, email, generate_password_hash(password)),
                )
        finally:
            conn.close()

        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cur.fetchone()
        finally:
            conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['name'] = user['name']
            session['role'] = user['role']
            flash(f"Welcome back, {user['name']}!", 'success')
            next_url = request.args.get('next')
            if user['role'] == 'admin':
                return redirect(next_url or url_for('admin_panel'))
            return redirect(next_url or url_for('dashboard'))

        flash('Invalid email or password.', 'danger')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('landing'))


# ---------------------------------------------------------------------------
# Registered-user routes
# ---------------------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, status, uploaded_at, reviewed_at
                   FROM papers WHERE author_id = %s
                   ORDER BY uploaded_at DESC""",
                (session['user_id'],),
            )
            my_papers = cur.fetchall()
    finally:
        conn.close()
    return render_template('dashboard.html', papers=my_papers)


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        file = request.files.get('file')

        if not title or not file or file.filename == '':
            flash('Title and file are required.', 'danger')
            return render_template('upload.html')

        if not allowed_file(file.filename):
            flash('Only PDF, DOC, or DOCX files are allowed.', 'danger')
            return render_template('upload.html')

        safe_name = secure_filename(file.filename)
        unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{session['user_id']}_{safe_name}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))

        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO papers (title, author_id, description, filename, status)
                       VALUES (%s,%s,%s,%s,'pending')""",
                    (title, session['user_id'], description, unique_name),
                )
        finally:
            conn.close()

        flash('Paper submitted. It will appear in the archive once an admin approves it.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('upload.html')


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------
@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.id, p.title, p.description, p.uploaded_at, u.name AS author, u.email
                   FROM papers p JOIN users u ON p.author_id = u.id
                   WHERE p.status = 'pending'
                   ORDER BY p.uploaded_at ASC"""
            )
            pending = cur.fetchall()
            cur.execute(
                """SELECT p.id, p.title, p.status, p.uploaded_at, u.name AS author
                   FROM papers p JOIN users u ON p.author_id = u.id
                   ORDER BY p.uploaded_at DESC LIMIT 50"""
            )
            recent = cur.fetchall()
    finally:
        conn.close()
    return render_template('admin.html', pending=pending, recent=recent)


@app.route('/admin/approve/<int:paper_id>', methods=['POST'])
@login_required
@admin_required
def approve_paper(paper_id):

    conn = get_db()

    try:
        with conn.cursor() as cur:

            cur.execute(
                "SELECT filename, summary, extracted_text FROM papers WHERE id=%s",
                (paper_id,)
            )

            paper = cur.fetchone()

            if not paper:
                flash("Paper not found.", "danger")
                return redirect(url_for("admin_panel"))

            # ✅ Skip if already processed
            if paper.get("summary") and paper.get("extracted_text"):
                summary = paper["summary"]
                text = paper["extracted_text"]

            else:
                pdf_path = os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    paper["filename"]
                )

                text = extract_pdf_text(pdf_path)

                if not text:
                    flash("Failed to extract text.", "danger")
                    return redirect(url_for("admin_panel"))

                # ✅ Only generate if missing
                if paper.get("summary"):
                    summary = paper["summary"]
                else:
                    summary = generate_summary(text)

            cur.execute(
                """
                UPDATE papers
                SET status='approved',
                    reviewed_at=NOW(),
                    summary=%s,
                    extracted_text=%s
                WHERE id=%s
                """,
                (summary, text, paper_id)
            )

    finally:
        conn.close()

    flash("Paper approved successfully.", "success")
    return redirect(url_for("admin_panel"))
@app.route('/admin/reject/<int:paper_id>', methods=['POST'])
@login_required
@admin_required
def reject_paper(paper_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE papers SET status='rejected', reviewed_at=NOW() WHERE id=%s",
                (paper_id,),
            )
    finally:
        conn.close()
    flash('Paper rejected.', 'info')
    return redirect(url_for('admin_panel'))
# CORRECTED chat_with_paper() Function
# Copy this into your app.py to replace the current version

@app.route('/chat/<int:paper_id>', methods=['GET', 'POST'])
@login_required
def chat_paper(paper_id):

    conn = get_db()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT title, summary, extracted_text
                FROM papers WHERE id=%s
            """, (paper_id,))
            
            paper = cur.fetchone()

        if not paper:
            if request.method == 'POST':
                return jsonify({"error": "Paper not found"}), 404
            flash("Paper not found", "danger")
            return redirect(url_for('dashboard'))

        # ✅ USE SUMMARY (FAST)
        context = paper.get('summary')

        # fallback if summary missing
        if not context:
            context = paper.get('extracted_text')

        if not context:
            if request.method == 'POST':
                return jsonify({"error": "No content available"}), 400
            flash("No content available", "danger")
            return redirect(url_for('dashboard'))

        # 💬 CHAT
        if request.method == 'POST':
            question = request.form.get('question', '').strip()

            if not question:
                return jsonify({"error": "Empty question"}), 400

            answer = ask_question(context, question)

            return jsonify({
                "answer": answer,
                "status": "success"
            })

        return render_template('chat.html', paper=paper)

    except Exception as e:
        print(f"Chat error: {e}")

        if request.method == 'POST':
            return jsonify({"error": str(e)}), 500

        flash("Error occurred", "danger")
        return redirect(url_for('dashboard'))

    finally:
        conn.close()
# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message="You don't have permission to view this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message="That page doesn't exist."), 404


if __name__ == '__main__':
    with app.app_context():
        seed_admin()
    port = int(os.environ.get("PORT", 5000))  # important for Render
    app.run(host="0.0.0.0", port=port, debug=False)
