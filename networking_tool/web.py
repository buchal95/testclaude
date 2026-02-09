"""
Flask web application for the Networking Tool.
Based on "Never Eat Alone" by Keith Ferrazzi.
"""

import os
import functools
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, g

from . import database as db

CIRCLE_LABELS = {
    "inner_circle": "Vnitrni kruh",
    "close": "Blizci",
    "acquaintance": "Znami",
    "dormant": "Spici kontakty",
}

INTERACTION_TYPES = {
    "meal": "Jidlo",
    "coffee": "Kava",
    "call": "Hovor",
    "email": "E-mail",
    "event": "Akce",
    "intro": "Predstaveni",
    "other": "Jine",
}

GENEROSITY_CATEGORIES = {
    "intro": "Predstaveni",
    "advice": "Rada",
    "resource": "Zdroj/informace",
    "help": "Pomoc",
    "gift": "Darek",
    "referral": "Doporuceni",
}


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-networking-tool-key")

    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        db.DB_PATH = db_path
    db.init_db()

    # Load user before each request
    @app.before_request
    def load_user():
        user_id = session.get("user_id")
        g.user = db.get_user(user_id) if user_id else None

    # Template helpers
    @app.template_filter("circle_label")
    def circle_label(value):
        return CIRCLE_LABELS.get(value, value)

    @app.template_filter("interaction_label")
    def interaction_label(value):
        return INTERACTION_TYPES.get(value, value)

    @app.template_filter("generosity_label")
    def generosity_label(value):
        return GENEROSITY_CATEGORIES.get(value, value)

    @app.context_processor
    def inject_globals():
        return {
            "circle_labels": CIRCLE_LABELS,
            "interaction_types": INTERACTION_TYPES,
            "generosity_categories": GENEROSITY_CATEGORIES,
            "today": datetime.now().strftime("%Y-%m-%d"),
            "current_user": g.user,
        }

    # --- Auth ---

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"]
            password2 = request.form["password2"]
            display_name = request.form.get("display_name", "").strip() or None

            if not username or not password:
                flash("Vyplnte uzivatelske jmeno a heslo.", "error")
                return render_template("register.html")
            if len(password) < 6:
                flash("Heslo musi mit alespon 6 znaku.", "error")
                return render_template("register.html")
            if password != password2:
                flash("Hesla se neshoduji.", "error")
                return render_template("register.html")

            user_id = db.create_user(username, password, display_name=display_name)
            if not user_id:
                flash("Uzivatelske jmeno jiz existuje.", "error")
                return render_template("register.html")

            session["user_id"] = user_id
            flash("Registrace uspesna! Vitej v networking nastroji.", "success")
            return redirect(url_for("dashboard"))
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"]
            user = db.authenticate_user(username, password)
            if not user:
                flash("Spatne uzivatelske jmeno nebo heslo.", "error")
                return render_template("login.html")
            session["user_id"] = user["id"]
            flash(f"Vitej zpet, {user['display_name'] or user['username']}!", "success")
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("Odhlaseni uspesne.", "success")
        return redirect(url_for("login"))

    # --- Dashboard ---

    @app.route("/")
    @login_required
    def dashboard():
        stats = db.get_stats(g.user["id"])
        followups = db.get_pending_followups(g.user["id"])
        return render_template("dashboard.html", stats=stats, followups=followups)

    # --- Contacts ---

    @app.route("/contacts")
    @login_required
    def contacts():
        circle = request.args.get("circle")
        query = request.args.get("q")
        if query:
            contact_list = db.search_contacts(g.user["id"], query)
        else:
            contact_list = db.list_contacts(g.user["id"], circle)
        return render_template("contacts.html", contacts=contact_list,
                               current_circle=circle, query=query)

    @app.route("/contact/new", methods=["GET", "POST"])
    @login_required
    def contact_new():
        if request.method == "POST":
            contact_id = db.add_contact(
                user_id=g.user["id"],
                name=request.form["name"],
                email=request.form.get("email") or None,
                phone=request.form.get("phone") or None,
                company=request.form.get("company") or None,
                role=request.form.get("role") or None,
                circle=request.form.get("circle", "acquaintance"),
                notes=request.form.get("notes") or None,
                how_we_met=request.form.get("how_we_met") or None,
                interests=request.form.get("interests") or None,
                goals=request.form.get("goals") or None,
            )
            flash("Kontakt pridan!", "success")
            return redirect(url_for("contact_detail", contact_id=contact_id))
        return render_template("contact_form.html", contact=None)

    @app.route("/contact/<int:contact_id>")
    @login_required
    def contact_detail(contact_id):
        contact = db.get_contact(contact_id, g.user["id"])
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))
        interactions = db.get_interactions(contact_id, limit=20)
        generosity = db.get_generosity(contact_id)
        goals = db.get_goals(g.user["id"], contact_id)
        return render_template("contact_detail.html", contact=contact,
                               interactions=interactions, generosity=generosity,
                               goals=goals)

    @app.route("/contact/<int:contact_id>/edit", methods=["GET", "POST"])
    @login_required
    def contact_edit(contact_id):
        contact = db.get_contact(contact_id, g.user["id"])
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))
        if request.method == "POST":
            db.update_contact(
                contact_id,
                g.user["id"],
                name=request.form["name"],
                email=request.form.get("email") or None,
                phone=request.form.get("phone") or None,
                company=request.form.get("company") or None,
                role=request.form.get("role") or None,
                circle=request.form.get("circle"),
                notes=request.form.get("notes") or None,
                how_we_met=request.form.get("how_we_met") or None,
                interests=request.form.get("interests") or None,
                goals=request.form.get("goals") or None,
            )
            flash("Kontakt aktualizovan!", "success")
            return redirect(url_for("contact_detail", contact_id=contact_id))
        return render_template("contact_form.html", contact=contact)

    @app.route("/contact/<int:contact_id>/delete", methods=["POST"])
    @login_required
    def contact_delete(contact_id):
        contact = db.get_contact(contact_id, g.user["id"])
        if contact:
            db.delete_contact(contact_id, g.user["id"])
            flash(f"Kontakt '{contact['name']}' smazan.", "success")
        return redirect(url_for("contacts"))

    # --- Interactions ---

    @app.route("/contact/<int:contact_id>/interaction", methods=["POST"])
    @login_required
    def interaction_add(contact_id):
        contact = db.get_contact(contact_id, g.user["id"])
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))

        follow_up = "follow_up" in request.form
        follow_up_by = request.form.get("follow_up_by") or None
        if follow_up and not follow_up_by:
            follow_up_by = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        db.add_interaction(
            contact_id=contact_id,
            interaction_type=request.form["type"],
            description=request.form.get("description") or None,
            date=request.form.get("date") or None,
            follow_up_needed=follow_up,
            follow_up_by=follow_up_by,
        )
        flash("Interakce zaznamenana!", "success")
        return redirect(url_for("contact_detail", contact_id=contact_id))

    # --- Follow-ups ---

    @app.route("/followups")
    @login_required
    def followups():
        pending = db.get_pending_followups(g.user["id"])
        today = datetime.now().strftime("%Y-%m-%d")
        return render_template("followups.html", followups=pending, today=today)

    @app.route("/followup/<int:interaction_id>/done", methods=["POST"])
    @login_required
    def followup_done(interaction_id):
        db.mark_followup_done(interaction_id, g.user["id"])
        flash("Follow-up splnen!", "success")
        next_url = request.form.get("next", url_for("followups"))
        return redirect(next_url)

    # --- Generosity ---

    @app.route("/contact/<int:contact_id>/give", methods=["POST"])
    @login_required
    def give_add(contact_id):
        contact = db.get_contact(contact_id, g.user["id"])
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))

        db.add_generosity(
            contact_id=contact_id,
            description=request.form["description"],
            category=request.form.get("category") or None,
            date=request.form.get("date") or None,
        )
        flash("Stedrost zaznamenana!", "success")
        return redirect(url_for("contact_detail", contact_id=contact_id))

    # --- Goals ---

    @app.route("/contact/<int:contact_id>/goal", methods=["POST"])
    @login_required
    def goal_add(contact_id):
        contact = db.get_contact(contact_id, g.user["id"])
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))

        db.add_goal(
            contact_id=contact_id,
            goal=request.form["goal"],
            target_date=request.form.get("target_date") or None,
        )
        flash("Cil pridan!", "success")
        return redirect(url_for("contact_detail", contact_id=contact_id))

    @app.route("/goal/<int:goal_id>/done", methods=["POST"])
    @login_required
    def goal_done(goal_id):
        db.complete_goal(goal_id, g.user["id"])
        flash("Cil splnen!", "success")
        return redirect(request.form.get("next", url_for("dashboard")))

    # --- Goals overview ---

    @app.route("/goals")
    @login_required
    def goals():
        show_all = request.args.get("all") == "1"
        goal_list = db.get_goals(g.user["id"], pending_only=not show_all)
        return render_template("goals.html", goals=goal_list, show_all=show_all)

    # --- Tips ---

    @app.route("/tips")
    @login_required
    def tips():
        return render_template("tips.html")

    return app
