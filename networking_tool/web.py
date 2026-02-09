"""
Flask web application for GiveFirst.
Based on "Never Eat Alone" by Keith Ferrazzi.
"""

import os
import secrets
import functools
from datetime import datetime, timedelta
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, jsonify
from flask_wtf.csrf import CSRFProtect

from . import database as db

csrf = CSRFProtect()


def safe_redirect(next_url, default="dashboard"):
    """Only allow redirects to local paths (prevent open redirect)."""
    if not next_url:
        return redirect(url_for(default))
    parsed = urlparse(next_url)
    if parsed.netloc or parsed.scheme:
        return redirect(url_for(default))
    return redirect(next_url)

CIRCLE_LABELS = {
    "inner_circle": "Vnitřní kruh",
    "close": "Blízcí",
    "acquaintance": "Známí",
    "dormant": "Spící kontakty",
}

INTERACTION_TYPES = {
    "meal": "Jídlo",
    "coffee": "Káva",
    "call": "Hovor",
    "email": "E-mail",
    "event": "Akce",
    "intro": "Představení",
    "other": "Jiné",
}

GENEROSITY_CATEGORIES = {
    "intro": "Představení",
    "advice": "Rada",
    "resource": "Zdroj/informace",
    "help": "Pomoc",
    "gift": "Dárek",
    "referral": "Doporučení",
}

INTRO_STATUSES = {
    "planned": "Plánované",
    "made": "Provedené",
    "successful": "Úspěšné",
    "no_result": "Bez výsledku",
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

    # SECRET_KEY: require from environment in production
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        secret = secrets.token_hex(32)
        import sys
        print("WARNING: SECRET_KEY not set! Generated random key. Set SECRET_KEY env var for persistent sessions.", file=sys.stderr)
    app.secret_key = secret

    csrf.init_app(app)

    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        db.DATABASE_URL = database_url
    db.init_db()

    @app.before_request
    def load_user():
        user_id = session.get("user_id")
        g.user = db.get_user(user_id) if user_id else None
        if g.user:
            g.unread_notifications = db.get_unread_notification_count(g.user["id"])
            db.generate_notifications(g.user["id"])
        else:
            g.unread_notifications = 0

    @app.template_filter("circle_label")
    def circle_label(value):
        return CIRCLE_LABELS.get(value, value)

    @app.template_filter("interaction_label")
    def interaction_label(value):
        return INTERACTION_TYPES.get(value, value)

    @app.template_filter("generosity_label")
    def generosity_label(value):
        return GENEROSITY_CATEGORIES.get(value, value)

    @app.template_filter("intro_status_label")
    def intro_status_label(value):
        return INTRO_STATUSES.get(value, value)

    @app.template_filter("health_color")
    def health_color(score):
        if score >= 80:
            return "var(--success)"
        elif score >= 50:
            return "var(--warning)"
        elif score >= 25:
            return "#f97316"
        return "var(--danger)"

    @app.template_filter("trend_arrow")
    def trend_arrow(trend):
        return {"up": "↑", "down": "↓", "stable": "→"}.get(trend, "→")

    @app.context_processor
    def inject_globals():
        return {
            "circle_labels": CIRCLE_LABELS,
            "interaction_types": INTERACTION_TYPES,
            "generosity_categories": GENEROSITY_CATEGORIES,
            "intro_statuses": INTRO_STATUSES,
            "today": datetime.now().strftime("%Y-%m-%d"),
            "current_user": g.user,
            "unread_notifications": g.unread_notifications,
        }

    # ========== Auth ==========

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
                flash("Vyplňte uživatelské jméno a heslo.", "error")
                return render_template("register.html")
            if len(password) < 6:
                flash("Heslo musí mít alespoň 6 znaků.", "error")
                return render_template("register.html")
            if password != password2:
                flash("Hesla se neshodují.", "error")
                return render_template("register.html")

            user_id = db.create_user(username, password, display_name=display_name)
            if not user_id:
                flash("Uživatelské jméno již existuje.", "error")
                return render_template("register.html")

            session["user_id"] = user_id
            flash("Registrace úspěšná! Vítej v GiveFirst.", "success")
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
                flash("Špatné uživatelské jméno nebo heslo.", "error")
                return render_template("login.html")
            session["user_id"] = user["id"]
            flash(f"Vítej zpět, {user['display_name'] or user['username']}!", "success")
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("Odhlášení úspěšné.", "success")
        return redirect(url_for("login"))

    # ========== Dashboard ==========

    @app.route("/")
    @login_required
    def dashboard():
        uid = g.user["id"]
        stats = db.get_stats(uid)
        followups = db.get_pending_followups(uid)
        agenda = db.get_agenda_items(uid)
        progress = db.get_weekly_progress(uid)
        return render_template("dashboard.html", stats=stats, followups=followups,
                               agenda=agenda[:5], progress=progress)

    # ========== Contacts ==========

    @app.route("/contacts")
    @login_required
    def contacts():
        uid = g.user["id"]
        circle = request.args.get("circle")
        query = request.args.get("q")
        tag = request.args.get("tag")
        sort = request.args.get("sort", "name")
        if query:
            contact_list = db.search_contacts(uid, query)
        else:
            contact_list = db.list_contacts(uid, circle, tag=tag, sort=sort)

        # Add health scores and tags to contacts
        for c in contact_list:
            hs = db.calculate_health_score(c, uid)
            c["health_score"] = hs["total"]
            c["tags"] = db.get_contact_tags(c["id"])

        # Sort by health_score in Python if requested
        if sort == "health_score":
            contact_list.sort(key=lambda x: x["health_score"])

        all_tags = db.get_all_tags(uid)
        return render_template("contacts.html", contacts=contact_list,
                               current_circle=circle, query=query,
                               current_tag=tag, current_sort=sort,
                               all_tags=all_tags)

    @app.route("/contact/new", methods=["GET", "POST"])
    @login_required
    def contact_new():
        uid = g.user["id"]
        if request.method == "POST":
            intro_by = request.form.get("introduced_by_contact_id")
            freq = request.form.get("contact_frequency_days")
            contact_id = db.add_contact(
                user_id=uid,
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
                linkedin_url=request.form.get("linkedin_url") or None,
                instagram=request.form.get("instagram") or None,
                twitter=request.form.get("twitter") or None,
                facebook_url=request.form.get("facebook_url") or None,
                birthday=request.form.get("birthday") or None,
                personal_details=request.form.get("personal_details") or None,
                introduced_by_contact_id=int(intro_by) if intro_by else None,
                introduced_by_text=request.form.get("introduced_by_text") or None,
                contact_frequency_days=int(freq) if freq else None,
            )
            # Tags
            tags_str = request.form.get("tags", "")
            if tags_str.strip():
                db.set_contact_tags(uid, contact_id, [t.strip() for t in tags_str.split(",") if t.strip()])
            flash("Kontakt přidán!", "success")
            return redirect(url_for("contact_detail", contact_id=contact_id))
        all_contacts = db.list_contacts(uid)
        return render_template("contact_form.html", contact=None, all_contacts=all_contacts)

    @app.route("/contact/<int:contact_id>")
    @login_required
    def contact_detail(contact_id):
        uid = g.user["id"]
        contact = db.get_contact(contact_id, uid)
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))
        interactions = db.get_interactions(contact_id, limit=20)
        generosity = db.get_generosity(contact_id)
        goals_list = db.get_goals(uid, contact_id)
        tags = db.get_contact_tags(contact_id)
        starters = db.get_conversation_starters(contact_id)
        intros = db.get_introductions(uid, contact_id=contact_id)
        health = db.calculate_health_score(contact, uid)
        trend = db.get_health_trend(contact_id, health["total"])
        db.save_health_score_snapshot(contact_id, health["total"])

        # Get introducer name
        introducer_name = None
        if contact.get("introduced_by_contact_id"):
            introducer = db.get_contact(contact["introduced_by_contact_id"], uid)
            if introducer:
                introducer_name = introducer["name"]

        # Check birthday proximity
        birthday_soon = False
        if contact.get("birthday"):
            today_mmdd = datetime.now().strftime("%m-%d")
            week_mmdd = (datetime.now() + timedelta(days=7)).strftime("%m-%d")
            bday_mmdd = contact["birthday"][-5:]
            birthday_soon = today_mmdd <= bday_mmdd <= week_mmdd

        all_contacts = db.list_contacts(uid)
        return render_template("contact_detail.html", contact=contact,
                               interactions=interactions, generosity=generosity,
                               goals=goals_list, tags=tags, starters=starters,
                               intros=intros, health=health, trend=trend,
                               introducer_name=introducer_name,
                               birthday_soon=birthday_soon,
                               all_contacts=all_contacts)

    @app.route("/contact/<int:contact_id>/edit", methods=["GET", "POST"])
    @login_required
    def contact_edit(contact_id):
        uid = g.user["id"]
        contact = db.get_contact(contact_id, uid)
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))
        if request.method == "POST":
            intro_by = request.form.get("introduced_by_contact_id")
            freq = request.form.get("contact_frequency_days")
            db.update_contact(
                contact_id, uid,
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
                linkedin_url=request.form.get("linkedin_url") or None,
                instagram=request.form.get("instagram") or None,
                twitter=request.form.get("twitter") or None,
                facebook_url=request.form.get("facebook_url") or None,
                birthday=request.form.get("birthday") or None,
                personal_details=request.form.get("personal_details") or None,
                introduced_by_contact_id=int(intro_by) if intro_by else None,
                introduced_by_text=request.form.get("introduced_by_text") or None,
                contact_frequency_days=int(freq) if freq else None,
            )
            tags_str = request.form.get("tags", "")
            db.set_contact_tags(uid, contact_id, [t.strip() for t in tags_str.split(",") if t.strip()])
            flash("Kontakt aktualizován!", "success")
            return redirect(url_for("contact_detail", contact_id=contact_id))
        tags = db.get_contact_tags(contact_id)
        contact["tags_str"] = ", ".join(t["name"] for t in tags)
        all_contacts = db.list_contacts(uid)
        return render_template("contact_form.html", contact=contact, all_contacts=all_contacts)

    @app.route("/contact/<int:contact_id>/delete", methods=["POST"])
    @login_required
    def contact_delete(contact_id):
        contact = db.get_contact(contact_id, g.user["id"])
        if contact:
            db.delete_contact(contact_id, g.user["id"])
            flash(f"Kontakt '{contact['name']}' smazán.", "success")
        return redirect(url_for("contacts"))

    @app.route("/contacts/bulk", methods=["POST"])
    @login_required
    def contacts_bulk():
        uid = g.user["id"]
        action = request.form.get("action")
        ids = request.form.getlist("contact_ids")
        contact_ids = [int(i) for i in ids if i.isdigit()]
        if not contact_ids:
            flash("Nebyl vybrán žádný kontakt.", "error")
            return redirect(url_for("contacts"))
        if action == "move_circle":
            circle = request.form.get("bulk_circle")
            if circle in CIRCLE_LABELS:
                db.bulk_move_circle(uid, contact_ids, circle)
                flash(f"{len(contact_ids)} kontaktů přesunuto do kruhu '{CIRCLE_LABELS[circle]}'.", "success")
        elif action == "add_tag":
            tag = request.form.get("bulk_tag", "").strip()
            if tag:
                db.bulk_add_tag(uid, contact_ids, tag)
                flash(f"Tag '{tag}' přidán k {len(contact_ids)} kontaktům.", "success")
        elif action == "delete":
            db.bulk_delete_contacts(uid, contact_ids)
            flash(f"{len(contact_ids)} kontaktů smazáno.", "success")
        return redirect(url_for("contacts"))

    # ========== Interactions ==========

    @app.route("/contact/<int:contact_id>/interaction", methods=["POST"])
    @login_required
    def interaction_add(contact_id):
        uid = g.user["id"]
        contact = db.get_contact(contact_id, uid)
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))

        follow_up = "follow_up" in request.form
        follow_up_by = request.form.get("follow_up_by") or None
        if follow_up and not follow_up_by:
            follow_up_by = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        # Additional contacts (group interaction)
        additional_ids = request.form.getlist("additional_contacts")
        additional = [int(i) for i in additional_ids if i.isdigit()] if additional_ids else None

        conversation_starter = request.form.get("conversation_starter") or None

        db.add_interaction(
            contact_id=contact_id,
            interaction_type=request.form["type"],
            description=request.form.get("description") or None,
            date=request.form.get("date") or None,
            follow_up_needed=follow_up,
            follow_up_by=follow_up_by,
            additional_contact_ids=additional,
            conversation_starter=conversation_starter,
        )
        flash("Interakce zaznamenána!", "success")
        return safe_redirect(request.form.get("next"), "contacts")

    @app.route("/api/quick-log", methods=["POST"])
    @login_required
    def quick_log():
        uid = g.user["id"]
        contact_id = request.form.get("contact_id")
        if not contact_id:
            flash("Vyber kontakt.", "error")
            return safe_redirect(request.form.get("next"), "contacts")
        contact = db.get_contact(int(contact_id), uid)
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return safe_redirect(request.form.get("next"), "contacts")

        follow_up = "follow_up" in request.form
        follow_up_by = None
        if follow_up:
            follow_up_by = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        db.add_interaction(
            contact_id=int(contact_id),
            interaction_type=request.form.get("type", "other"),
            description=request.form.get("description") or None,
            follow_up_needed=follow_up,
            follow_up_by=follow_up_by,
        )
        flash(f"Interakce s {contact['name']} zaznamenána!", "success")
        return safe_redirect(request.form.get("next"), "contacts")

    @app.route("/api/contacts/search")
    @login_required
    def api_contacts_search():
        q = request.args.get("q", "")
        if len(q) < 1:
            return jsonify([])
        results = db.search_contacts_simple(g.user["id"], q)
        return jsonify(results)

    # ========== Follow-ups ==========

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
        flash("Follow-up vyřízen!", "success")
        return safe_redirect(request.form.get("next"), "followups")

    # ========== Generosity ==========

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
        flash("Dobrý skutek zaznamenán!", "success")
        return redirect(url_for("contact_detail", contact_id=contact_id))

    # ========== Goals ==========

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
        flash("Cíl přidán!", "success")
        return redirect(url_for("contact_detail", contact_id=contact_id))

    @app.route("/goal/<int:goal_id>/done", methods=["POST"])
    @login_required
    def goal_done(goal_id):
        db.complete_goal(goal_id, g.user["id"])
        flash("Cíl splněn!", "success")
        return safe_redirect(request.form.get("next"), "dashboard")

    @app.route("/goals")
    @login_required
    def goals():
        show_all = request.args.get("all") == "1"
        goal_list = db.get_goals(g.user["id"], pending_only=not show_all)
        return render_template("goals.html", goals=goal_list, show_all=show_all)

    # ========== Conversation Starters ==========

    @app.route("/contact/<int:contact_id>/starter", methods=["POST"])
    @login_required
    def starter_add(contact_id):
        contact = db.get_contact(contact_id, g.user["id"])
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))
        content = request.form.get("content", "").strip()
        if content:
            db.add_conversation_starter(contact_id, content)
            flash("Téma přidáno!", "success")
        return redirect(url_for("contact_detail", contact_id=contact_id))

    @app.route("/starter/<int:starter_id>/deactivate", methods=["POST"])
    @login_required
    def starter_deactivate(starter_id):
        db.deactivate_conversation_starter(starter_id, g.user["id"])
        return safe_redirect(request.form.get("next"), "dashboard")

    # ========== Introductions ==========

    @app.route("/introductions")
    @login_required
    def introductions():
        uid = g.user["id"]
        status = request.args.get("status")
        intro_list = db.get_introductions(uid, status=status)
        return render_template("introductions.html", introductions=intro_list,
                               current_status=status)

    @app.route("/contact/<int:contact_id>/introduction", methods=["POST"])
    @login_required
    def introduction_add(contact_id):
        uid = g.user["id"]
        contact = db.get_contact(contact_id, uid)
        if not contact:
            flash("Kontakt nenalezen.", "error")
            return redirect(url_for("contacts"))
        contact_b_id = request.form.get("contact_b_id")
        if not contact_b_id:
            flash("Vyber druhý kontakt.", "error")
            return redirect(url_for("contact_detail", contact_id=contact_id))
        db.add_introduction(
            user_id=uid,
            contact_a_id=contact_id,
            contact_b_id=int(contact_b_id),
            context=request.form.get("context") or None,
            date=request.form.get("date") or None,
            status=request.form.get("status", "made"),
        )
        flash("Propojení zaznamenáno!", "success")
        return redirect(url_for("contact_detail", contact_id=contact_id))

    @app.route("/introduction/<int:intro_id>/update", methods=["POST"])
    @login_required
    def introduction_update(intro_id):
        uid = g.user["id"]
        db.update_introduction(
            intro_id, uid,
            status=request.form.get("status"),
            outcome=request.form.get("outcome"),
        )
        flash("Propojení aktualizováno!", "success")
        return safe_redirect(request.form.get("next"), "introductions")

    # ========== Agenda ==========

    @app.route("/agenda")
    @login_required
    def agenda():
        uid = g.user["id"]
        items = db.get_agenda_items(uid)
        progress = db.get_weekly_progress(uid)
        return render_template("agenda.html", agenda=items, progress=progress)

    @app.route("/agenda/skip", methods=["POST"])
    @login_required
    def agenda_skip():
        uid = g.user["id"]
        item_type = request.form.get("item_type")
        item_id = request.form.get("item_id")
        if item_type and item_id:
            db.skip_agenda_item(uid, item_type, int(item_id))
            flash("Položka přeskočena do příštího týdne.", "success")
        return safe_redirect(request.form.get("next"), "agenda")

    # ========== Notifications ==========

    @app.route("/notifications")
    @login_required
    def notifications():
        uid = g.user["id"]
        notifs = db.get_notifications(uid)
        return render_template("notifications.html", notifications=notifs)

    @app.route("/notification/<int:notification_id>/read", methods=["POST"])
    @login_required
    def notification_read(notification_id):
        uid = g.user["id"]
        db.mark_notification_read(notification_id, uid)
        # Get the notification to redirect
        notifs = db.get_notifications(uid)
        for n in notifs:
            if n["id"] == notification_id and n.get("link"):
                return redirect(n["link"])
        return redirect(url_for("notifications"))

    @app.route("/notifications/read-all", methods=["POST"])
    @login_required
    def notifications_read_all():
        db.mark_all_notifications_read(g.user["id"])
        flash("Všechny notifikace označeny jako přečtené.", "success")
        return safe_redirect(request.form.get("next"), "dashboard")

    @app.route("/api/notifications")
    @login_required
    def api_notifications():
        uid = g.user["id"]
        notifs = db.get_notifications(uid, unread_only=True, limit=10)
        return jsonify(notifs)

    # ========== Settings ==========

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        uid = g.user["id"]
        if request.method == "POST":
            for key in ["freq_inner_circle", "freq_close", "freq_acquaintance", "weekly_goal"]:
                val = request.form.get(key, "").strip()
                if val and val.isdigit():
                    db.set_user_setting(uid, key, val)
            flash("Nastavení uloženo!", "success")
            return redirect(url_for("settings"))

        current = db.get_all_user_settings(uid)
        defaults = {
            "freq_inner_circle": "14",
            "freq_close": "30",
            "freq_acquaintance": "90",
            "weekly_goal": "5",
        }
        for k, v in defaults.items():
            if k not in current:
                current[k] = v
        return render_template("settings.html", settings=current)

    # ========== Tips ==========

    @app.route("/tips")
    @login_required
    def tips():
        return render_template("tips.html")

    return app
