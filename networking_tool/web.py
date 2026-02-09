"""
Flask web application for the Networking Tool.
Based on "Never Eat Alone" by Keith Ferrazzi.
"""

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash

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


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-networking-tool-key")

    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        db.DB_PATH = db_path
    db.init_db()

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
        }

    # --- Dashboard ---

    @app.route("/")
    def dashboard():
        stats = db.get_stats()
        followups = db.get_pending_followups()
        return render_template("dashboard.html", stats=stats, followups=followups)

    # --- Contacts ---

    @app.route("/contacts")
    def contacts():
        circle = request.args.get("circle")
        query = request.args.get("q")
        if query:
            contact_list = db.search_contacts(query)
        else:
            contact_list = db.list_contacts(circle)
        return render_template("contacts.html", contacts=contact_list,
                               current_circle=circle, query=query)

    @app.route("/contact/new", methods=["GET", "POST"])
    def contact_new():
        if request.method == "POST":
            contact_id = db.add_contact(
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
            flash(f"Kontakt pridan!", "success")
            return redirect(url_for("contact_detail", contact_id=contact_id))
        return render_template("contact_form.html", contact=None)

    @app.route("/contact/<int:contact_id>")
    def contact_detail(contact_id):
        contact = db.get_contact(contact_id)
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))
        interactions = db.get_interactions(contact_id, limit=20)
        generosity = db.get_generosity(contact_id)
        goals = db.get_goals(contact_id)
        return render_template("contact_detail.html", contact=contact,
                               interactions=interactions, generosity=generosity,
                               goals=goals)

    @app.route("/contact/<int:contact_id>/edit", methods=["GET", "POST"])
    def contact_edit(contact_id):
        contact = db.get_contact(contact_id)
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))
        if request.method == "POST":
            db.update_contact(
                contact_id,
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
    def contact_delete(contact_id):
        contact = db.get_contact(contact_id)
        if contact:
            db.delete_contact(contact_id)
            flash(f"Kontakt '{contact['name']}' smazan.", "success")
        return redirect(url_for("contacts"))

    # --- Interactions ---

    @app.route("/contact/<int:contact_id>/interaction", methods=["POST"])
    def interaction_add(contact_id):
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
    def followups():
        pending = db.get_pending_followups()
        today = datetime.now().strftime("%Y-%m-%d")
        return render_template("followups.html", followups=pending, today=today)

    @app.route("/followup/<int:interaction_id>/done", methods=["POST"])
    def followup_done(interaction_id):
        db.mark_followup_done(interaction_id)
        flash("Follow-up splnen!", "success")
        next_url = request.form.get("next", url_for("followups"))
        return redirect(next_url)

    # --- Generosity ---

    @app.route("/contact/<int:contact_id>/give", methods=["POST"])
    def give_add(contact_id):
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
    def goal_add(contact_id):
        db.add_goal(
            contact_id=contact_id,
            goal=request.form["goal"],
            target_date=request.form.get("target_date") or None,
        )
        flash("Cil pridan!", "success")
        return redirect(url_for("contact_detail", contact_id=contact_id))

    @app.route("/goal/<int:goal_id>/done", methods=["POST"])
    def goal_done(goal_id):
        db.complete_goal(goal_id)
        flash("Cil splnen!", "success")
        return redirect(request.form.get("next", url_for("dashboard")))

    # --- Goals overview ---

    @app.route("/goals")
    def goals():
        show_all = request.args.get("all") == "1"
        goal_list = db.get_goals(pending_only=not show_all)
        return render_template("goals.html", goals=goal_list, show_all=show_all)

    # --- Tips ---

    @app.route("/tips")
    def tips():
        return render_template("tips.html")

    return app
