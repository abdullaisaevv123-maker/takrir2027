import os
import sqlite3
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "pdfs"
UPLOAD_DIR = BASE_DIR / "uploads"
DB_PATH = BASE_DIR / "data.db"
PDF_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS beneficiaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_number TEXT UNIQUE NOT NULL,
            sponsor TEXT, beneficiary TEXT, beneficiary_number TEXT,
            internal_number TEXT, birth_date TEXT, gender TEXT, health TEXT,
            class_name TEXT, future_wish TEXT, impact TEXT, notes TEXT,
            link TEXT, pdf_url TEXT, created_at TEXT NOT NULL
        )
    """)
    conn.commit(); conn.close()

def clean_filename(value):
    value = secure_filename(value or "")
    return value or "file"

def save_upload(file, file_number, field):
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return None
    path = UPLOAD_DIR / f"{clean_filename(file_number)}_{field}{ext}"
    file.save(path)
    return path

def make_pdf(file_number, data, image_paths):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib.utils import ImageReader
    from arabic_reshaper import reshape
    from bidi.algorithm import get_display

    fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"
    ]
    font_path = next((p for p in fonts if os.path.exists(p)), None)
    if not font_path:
        raise RuntimeError("Arabic font not found on server")
    try:
        pdfmetrics.getFont("AppArabic")
    except KeyError:
        pdfmetrics.registerFont(TTFont("AppArabic", font_path))

    out = PDF_DIR / f"{clean_filename(file_number)}.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    width, height = A4; margin = 42; y = height - 50

    def ar(text):
        return get_display(reshape(str(text or "")))
    def line(label, value):
        nonlocal y
        c.setFont("AppArabic", 11)
        c.drawRightString(width - margin, y, ar(f"{label}: {value or '-'}"))
        y -= 24
        if y < 70:
            c.showPage(); y = height - 50

    c.setFont("AppArabic", 18)
    c.drawCentredString(width / 2, y, ar("استمارة تقرير اليتيم")); y -= 32
    c.setFont("AppArabic", 12)
    c.drawCentredString(width / 2, y, ar(f"رقم الملف: {file_number}")); y -= 32

    fields = [
        ("الدولة", data.get("country")), ("اسم الكافل", data.get("sponsor")),
        ("اسم اليتيم", data.get("beneficiary")), ("رقم الكافل", data.get("beneficiary_number")),
        ("الرقم الداخلي", data.get("internal_number")), ("تاريخ الميلاد", data.get("birth_date")),
        ("الجنس", data.get("gender")), ("الحالة الصحية", data.get("health")),
        ("الصف", data.get("class_name")), ("أمنية المستقبل", data.get("future_wish")),
        ("أثر الكفالة", data.get("impact")), ("ملاحظات المشرف", data.get("notes")),
        ("رابط الفيديو / الملف", data.get("link"))
    ]
    for label, value in fields: line(label, value)

    for path in image_paths:
        if y < 220: c.showPage(); y = height - 50
        try:
            img = ImageReader(str(path)); iw, ih = img.getSize()
            scale = min(170 / iw, 220 / ih); dw, dh = iw * scale, ih * scale
            c.drawImage(img, margin, y - dh, width=dw, height=dh, preserveAspectRatio=True, mask="auto")
            y -= dh + 20
        except Exception: pass
    c.save(); return out

@app.route("/")
def index():
    pdfs = sorted([p.name for p in PDF_DIR.glob("*.pdf")], reverse=True)
    return render_template("index.html", pdfs=pdfs)

@app.post("/api/generate")
def generate():
    try:
        form = request.form
        file_number = (form.get("file_number") or "").strip()
        if not file_number: return jsonify(ok=False, error="Файл № киргизиңиз."), 400
        data = {k: form.get(k, "").strip() for k in [
            "country", "sponsor", "beneficiary", "beneficiary_number", "internal_number",
            "birth_date", "gender", "health", "class_name", "future_wish", "impact", "notes", "link"]}
        images = []
        for field in ("photo10", "photo1", "photo2", "photo3"):
            saved = save_upload(request.files.get(field), file_number, field)
            if saved: images.append(saved)
        pdf = make_pdf(file_number, data, images)
        pdf_url = f"/download/{pdf.name}"
        conn = db()
        conn.execute("""
            INSERT INTO beneficiaries
            (file_number,sponsor,beneficiary,beneficiary_number,internal_number,birth_date,gender,health,class_name,future_wish,impact,notes,link,pdf_url,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(file_number) DO UPDATE SET
            sponsor=excluded.sponsor, beneficiary=excluded.beneficiary,
            beneficiary_number=excluded.beneficiary_number, internal_number=excluded.internal_number,
            birth_date=excluded.birth_date, gender=excluded.gender, health=excluded.health,
            class_name=excluded.class_name, future_wish=excluded.future_wish, impact=excluded.impact,
            notes=excluded.notes, link=excluded.link, pdf_url=excluded.pdf_url, created_at=excluded.created_at
        """, (file_number,data["sponsor"],data["beneficiary"],data["beneficiary_number"],data["internal_number"],data["birth_date"],data["gender"],data["health"],data["class_name"],data["future_wish"],data["impact"],data["notes"],data["link"],pdf_url,datetime.now().isoformat(timespec="seconds")))
        conn.commit(); conn.close()
        return jsonify(ok=True, file_number=file_number, download=pdf_url)
    except Exception as e:
        app.logger.exception("generate failed")
        return jsonify(ok=False, error=str(e)), 500

@app.get("/api/search")
def search():
    n = (request.args.get("file_number") or "").strip()
    if not n: return jsonify(ok=False, error="Файл № жазыңыз."), 400
    conn = db(); row = conn.execute("SELECT * FROM beneficiaries WHERE file_number=?", (n,)).fetchone(); conn.close()
    if not row: return jsonify(ok=False, error="Катталган адам табылган жок."), 404
    return jsonify(ok=True, beneficiary=dict(row))

@app.get("/download/<path:filename>")
def download(filename):
    return send_from_directory(PDF_DIR, clean_filename(filename), as_attachment=True)

@app.get("/health")
def health(): return jsonify(status="ok")

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
