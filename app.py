from flask import Flask, redirect, render_template, request, url_for

import db

app = Flask(__name__)


@app.before_request
def setup_database():
    if not getattr(app, "_db_ready", False):
        db.init_db()
        db.seed_db()
        app._db_ready = True


@app.route("/")
def index():
    edit_id = request.args.get("edit", type=int)
    return render_template(
        "index.html",
        notes=db.get_notes(),
        bullets=db.get_draft_bullets(),
        edit_id=edit_id,
    )


@app.route("/briefings")
def past_briefings():
    return render_template(
        "past_briefings.html",
        briefings=db.get_past_briefings(),
        history=db.get_history(),
        history_timeline=db.get_history_timeline(),
    )


@app.route("/briefings/<int:briefing_id>")
def briefing_detail(briefing_id):
    bullets = db.get_briefing_bullets(briefing_id)
    if not bullets:
        return redirect(url_for("past_briefings"))
    return render_template(
        "briefing_detail.html",
        briefing_id=briefing_id,
        bullets=bullets,
        briefing=db.get_briefing(briefing_id),
        history=db.get_briefing_history(briefing_id),
    )


@app.route("/notes", methods=["POST"])
def add_note():
    body = request.form.get("body", "").strip()
    if not body:
        return redirect(url_for("index"))
    from datetime import datetime
    title = f"Note - {datetime.now().strftime('%b %d')}"
    db.add_note(title, body)
    return redirect(url_for("index"))


@app.route("/bullets/<int:bullet_id>/approve", methods=["POST"])
def approve_bullet(bullet_id):
    db.approve_bullet(bullet_id)
    return redirect(url_for("index"))


@app.route("/bullets/<int:bullet_id>/reject", methods=["POST"])
def reject_bullet(bullet_id):
    db.reject_bullet(bullet_id)
    return redirect(url_for("index"))


@app.route("/bullets/<int:bullet_id>/edit", methods=["POST"])
def edit_bullet(bullet_id):
    text = request.form.get("text", "").strip()
    notes = request.form.get("notes", "").strip()
    if text:
        db.update_bullet(bullet_id, text, notes)
    return redirect(url_for("index"))


@app.route("/briefings/save", methods=["POST"])
def save_briefing():
    title = request.form.get("title", "").strip() or None
    db.save_briefing(title)
    return redirect(url_for("past_briefings"))


if __name__ == "__main__":
    app.run(debug=True)
