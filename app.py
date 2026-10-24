import os, io, sqlite3, json, secrets
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image, ImageStat, ImageFilter, ImageOps, ImageEnhance
import numpy as np

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "optivision.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("OPTIVISION_SECRET", "change-this-secret-key-before-deployment")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analyses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, filename TEXT NOT NULL, stored_name TEXT NOT NULL,
            width INTEGER, height INTEGER, score REAL, metrics TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS activity(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            event TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        admin = con.execute("SELECT id FROM users WHERE email=?", ("admin@optivision.local",)).fetchone()
        if not admin:
            con.execute("INSERT INTO users(name,email,password_hash,role,active,created_at) VALUES(?,?,?,?,?,?)",
                ("Main Admin", "admin@optivision.local", generate_password_hash("Admin@12345"), "admin", 1, datetime.now().isoformat(timespec="seconds")))

def log_event(user_id, event):
    with db() as con:
        con.execute("INSERT INTO activity(user_id,event,created_at) VALUES(?,?,?)",
                    (user_id, event, datetime.now().isoformat(timespec="seconds")))

def current_user():
    if not session.get("user_id"): return None
    with db() as con:
        return con.execute("SELECT id,name,email,role,active,created_at FROM users WHERE id=?", (session["user_id"],)).fetchone()

@app.context_processor
def inject_user():
    return {"current_user": current_user()}

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("login"))
        if not user["active"]:
            session.clear()
            flash("This account is disabled. Contact the administrator.", "error")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user()["role"] != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def pct(v):
    return round(float(max(0, min(100, v))), 1)

def auto_enhance_and_resize(input_path, output_path, max_dimension=1600):
    """Automatically resizes oversized images and applies adaptive enhancement for clarity."""
    with Image.open(input_path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        
        # Resize if dimensions exceed limits while maintaining aspect ratio
        if img.width > max_dimension or img.height > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            
        # Apply gentle automated enhancements for poor or standard quality inputs
        img = ImageEnhance.Sharpness(img).enhance(1.25)
        img = ImageEnhance.Contrast(img).enhance(1.1)
        
        img.save(output_path, quality=95, optimize=True)

def analyze_image(path):
    image = Image.open(path)
    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    rgb = np.asarray(image, dtype=np.float32) / 255.0
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    lum = 0.2126*r + 0.7152*g + 0.0722*b
    brightness = float(lum.mean() * 100)
    contrast_std = float(lum.std() * 100)
    gray = Image.fromarray((lum * 255).astype(np.uint8))
    edges = np.asarray(gray.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    sharpness_raw = float(edges.var())
    sharpness = pct((sharpness_raw / 500.0) * 100)
    blur = pct(100 - sharpness)
    saturation_arr = np.max(rgb, axis=2) - np.min(rgb, axis=2)
    saturation = float(saturation_arr.mean() * 100)
    vibrance = pct(np.mean(saturation_arr * (1 - saturation_arr)) * 400)
    highlights = float((lum >= 0.90).mean() * 100)
    shadows = float((lum <= 0.10).mean() * 100)
    under = float((lum < 0.05).mean() * 100)
    over = float((lum > 0.98).mean() * 100)
    means = rgb.mean(axis=(0,1))
    warm_cool = float((means[0] - means[2]) * 100)
    color_temp = round(5500 + warm_cool * 3000)
    color_balance = pct(100 - abs(float(means[0]-means[1]))*100 - abs(float(means[1]-means[2]))*100)
    small_blur = np.asarray(image.filter(ImageFilter.GaussianBlur(radius=1.2)), dtype=np.float32)
    noise = pct(np.mean(np.abs(np.asarray(image, dtype=np.float32)-small_blur)) / 18 * 100)
    dynamic_range = pct((np.percentile(lum, 95) - np.percentile(lum, 5)) * 100)
    exposure = pct(100 - abs(brightness - 50) * 1.65 - under*0.6 - over*0.6)
    contrast_score = pct(100 - abs(contrast_std - 24) * 2.0)
    highlight_score = pct(100 - highlights * 2.5)
    shadow_score = pct(100 - shadows * 2.5)
    noise_score = pct(100 - noise)
    score = pct(exposure*0.22 + sharpness*0.20 + contrast_score*0.16 +
                dynamic_range*0.12 + color_balance*0.10 + (100-noise)*0.08 +
                highlight_score*0.06 + shadow_score*0.06)
    metrics = {
        "brightness": round(brightness,1), "contrast": round(contrast_std,1),
        "sharpness": sharpness, "blurriness": blur, "exposure": exposure,
        "highlights": round(highlights,1), "shadows": round(shadows,1),
        "saturation": round(saturation,1), "vibrance": vibrance,
        "color_temperature": color_temp, "color_balance": color_balance,
        "noise": noise, "dynamic_range": dynamic_range,
        "width": width, "height": height
    }
    tips = []
    if brightness < 35: tips.append("The image is relatively dark. Try a small exposure or shadow lift.")
    elif brightness > 70: tips.append("The image is bright. Check highlights before increasing exposure further.")
    if sharpness < 20: tips.append("Fine detail appears limited. Check focus and avoid excessive digital sharpening.")
    if highlights > 10: tips.append("Some bright areas may be clipped; reduce highlights if detail is missing.")
    if shadows > 15: tips.append("Many pixels are in deep shadows; lift shadows if those areas should show detail.")
    if saturation < 12: tips.append("Colors are muted. Increase saturation gently if a more vivid look is intended.")
    if noise > 20: tips.append("Visible high-frequency variation may indicate noise or texture; inspect at 100% zoom.")
    if not tips: tips.append("The measured signals look balanced overall. Review the image at full size for final judgement.")
    return metrics, score, tips, width, height

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        if not name or not email or len(password) < 8:
            flash("Enter your name, a valid email, and a password of at least 8 characters.", "error")
            return render_template("auth.html", mode="register")
        try:
            with db() as con:
                con.execute("INSERT INTO users(name,email,password_hash,role,active,created_at) VALUES(?,?,?,?,?,?)",
                    (name,email,generate_password_hash(password),"user",1,datetime.now().isoformat(timespec="seconds")))
            flash("Account created. You can sign in now.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("An account with that email already exists.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
        elif not user["active"]:
            flash("This account is disabled. Contact the administrator.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            log_event(user["id"], "Signed in")
            return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    uid = session.get("user_id")
    if uid: log_event(uid, "Signed out")
    session.clear()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    with db() as con:
        rows = con.execute("SELECT * FROM analyses WHERE user_id=? ORDER BY id DESC LIMIT 5",(user["id"],)).fetchall()
        stats = con.execute("SELECT COUNT(*) n, AVG(score) avg FROM analyses WHERE user_id=?",(user["id"],)).fetchone()
    return render_template("dashboard.html", rows=rows, stats=stats)

@app.route("/upload", methods=["GET","POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files.get("image")
        if not file or not file.filename:
            flash("Choose an image first.", "error")
            return redirect(url_for("upload"))
        if not allowed_file(file.filename):
            flash("Supported formats: JPG, JPEG, PNG, WEBP.", "error")
            return redirect(url_for("upload"))
        try:
            raw = file.read()
            image = Image.open(io.BytesIO(raw))
            image.verify()
            file.stream.seek(0)
        except Exception:
            flash("This file does not appear to be a valid image.", "error")
            return redirect(url_for("upload"))
            
        original = secure_filename(file.filename) or "image"
        base_name, ext = os.path.splitext(original)
        ext = ext.lower() if ext else ".jpg"
        stored_prefix = secrets.token_hex(12)
        stored = stored_prefix + ext
        enhanced_stored = stored_prefix + "_enhanced" + ext
        
        path = os.path.join(UPLOAD_DIR, stored)
        enhanced_path = os.path.join(UPLOAD_DIR, enhanced_stored)
        
        file.save(path)
        
        # Automatically enhance and resize the image for better results and download readiness
        try:
            auto_enhance_and_resize(path, enhanced_path)
        except Exception:
            # Fallback if enhancement fails
            if os.path.exists(path):
                import shutil
                shutil.copy(path, enhanced_path)

        try:
            metrics, score, tips, width, height = analyze_image(enhanced_path)
        except Exception:
            if os.path.exists(path): os.remove(path)
            if os.path.exists(enhanced_path): os.remove(enhanced_path)
            flash("Could not analyze this image. Please try another file.", "error")
            return redirect(url_for("upload"))
            
        with db() as con:
            cur = con.execute("INSERT INTO analyses(user_id,filename,stored_name,width,height,score,metrics,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (current_user()["id"], original, stored, width, height, score, json.dumps({"metrics":metrics,"tips":tips}), datetime.now().isoformat(timespec="seconds")))
            aid = cur.lastrowid
        log_event(current_user()["id"], f"Analyzed and enhanced {original}")
        return redirect(url_for("result", analysis_id=aid))
    return render_template("upload.html")

@app.route("/result/<int:analysis_id>")
@login_required
def result(analysis_id):
    with db() as con:
        row = con.execute("SELECT * FROM analyses WHERE id=?",(analysis_id,)).fetchone()
    if not row: abort(404)
    if row["user_id"] != current_user()["id"] and current_user()["role"] != "admin": abort(403)
    data = json.loads(row["metrics"])
    return render_template("result.html", row=row, metrics=data["metrics"], tips=data["tips"])

@app.route("/image/<int:analysis_id>")
@login_required
def image_file(analysis_id):
    with db() as con:
        row = con.execute("SELECT * FROM analyses WHERE id=?",(analysis_id,)).fetchone()
    if not row or (row["user_id"] != current_user()["id"] and current_user()["role"] != "admin"): abort(404)
    
    # Serve enhanced version if available, otherwise original
    stored = row["stored_name"]
    base, ext = os.path.splitext(stored)
    enhanced_stored = base + "_enhanced" + ext
    enhanced_path = os.path.join(UPLOAD_DIR, enhanced_stored)
    
    if os.path.exists(enhanced_path):
        return send_file(enhanced_path)
    return send_file(os.path.join(UPLOAD_DIR, stored))

@app.route("/download/<int:analysis_id>")
@login_required
def download_image(analysis_id):
    with db() as con:
        row = con.execute("SELECT * FROM analyses WHERE id=?",(analysis_id,)).fetchone()
    if not row or (row["user_id"] != current_user()["id"] and current_user()["role"] != "admin"): abort(404)
    
    stored = row["stored_name"]
    base, ext = os.path.splitext(stored)
    enhanced_stored = base + "_enhanced" + ext
    enhanced_path = os.path.join(UPLOAD_DIR, enhanced_stored)
    
    if os.path.exists(enhanced_path):
        return send_file(enhanced_path, as_attachment=True, download_name="enhanced_" + row["filename"])
    return send_file(os.path.join(UPLOAD_DIR, stored), as_attachment=True, download_name=row["filename"])

@app.route("/history")
@login_required
def history():
    with db() as con:
        rows = con.execute("SELECT * FROM analyses WHERE user_id=? ORDER BY id DESC",(current_user()["id"],)).fetchall()
    return render_template("history.html", rows=rows)

@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        if name:
            with db() as con: con.execute("UPDATE users SET name=? WHERE id=?",(name,current_user()["id"]))
            flash("Profile updated.", "success")
            return redirect(url_for("profile"))
    return render_template("profile.html", user=current_user())

@app.route("/admin")
@admin_required
def admin():
    with db() as con:
        stats = {
            "users": con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
            "analyses": con.execute("SELECT COUNT(*) n FROM analyses").fetchone()["n"],
            "avg": con.execute("SELECT AVG(score) n FROM analyses").fetchone()["n"],
        }
        users = con.execute("SELECT id,name,email,role,active,created_at FROM users ORDER BY id DESC").fetchall()
        analyses = con.execute("SELECT a.*,u.name user_name FROM analyses a JOIN users u ON a.user_id=u.id ORDER BY a.id DESC LIMIT 12").fetchall()
        activity = con.execute("SELECT activity.*,users.name user_name FROM activity LEFT JOIN users ON activity.user_id=users.id ORDER BY activity.id DESC LIMIT 12").fetchall()
    return render_template("admin.html", stats=stats, users=users, analyses=analyses, activity=activity)

@app.route("/admin/user/<int:user_id>", methods=["POST"])
@admin_required
def admin_user(user_id):
    action = request.form.get("action")
    if user_id == current_user()["id"]:
        flash("You cannot change your own account status or role here.", "error")
    else:
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
            if user:
                if action == "toggle":
                    con.execute("UPDATE users SET active=? WHERE id=?",(0 if user["active"] else 1,user_id))
                    flash("User status updated.", "success")
                elif action in ("user","admin"):
                    con.execute("UPDATE users SET role=? WHERE id=?",(action,user_id))
                    flash("User role updated.", "success")
    return redirect(url_for("admin"))

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="You do not have permission to access this page."), 403
@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="We could not find that page."), 404
@app.errorhandler(413)
def too_large(_):
    flash("Image is too large. The maximum upload size is 12 MB.", "error")
    return redirect(url_for("upload"))

init_db()
if __name__ == "__main__":
    app.run(debug=True)