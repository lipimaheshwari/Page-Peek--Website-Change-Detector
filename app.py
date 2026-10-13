import os, re, json, time, hashlib, socket, ipaddress, difflib, smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import urlparse
from threading import Lock

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from database import init_db, get_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "page-peek-local-demo-key")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
init_db()
scheduler = BackgroundScheduler(daemon=True)
job_lock = Lock()

def now_text():
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

def validate_public_url(url):
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False, "Use a full public http:// or https:// URL."
        if parsed.username or parsed.password:
            return False, "URLs containing credentials are not allowed."
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            return False, "Local/private addresses are not allowed."
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            for info in infos:
                ip = ipaddress.ip_address(info[4][0])
                if not ip.is_global:
                    return False, "That address does not look like a public website."
        except socket.gaierror:
            return False, "Could not resolve that website. Check the URL."
        return True, ""
    except Exception:
        return False, "Please enter a valid public website URL."

def normalize_text(text, selectors):
    # Remove user-selected noisy regions before comparison.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, "html.parser")
    for selector in selectors:
        try:
            for node in soup.select(selector):
                node.decompose()
        except Exception:
            continue
    for node in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", text)  # clocks
    text = re.sub(r"\b(session|csrf|nonce|token)[-_:= ]?[\w-]{6,}\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def get_page_snapshot(page_row):
    url = page_row["url"]
    ok, reason = validate_public_url(url)
    if not ok:
        raise ValueError(reason)
    selectors = [x.strip() for x in (page_row["ignore_selectors"] or "").splitlines() if x.strip()]
    watch_selectors = [x.strip() for x in (page_row["watch_selectors"] or "").splitlines() if x.strip()]
    timeout_ms = 20000
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 850}, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(900)
            status = response.status if response else 0
            if status in (401, 403, 429, 503):
                raise RuntimeError(f"Blocked or rate-limited (HTTP {status})")
            if status >= 400:
                raise RuntimeError(f"Website returned HTTP {status}")
            if watch_selectors:
                pieces = []
                for selector in watch_selectors:
                    try:
                        pieces.append(page.locator(selector).first.inner_text(timeout=2500))
                    except Exception:
                        pieces.append("")
                text = "\n".join(pieces)
            else:
                text = page.locator("body").inner_text(timeout=5000)
            html = page.content()
            # Remove selector regions from HTML text as a second line of defence.
            clean = normalize_text(html, selectors)
            if watch_selectors:
                clean = normalize_text("<main>" + text + "</main>", [])
            title = page.title() or url
            screenshot_path = None
            # The caller decides whether this screenshot becomes a saved version.
            temp_path = os.path.join(DATA_DIR, f"temp_{int(time.time()*1000)}.png")
            page.screenshot(path=temp_path, full_page=True, animations="disabled", timeout=12000)
            screenshot_path = temp_path
            return {"text": clean, "hash": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
                    "title": title, "status": status, "screenshot": screenshot_path}
        finally:
            context.close()
            browser.close()

def create_alert(page, old_text, new_text, version_id):
    summary = " ".join(difflib.ndiff(old_text.split(), new_text.split()))
    added = [x[2:] for x in summary.split(" ") if x.startswith("+")][:25]
    removed = [x[2:] for x in summary.split(" ") if x.startswith("-")][:25]
    short = " ".join(difflib.unified_diff(old_text.split(), new_text.split(), n=1, lineterm=""))
    short = short[:1000] or "The page content changed."
    message = f"Page Peek detected a change on {page['name']} ({page['url']}).\nChecked: {now_text()}\n\nSummary:\n{short}\n\nVersion ID: {version_id}"
    webhook = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            import urllib.request
            req = urllib.request.Request(webhook, data=json.dumps({"content": message, "text": message}).encode(),
                headers={"Content-Type":"application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:
            print("Webhook notification failed:", e)
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    if smtp_host and os.environ.get("ALERT_TO") and os.environ.get("ALERT_FROM"):
        try:
            msg = EmailMessage()
            msg["Subject"] = f"Page Peek: {page['name']} changed"
            msg["From"] = os.environ["ALERT_FROM"]
            msg["To"] = os.environ["ALERT_TO"]
            msg.set_content(message)
            with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", "587")), timeout=8) as server:
                server.starttls()
                if os.environ.get("SMTP_USER"):
                    server.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                server.send_message(msg)
        except Exception as e:
            print("Email notification failed:", e)

def run_check(page_id, manual=False):
    # The lock prevents two scheduled/manual checks for the same URL at once.
    with job_lock:
        db = get_db()
        row = db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
        if not row:
            db.close()
            return
        page = dict(row)
        try:
            snap = get_page_snapshot(page)
            previous = db.execute("SELECT * FROM versions WHERE page_id=? ORDER BY id DESC LIMIT 1", (page_id,)).fetchone()
            changed = previous is not None and previous["content_hash"] != snap["hash"]
            save_version = previous is None or changed
            if save_version:
                version_no = (previous["version_no"] + 1) if previous else 1
                final_shot = os.path.join(DATA_DIR, f"page_{page_id}_v{version_no}.png")
                if snap["screenshot"] and os.path.exists(snap["screenshot"]):
                    os.replace(snap["screenshot"], final_shot)
                db.execute("""INSERT INTO versions(page_id, version_no, checked_at, title, content_hash, content_text, screenshot_path)
                              VALUES(?,?,?,?,?,?,?)""",
                           (page_id, version_no, now_text(), snap["title"], snap["hash"], snap["text"], final_shot))
                version_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                if changed:
                    create_alert(page, previous["content_text"], snap["text"], version_no)
            else:
                if snap["screenshot"] and os.path.exists(snap["screenshot"]):
                    os.remove(snap["screenshot"])
            db.execute("UPDATE pages SET last_checked=?, last_status=?, last_error='', last_hash=?, last_title=? WHERE id=?",
                       (now_text(), "changed" if changed else "ok", snap["hash"], snap["title"], page_id))
            db.commit()
        except Exception as e:
            db.execute("UPDATE pages SET last_checked=?, last_status=?, last_error=? WHERE id=?",
                       (now_text(), "blocked" if "Blocked" in str(e) or "rate-limited" in str(e) else "error", str(e)[:500], page_id))
            db.commit()
        finally:
            db.close()

def scheduled_checks():
    db = get_db()
    pages = db.execute("SELECT id FROM pages WHERE enabled=1").fetchall()
    db.close()
    for item in pages:
        # Scheduler is serial and only queues each monitored page once per interval.
        run_check(item["id"])

def refresh_schedule():
    if scheduler.running:
        scheduler.remove_all_jobs()
        db = get_db()
        rows = db.execute("SELECT id, interval_minutes FROM pages WHERE enabled=1").fetchall()
        db.close()
        for row in rows:
            scheduler.add_job(run_check, IntervalTrigger(minutes=max(15, min(1440, row["interval_minutes"]))),
                              args=[row["id"]], id=f"page-{row['id']}", replace_existing=True,
                              max_instances=1, coalesce=True, misfire_grace_time=60)

@app.route("/")
def index():
    db = get_db()
    pages = db.execute("""SELECT p.*, (SELECT COUNT(*) FROM versions v WHERE v.page_id=p.id) AS version_count
                          FROM pages p ORDER BY p.created_at DESC""").fetchall()
    db.close()
    return render_template("index.html", pages=pages)

@app.post("/add")
def add_page():
    name = request.form.get("name", "").strip()[:80]
    url = request.form.get("url", "").strip()
    interval = request.form.get("interval", "60")
    watch = request.form.get("watch_selectors", "").strip()[:1000]
    ignore = request.form.get("ignore_selectors", "").strip()[:1000]
    ok, reason = validate_public_url(url)
    try:
        interval = int(interval)
    except ValueError:
        interval = 60
    if not name or not url:
        flash("Please add both a name and URL.", "error")
    elif not ok:
        flash(reason, "error")
    elif interval < 15 or interval > 1440:
        flash("Check interval must be between 15 minutes and 24 hours.", "error")
    else:
        db = get_db()
        existing = db.execute("SELECT id FROM pages WHERE url=?", (url,)).fetchone()
        if existing:
            flash("That URL is already on your list. Edit the existing page instead.", "error")
        else:
            cur = db.execute("""INSERT INTO pages(name,url,interval_minutes,watch_selectors,ignore_selectors,created_at)
                                VALUES(?,?,?,?,?,?)""", (name,url,interval,watch,ignore,now_text()))
            db.commit()
            page_id = cur.lastrowid
            db.close()
            run_check(page_id)  # Capture the first baseline straight away.
            refresh_schedule()
            flash("Page added! Its first snapshot is ready.", "success")
            return redirect(url_for("index"))
        db.close()
    return redirect(url_for("index"))

@app.post("/check/<int:page_id>")
def check_now(page_id):
    run_check(page_id, manual=True)
    flash("Check finished. See the latest status below.", "success")
    return redirect(url_for("index"))

@app.post("/delete/<int:page_id>")
def delete_page(page_id):
    db = get_db()
    versions = db.execute("SELECT screenshot_path FROM versions WHERE page_id=?", (page_id,)).fetchall()
    db.execute("DELETE FROM pages WHERE id=?", (page_id,))
    db.commit(); db.close()
    for v in versions:
        try:
            if v["screenshot_path"] and os.path.exists(v["screenshot_path"]): os.remove(v["screenshot_path"])
        except OSError: pass
    refresh_schedule()
    flash("Page removed.", "success")
    return redirect(url_for("index"))

@app.route("/page/<int:page_id>")
def page_detail(page_id):
    db = get_db()
    page = db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    if not page:
        db.close(); return "Page not found", 404
    versions = db.execute("SELECT * FROM versions WHERE page_id=? ORDER BY id DESC", (page_id,)).fetchall()
    db.close()
    latest = versions[0] if versions else None
    previous = versions[1] if len(versions)>1 else None
    diff = ""
    if latest and previous:
        diff = "\n".join(difflib.unified_diff(previous["content_text"].split(), latest["content_text"].split(),
                                               fromfile=f"Version {previous['version_no']}", tofile=f"Version {latest['version_no']}", lineterm=""))
    return render_template("detail.html", page=page, versions=versions, latest=latest, previous=previous, diff=diff)

@app.get("/shot/<int:version_id>")
def screenshot(version_id):
    db = get_db()
    row = db.execute("SELECT screenshot_path FROM versions WHERE id=?", (version_id,)).fetchone()
    db.close()
    if not row or not row["screenshot_path"] or not os.path.isfile(row["screenshot_path"]):
        return "Screenshot not found", 404
    return send_from_directory(DATA_DIR, os.path.basename(row["screenshot_path"]))

@app.route("/compare/<int:version_a>/<int:version_b>")
def compare(version_a, version_b):
    db = get_db()
    a = db.execute("SELECT * FROM versions WHERE id=?", (version_a,)).fetchone()
    b = db.execute("SELECT * FROM versions WHERE id=?", (version_b,)).fetchone()
    db.close()
    if not a or not b: return "Version not found", 404
    diff = "\n".join(difflib.unified_diff(a["content_text"].split(), b["content_text"].split(),
                                           fromfile=f"Version {a['version_no']}", tofile=f"Version {b['version_no']}", lineterm=""))
    return render_template("compare.html", a=a, b=b, diff=diff)

@app.get("/diff-image/<path:filename>")
def diff_image(filename):
    # Only serve generated diff images, not arbitrary filesystem paths.
    if not re.fullmatch(r"diff_\\d+_\\d+\\.png", filename):
        return "Not found", 404
    return send_from_directory(DATA_DIR, filename)

@app.context_processor
def inject_helpers():
    return {"datetime": datetime}

if __name__ == "__main__":
    if not scheduler.running:
        scheduler.start()
    refresh_schedule()
    app.run(debug=True, use_reloader=False)
