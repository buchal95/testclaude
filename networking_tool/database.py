"""
Database layer for GiveFirst.
Uses PostgreSQL for persistent storage of users, contacts, interactions, goals, and generosity acts.
"""

import os
from datetime import datetime, timedelta
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash


DATABASE_URL = os.environ.get("DATABASE_URL", "")


@contextmanager
def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fetchone(cur):
    row = cur.fetchone()
    return dict(row) if row else None


def _fetchall(cur):
    return [dict(r) for r in cur.fetchall()]


def init_db():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                company TEXT,
                role TEXT,
                circle TEXT NOT NULL DEFAULT 'acquaintance',
                notes TEXT,
                how_we_met TEXT,
                interests TEXT,
                goals TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS interactions (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                description TEXT,
                date DATE NOT NULL DEFAULT CURRENT_DATE,
                follow_up_needed BOOLEAN NOT NULL DEFAULT FALSE,
                follow_up_done BOOLEAN NOT NULL DEFAULT FALSE,
                follow_up_by DATE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS generosity (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                description TEXT NOT NULL,
                category TEXT,
                date DATE NOT NULL DEFAULT CURRENT_DATE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS relationship_goals (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                goal TEXT NOT NULL,
                target_date DATE,
                completed BOOLEAN NOT NULL DEFAULT FALSE,
                completed_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
        """)


# --- Users ---

def create_user(username, password, email=None, display_name=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("""
                INSERT INTO users (username, password_hash, email, display_name)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (username, generate_password_hash(password), email, display_name))
            return cur.fetchone()["id"]
        except psycopg2.errors.UniqueViolation:
            return None


def authenticate_user(username, password):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = _fetchone(cur)
        if row and check_password_hash(row["password_hash"], password):
            return row
        return None


def get_user(user_id):
    if not user_id:
        return None
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return _fetchone(cur)


# --- Contacts ---

def add_contact(user_id, name, email=None, phone=None, company=None, role=None,
                circle="acquaintance", notes=None, how_we_met=None,
                interests=None, goals=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO contacts (user_id, name, email, phone, company, role, circle, notes,
                                  how_we_met, interests, goals)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, name, email, phone, company, role, circle, notes, how_we_met,
              interests, goals))
        return cur.fetchone()["id"]


def get_contact(contact_id, user_id):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM contacts WHERE id = %s AND user_id = %s",
            (contact_id, user_id)
        )
        return _fetchone(cur)


def search_contacts(user_id, query):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        q = f"%{query}%"
        cur.execute("""
            SELECT * FROM contacts
            WHERE user_id = %s AND (name ILIKE %s OR company ILIKE %s OR email ILIKE %s OR notes ILIKE %s)
            ORDER BY name
        """, (user_id, q, q, q, q))
        return _fetchall(cur)


def list_contacts(user_id, circle=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if circle:
            cur.execute(
                "SELECT * FROM contacts WHERE user_id = %s AND circle = %s ORDER BY name",
                (user_id, circle)
            )
        else:
            cur.execute(
                "SELECT * FROM contacts WHERE user_id = %s ORDER BY circle, name",
                (user_id,)
            )
        return _fetchall(cur)


def update_contact(contact_id, user_id, **fields):
    if not fields:
        return
    allowed = {"name", "email", "phone", "company", "role", "circle",
               "notes", "how_we_met", "interests", "goals"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not fields:
        return
    fields["updated_at"] = datetime.now()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [contact_id, user_id]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE contacts SET {set_clause} WHERE id = %s AND user_id = %s", values)


def delete_contact(contact_id, user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM contacts WHERE id = %s AND user_id = %s", (contact_id, user_id))


# --- Interactions ---

def add_interaction(contact_id, interaction_type, description=None, date=None,
                    follow_up_needed=False, follow_up_by=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO interactions (contact_id, type, description, date,
                                      follow_up_needed, follow_up_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (contact_id, interaction_type, description,
              date or datetime.now().strftime("%Y-%m-%d"),
              follow_up_needed, follow_up_by))
        return cur.fetchone()["id"]


def get_interactions(contact_id, limit=10):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM interactions WHERE contact_id = %s
            ORDER BY date DESC LIMIT %s
        """, (contact_id, limit))
        return _fetchall(cur)


def get_pending_followups(user_id):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT i.*, c.name as contact_name, c.circle
            FROM interactions i
            JOIN contacts c ON i.contact_id = c.id
            WHERE c.user_id = %s AND i.follow_up_needed = TRUE AND i.follow_up_done = FALSE
            ORDER BY i.follow_up_by ASC NULLS LAST, i.date ASC
        """, (user_id,))
        return _fetchall(cur)


def mark_followup_done(interaction_id, user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE interactions SET follow_up_done = TRUE
            WHERE id = %s AND contact_id IN (SELECT id FROM contacts WHERE user_id = %s)
        """, (interaction_id, user_id))


# --- Generosity ---

def add_generosity(contact_id, description, category=None, date=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO generosity (contact_id, description, category, date)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (contact_id, description, category,
              date or datetime.now().strftime("%Y-%m-%d")))
        return cur.fetchone()["id"]


def get_generosity(contact_id):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM generosity WHERE contact_id = %s
            ORDER BY date DESC
        """, (contact_id,))
        return _fetchall(cur)


# --- Relationship Goals ---

def add_goal(contact_id, goal, target_date=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO relationship_goals (contact_id, goal, target_date)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (contact_id, goal, target_date))
        return cur.fetchone()["id"]


def complete_goal(goal_id, user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE relationship_goals
            SET completed = TRUE, completed_at = NOW()
            WHERE id = %s AND contact_id IN (SELECT id FROM contacts WHERE user_id = %s)
        """, (goal_id, user_id))


def get_goals(user_id, contact_id=None, pending_only=False):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query = """
            SELECT g.*, c.name as contact_name
            FROM relationship_goals g
            JOIN contacts c ON g.contact_id = c.id
            WHERE c.user_id = %s
        """
        params = [user_id]
        if contact_id:
            query += " AND g.contact_id = %s"
            params.append(contact_id)
        if pending_only:
            query += " AND g.completed = FALSE"
        query += " ORDER BY g.target_date ASC NULLS LAST"
        cur.execute(query, params)
        return _fetchall(cur)


# --- Dashboard Stats ---

def get_stats(user_id):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        stats = {}

        cur.execute("""
            SELECT circle, COUNT(*) as count FROM contacts WHERE user_id = %s GROUP BY circle
        """, (user_id,))
        rows = _fetchall(cur)
        stats["circles"] = {r["circle"]: r["count"] for r in rows}
        stats["total_contacts"] = sum(stats["circles"].values())

        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT COUNT(*) as count FROM interactions i
            JOIN contacts c ON i.contact_id = c.id
            WHERE c.user_id = %s AND i.date >= %s
        """, (user_id, week_ago))
        stats["interactions_this_week"] = _fetchone(cur)["count"]

        month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT COUNT(*) as count FROM interactions i
            JOIN contacts c ON i.contact_id = c.id
            WHERE c.user_id = %s AND i.date >= %s
        """, (user_id, month_ago))
        stats["interactions_this_month"] = _fetchone(cur)["count"]

        cur.execute("""
            SELECT COUNT(*) as count FROM interactions i
            JOIN contacts c ON i.contact_id = c.id
            WHERE c.user_id = %s AND i.follow_up_needed = TRUE AND i.follow_up_done = FALSE
        """, (user_id,))
        stats["pending_followups"] = _fetchone(cur)["count"]

        today = datetime.now().strftime("%Y-%m-%d")
        cur.execute("""
            SELECT COUNT(*) as count FROM interactions i
            JOIN contacts c ON i.contact_id = c.id
            WHERE c.user_id = %s AND i.follow_up_needed = TRUE AND i.follow_up_done = FALSE
            AND i.follow_up_by IS NOT NULL AND i.follow_up_by < %s
        """, (user_id, today))
        stats["overdue_followups"] = _fetchone(cur)["count"]

        cur.execute("""
            SELECT COUNT(*) as count FROM generosity g
            JOIN contacts c ON g.contact_id = c.id
            WHERE c.user_id = %s AND g.date >= %s
        """, (user_id, month_ago))
        stats["generosity_this_month"] = _fetchone(cur)["count"]

        cur.execute("""
            SELECT COUNT(*) as count FROM relationship_goals g
            JOIN contacts c ON g.contact_id = c.id
            WHERE c.user_id = %s AND g.completed = FALSE
        """, (user_id,))
        stats["pending_goals"] = _fetchone(cur)["count"]

        ninety_ago = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT c.id, c.name, c.circle, MAX(i.date) as last_interaction
            FROM contacts c
            LEFT JOIN interactions i ON c.id = i.contact_id
            WHERE c.user_id = %s
            GROUP BY c.id, c.name, c.circle
            HAVING MAX(i.date) IS NULL OR MAX(i.date) < %s
            ORDER BY MAX(i.date) ASC NULLS FIRST
            LIMIT 10
        """, (user_id, ninety_ago))
        stats["dormant_contacts"] = _fetchall(cur)

        return stats
