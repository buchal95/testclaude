"""
Database layer for the Networking Tool.
Uses SQLite for persistent storage of contacts, interactions, goals, and generosity acts.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = os.path.join(Path.home(), ".networking_tool.db")


def get_connection(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            company TEXT,
            role TEXT,
            circle TEXT NOT NULL DEFAULT 'acquaintance',
            -- circle: inner_circle, close, acquaintance, dormant
            notes TEXT,
            how_we_met TEXT,
            interests TEXT,
            goals TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            -- type: meal, coffee, call, email, event, intro, other
            description TEXT,
            date TEXT NOT NULL DEFAULT (date('now')),
            follow_up_needed INTEGER NOT NULL DEFAULT 0,
            follow_up_done INTEGER NOT NULL DEFAULT 0,
            follow_up_by TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS generosity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            category TEXT,
            -- category: intro, advice, resource, help, gift, referral
            date TEXT NOT NULL DEFAULT (date('now')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS relationship_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL,
            goal TEXT NOT NULL,
            target_date TEXT,
            completed INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
        );
    """)

    conn.commit()
    conn.close()


# --- Contacts ---

def add_contact(name, email=None, phone=None, company=None, role=None,
                circle="acquaintance", notes=None, how_we_met=None,
                interests=None, goals=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO contacts (name, email, phone, company, role, circle, notes,
                              how_we_met, interests, goals)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, email, phone, company, role, circle, notes, how_we_met,
          interests, goals))
    contact_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return contact_id


def get_contact(contact_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def search_contacts(query):
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM contacts
        WHERE name LIKE ? OR company LIKE ? OR email LIKE ? OR notes LIKE ?
        ORDER BY name
    """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_contacts(circle=None):
    conn = get_connection()
    if circle:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE circle = ? ORDER BY name",
            (circle,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM contacts ORDER BY circle, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_contact(contact_id, **fields):
    if not fields:
        return
    allowed = {"name", "email", "phone", "company", "role", "circle",
               "notes", "how_we_met", "interests", "goals"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not fields:
        return
    fields["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [contact_id]
    conn = get_connection()
    conn.execute(f"UPDATE contacts SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_contact(contact_id):
    conn = get_connection()
    conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    conn.commit()
    conn.close()


# --- Interactions ---

def add_interaction(contact_id, interaction_type, description=None, date=None,
                    follow_up_needed=False, follow_up_by=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO interactions (contact_id, type, description, date,
                                  follow_up_needed, follow_up_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (contact_id, interaction_type, description,
          date or datetime.now().strftime("%Y-%m-%d"),
          1 if follow_up_needed else 0, follow_up_by))
    interaction_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return interaction_id


def get_interactions(contact_id, limit=10):
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM interactions WHERE contact_id = ?
        ORDER BY date DESC LIMIT ?
    """, (contact_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_followups():
    conn = get_connection()
    rows = conn.execute("""
        SELECT i.*, c.name as contact_name, c.circle
        FROM interactions i
        JOIN contacts c ON i.contact_id = c.id
        WHERE i.follow_up_needed = 1 AND i.follow_up_done = 0
        ORDER BY i.follow_up_by ASC, i.date ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_followup_done(interaction_id):
    conn = get_connection()
    conn.execute(
        "UPDATE interactions SET follow_up_done = 1 WHERE id = ?",
        (interaction_id,)
    )
    conn.commit()
    conn.close()


# --- Generosity ---

def add_generosity(contact_id, description, category=None, date=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO generosity (contact_id, description, category, date)
        VALUES (?, ?, ?, ?)
    """, (contact_id, description, category,
          date or datetime.now().strftime("%Y-%m-%d")))
    gen_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return gen_id


def get_generosity(contact_id):
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM generosity WHERE contact_id = ?
        ORDER BY date DESC
    """, (contact_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Relationship Goals ---

def add_goal(contact_id, goal, target_date=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO relationship_goals (contact_id, goal, target_date)
        VALUES (?, ?, ?)
    """, (contact_id, goal, target_date))
    goal_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return goal_id


def complete_goal(goal_id):
    conn = get_connection()
    conn.execute("""
        UPDATE relationship_goals
        SET completed = 1, completed_at = datetime('now')
        WHERE id = ?
    """, (goal_id,))
    conn.commit()
    conn.close()


def get_goals(contact_id=None, pending_only=False):
    conn = get_connection()
    query = """
        SELECT g.*, c.name as contact_name
        FROM relationship_goals g
        JOIN contacts c ON g.contact_id = c.id
    """
    conditions = []
    params = []
    if contact_id:
        conditions.append("g.contact_id = ?")
        params.append(contact_id)
    if pending_only:
        conditions.append("g.completed = 0")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY g.target_date ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Dashboard Stats ---

def get_stats():
    conn = get_connection()
    stats = {}

    # Contact counts by circle
    rows = conn.execute("""
        SELECT circle, COUNT(*) as count FROM contacts GROUP BY circle
    """).fetchall()
    stats["circles"] = {r["circle"]: r["count"] for r in rows}
    stats["total_contacts"] = sum(stats["circles"].values())

    # Interactions this week
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT COUNT(*) as count FROM interactions WHERE date >= ?
    """, (week_ago,)).fetchone()
    stats["interactions_this_week"] = row["count"]

    # Interactions this month
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT COUNT(*) as count FROM interactions WHERE date >= ?
    """, (month_ago,)).fetchone()
    stats["interactions_this_month"] = row["count"]

    # Pending follow-ups
    row = conn.execute("""
        SELECT COUNT(*) as count FROM interactions
        WHERE follow_up_needed = 1 AND follow_up_done = 0
    """).fetchone()
    stats["pending_followups"] = row["count"]

    # Overdue follow-ups
    today = datetime.now().strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT COUNT(*) as count FROM interactions
        WHERE follow_up_needed = 1 AND follow_up_done = 0
        AND follow_up_by IS NOT NULL AND follow_up_by < ?
    """, (today,)).fetchone()
    stats["overdue_followups"] = row["count"]

    # Generosity acts this month
    row = conn.execute("""
        SELECT COUNT(*) as count FROM generosity WHERE date >= ?
    """, (month_ago,)).fetchone()
    stats["generosity_this_month"] = row["count"]

    # Pending goals
    row = conn.execute("""
        SELECT COUNT(*) as count FROM relationship_goals WHERE completed = 0
    """).fetchone()
    stats["pending_goals"] = row["count"]

    # Dormant contacts (no interaction in 90+ days)
    ninety_ago = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT c.id, c.name, c.circle, MAX(i.date) as last_interaction
        FROM contacts c
        LEFT JOIN interactions i ON c.id = i.contact_id
        GROUP BY c.id
        HAVING last_interaction IS NULL OR last_interaction < ?
        ORDER BY last_interaction ASC
        LIMIT 10
    """, (ninety_ago,)).fetchall()
    stats["dormant_contacts"] = [dict(r) for r in rows]

    conn.close()
    return stats
