"""
Database layer for GiveFirst.
Uses PostgreSQL for persistent storage.
"""

import os
from datetime import datetime, timedelta
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash


DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Default circle frequencies (days)
DEFAULT_FREQUENCIES = {
    "inner_circle": {"ideal": 14, "warning": 21, "critical": 30},
    "close": {"ideal": 30, "warning": 45, "critical": 60},
    "acquaintance": {"ideal": 90, "warning": 120, "critical": 180},
    "dormant": {"ideal": 0, "warning": 0, "critical": 0},
}


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

        # Core tables
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

            -- Tags
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS contact_tags (
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (contact_id, tag_id)
            );

            -- Health score history
            CREATE TABLE IF NOT EXISTS health_score_history (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                score INTEGER NOT NULL,
                calculated_at DATE NOT NULL DEFAULT CURRENT_DATE
            );

            -- Conversation starters
            CREATE TABLE IF NOT EXISTS conversation_starters (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                source_interaction_id INTEGER REFERENCES interactions(id) ON DELETE SET NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            -- Introductions
            CREATE TABLE IF NOT EXISTS introductions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                contact_a_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                contact_b_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                date DATE NOT NULL DEFAULT CURRENT_DATE,
                context TEXT,
                outcome TEXT,
                status TEXT NOT NULL DEFAULT 'made',
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            -- Group interactions
            CREATE TABLE IF NOT EXISTS interaction_contacts (
                interaction_id INTEGER NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
                contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                PRIMARY KEY (interaction_id, contact_id)
            );

            -- Notifications
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT,
                link TEXT,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                related_id INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            );

            -- User settings
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                setting_key TEXT NOT NULL,
                setting_value TEXT NOT NULL,
                PRIMARY KEY (user_id, setting_key)
            );

            -- Agenda skips
            CREATE TABLE IF NOT EXISTS agenda_skips (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                item_type TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                skipped_until DATE NOT NULL
            );
        """)

        # Migrate: add new columns to contacts
        new_cols = [
            ("linkedin_url", "TEXT"),
            ("instagram", "TEXT"),
            ("twitter", "TEXT"),
            ("facebook_url", "TEXT"),
            ("birthday", "TEXT"),
            ("personal_details", "TEXT"),
            ("introduced_by_contact_id", "INTEGER REFERENCES contacts(id) ON DELETE SET NULL"),
            ("introduced_by_text", "TEXT"),
            ("contact_frequency_days", "INTEGER"),
        ]
        for col, typ in new_cols:
            cur.execute(f"""
                DO $$ BEGIN
                    ALTER TABLE contacts ADD COLUMN {col} {typ};
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            """)

        # Migrate existing interactions into interaction_contacts
        cur.execute("""
            INSERT INTO interaction_contacts (interaction_id, contact_id)
            SELECT id, contact_id FROM interactions
            WHERE id NOT IN (SELECT interaction_id FROM interaction_contacts)
        """)


# ===================== Users =====================

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


# ===================== User Settings =====================

def get_user_setting(user_id, key, default=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT setting_value FROM user_settings WHERE user_id = %s AND setting_key = %s",
            (user_id, key)
        )
        row = _fetchone(cur)
        return row["setting_value"] if row else default


def set_user_setting(user_id, key, value):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_settings (user_id, setting_key, setting_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, setting_key)
            DO UPDATE SET setting_value = EXCLUDED.setting_value
        """, (user_id, key, str(value)))


def get_all_user_settings(user_id):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT setting_key, setting_value FROM user_settings WHERE user_id = %s", (user_id,))
        return {r["setting_key"]: r["setting_value"] for r in cur.fetchall()}


def get_circle_frequency(user_id, circle):
    """Get frequency settings for a circle, respecting user overrides."""
    defaults = DEFAULT_FREQUENCIES.get(circle, DEFAULT_FREQUENCIES["acquaintance"])
    ideal = int(get_user_setting(user_id, f"freq_{circle}", defaults["ideal"]) or defaults["ideal"])
    warning_mult = 1.5
    critical_mult = 2.0
    return {
        "ideal": ideal,
        "warning": int(ideal * warning_mult),
        "critical": int(ideal * critical_mult),
    }


# ===================== Contacts =====================

CONTACT_FIELDS = {
    "name", "email", "phone", "company", "role", "circle",
    "notes", "how_we_met", "interests", "goals",
    "linkedin_url", "instagram", "twitter", "facebook_url",
    "birthday", "personal_details", "introduced_by_contact_id",
    "introduced_by_text", "contact_frequency_days",
}


def add_contact(user_id, name, email=None, phone=None, company=None, role=None,
                circle="acquaintance", notes=None, how_we_met=None,
                interests=None, goals=None, linkedin_url=None, instagram=None,
                twitter=None, facebook_url=None, birthday=None,
                personal_details=None, introduced_by_contact_id=None,
                introduced_by_text=None, contact_frequency_days=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO contacts (user_id, name, email, phone, company, role, circle, notes,
                                  how_we_met, interests, goals, linkedin_url, instagram,
                                  twitter, facebook_url, birthday, personal_details,
                                  introduced_by_contact_id, introduced_by_text,
                                  contact_frequency_days)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (user_id, name, email, phone, company, role, circle, notes, how_we_met,
              interests, goals, linkedin_url, instagram, twitter, facebook_url,
              birthday, personal_details, introduced_by_contact_id, introduced_by_text,
              contact_frequency_days))
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
            SELECT c.*, MAX(i.date) as last_interaction
            FROM contacts c
            LEFT JOIN interactions i ON c.id = i.contact_id
            WHERE c.user_id = %s AND (c.name ILIKE %s OR c.company ILIKE %s OR c.email ILIKE %s OR c.notes ILIKE %s)
            GROUP BY c.id
            ORDER BY c.name
        """, (user_id, q, q, q, q))
        return _fetchall(cur)


def list_contacts(user_id, circle=None, tag=None, sort="name"):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query = """
            SELECT c.*, MAX(i.date) as last_interaction
            FROM contacts c
            LEFT JOIN interactions i ON c.id = i.contact_id
        """
        params = [user_id]
        joins = ""
        where = "WHERE c.user_id = %s"

        if tag:
            joins += " JOIN contact_tags ct ON c.id = ct.contact_id JOIN tags t ON ct.tag_id = t.id"
            where += " AND t.name = %s AND t.user_id = %s"
            params.extend([tag, user_id])

        if circle:
            where += " AND c.circle = %s"
            params.append(circle)

        order_map = {
            "name": "c.name ASC",
            "last_interaction": "MAX(i.date) ASC NULLS FIRST",
            "health_score": "c.name ASC",  # sorted in Python after health calc
            "created": "c.created_at DESC",
        }
        order = order_map.get(sort, "c.name ASC")

        full_query = f"{query}{joins} {where} GROUP BY c.id ORDER BY {order}"
        cur.execute(full_query, params)
        return _fetchall(cur)


def search_contacts_simple(user_id, query, limit=10):
    """Lightweight search for autocomplete."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        q = f"%{query}%"
        cur.execute("""
            SELECT id, name, company, circle FROM contacts
            WHERE user_id = %s AND (name ILIKE %s OR company ILIKE %s)
            ORDER BY name LIMIT %s
        """, (user_id, q, q, limit))
        return _fetchall(cur)


def update_contact(contact_id, user_id, **fields):
    if not fields:
        return
    fields = {k: v for k, v in fields.items() if k in CONTACT_FIELDS}
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


def bulk_move_circle(user_id, contact_ids, circle):
    if not contact_ids:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE contacts SET circle = %s, updated_at = NOW() WHERE user_id = %s AND id = ANY(%s)",
            (circle, user_id, contact_ids)
        )


def bulk_delete_contacts(user_id, contact_ids):
    if not contact_ids:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM contacts WHERE user_id = %s AND id = ANY(%s)",
            (user_id, contact_ids)
        )


# ===================== Tags =====================

def get_or_create_tag(user_id, tag_name):
    tag_name = tag_name.strip().lower()
    if not tag_name:
        return None
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM tags WHERE user_id = %s AND name = %s", (user_id, tag_name))
        row = _fetchone(cur)
        if row:
            return row["id"]
        cur.execute("INSERT INTO tags (user_id, name) VALUES (%s, %s) RETURNING id", (user_id, tag_name))
        return cur.fetchone()["id"]


def set_contact_tags(user_id, contact_id, tag_names):
    """Replace all tags for a contact."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("DELETE FROM contact_tags WHERE contact_id = %s", (contact_id,))
        for name in tag_names:
            name = name.strip().lower()
            if not name:
                continue
            cur.execute("SELECT id FROM tags WHERE user_id = %s AND name = %s", (user_id, name))
            row = _fetchone(cur)
            if row:
                tag_id = row["id"]
            else:
                cur.execute("INSERT INTO tags (user_id, name) VALUES (%s, %s) RETURNING id", (user_id, name))
                tag_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO contact_tags (contact_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (contact_id, tag_id)
            )


def get_contact_tags(contact_id):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT t.id, t.name FROM tags t
            JOIN contact_tags ct ON t.id = ct.tag_id
            WHERE ct.contact_id = %s ORDER BY t.name
        """, (contact_id,))
        return _fetchall(cur)


def get_all_tags(user_id):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT t.id, t.name, COUNT(ct.contact_id) as contact_count
            FROM tags t LEFT JOIN contact_tags ct ON t.id = ct.tag_id
            WHERE t.user_id = %s GROUP BY t.id ORDER BY t.name
        """, (user_id,))
        return _fetchall(cur)


def bulk_add_tag(user_id, contact_ids, tag_name):
    if not contact_ids or not tag_name.strip():
        return
    tag_id = get_or_create_tag(user_id, tag_name)
    if not tag_id:
        return
    with get_connection() as conn:
        cur = conn.cursor()
        for cid in contact_ids:
            cur.execute(
                "INSERT INTO contact_tags (contact_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (cid, tag_id)
            )


# ===================== Interactions =====================

def add_interaction(contact_id, interaction_type, description=None, date=None,
                    follow_up_needed=False, follow_up_by=None,
                    additional_contact_ids=None, conversation_starter=None):
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
        interaction_id = cur.fetchone()["id"]

        # Add to junction table (primary contact)
        cur.execute(
            "INSERT INTO interaction_contacts (interaction_id, contact_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (interaction_id, contact_id)
        )

        # Add additional contacts (group interaction)
        if additional_contact_ids:
            for cid in additional_contact_ids:
                cur.execute(
                    "INSERT INTO interaction_contacts (interaction_id, contact_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (interaction_id, cid)
                )

        # Auto-create conversation starter
        if conversation_starter and conversation_starter.strip():
            cur.execute("""
                INSERT INTO conversation_starters (contact_id, content, source_interaction_id)
                VALUES (%s, %s, %s)
            """, (contact_id, conversation_starter.strip(), interaction_id))

        return interaction_id


def get_interactions(contact_id, limit=20):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT i.*,
                   array_agg(DISTINCT c2.name) FILTER (WHERE c2.id != i.contact_id) as other_participants
            FROM interactions i
            JOIN interaction_contacts ic ON i.id = ic.interaction_id
            LEFT JOIN contacts c2 ON ic.contact_id = c2.id AND c2.id != i.contact_id
            WHERE i.contact_id = %s OR i.id IN (
                SELECT interaction_id FROM interaction_contacts WHERE contact_id = %s
            )
            GROUP BY i.id
            ORDER BY i.date DESC LIMIT %s
        """, (contact_id, contact_id, limit))
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


# ===================== Generosity =====================

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


# ===================== Goals =====================

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


# ===================== Conversation Starters =====================

def add_conversation_starter(contact_id, content, source_interaction_id=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO conversation_starters (contact_id, content, source_interaction_id)
            VALUES (%s, %s, %s) RETURNING id
        """, (contact_id, content, source_interaction_id))
        return cur.fetchone()["id"]


def get_conversation_starters(contact_id, active_only=True):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query = "SELECT * FROM conversation_starters WHERE contact_id = %s"
        if active_only:
            query += " AND is_active = TRUE"
        query += " ORDER BY created_at DESC"
        cur.execute(query, (contact_id,))
        return _fetchall(cur)


def deactivate_conversation_starter(starter_id, user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE conversation_starters SET is_active = FALSE
            WHERE id = %s AND contact_id IN (SELECT id FROM contacts WHERE user_id = %s)
        """, (starter_id, user_id))


# ===================== Introductions =====================

def add_introduction(user_id, contact_a_id, contact_b_id, context=None, date=None, status="made"):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO introductions (user_id, contact_a_id, contact_b_id, context, date, status)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (user_id, contact_a_id, contact_b_id, context,
              date or datetime.now().strftime("%Y-%m-%d"), status))
        return cur.fetchone()["id"]


def get_introductions(user_id, contact_id=None, status=None):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query = """
            SELECT intr.*, ca.name as contact_a_name, cb.name as contact_b_name
            FROM introductions intr
            JOIN contacts ca ON intr.contact_a_id = ca.id
            JOIN contacts cb ON intr.contact_b_id = cb.id
            WHERE intr.user_id = %s
        """
        params = [user_id]
        if contact_id:
            query += " AND (intr.contact_a_id = %s OR intr.contact_b_id = %s)"
            params.extend([contact_id, contact_id])
        if status:
            query += " AND intr.status = %s"
            params.append(status)
        query += " ORDER BY intr.date DESC"
        cur.execute(query, params)
        return _fetchall(cur)


def update_introduction(intro_id, user_id, **fields):
    allowed = {"context", "outcome", "status", "date"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [intro_id, user_id]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE introductions SET {set_clause} WHERE id = %s AND user_id = %s", values)


# ===================== Notifications =====================

def generate_notifications(user_id):
    """Generate notifications based on current state. Deduplicate against existing unread."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        today = datetime.now().strftime("%Y-%m-%d")

        # Get existing unread notification related_ids by type
        cur.execute(
            "SELECT type, related_id FROM notifications WHERE user_id = %s AND is_read = FALSE",
            (user_id,)
        )
        existing = {(r["type"], r["related_id"]) for r in cur.fetchall()}

        # 1. Overdue follow-ups
        cur.execute("""
            SELECT i.id, c.name, i.follow_up_by
            FROM interactions i JOIN contacts c ON i.contact_id = c.id
            WHERE c.user_id = %s AND i.follow_up_needed = TRUE AND i.follow_up_done = FALSE
            AND i.follow_up_by IS NOT NULL AND i.follow_up_by < %s
        """, (user_id, today))
        for row in cur.fetchall():
            if ("overdue_followup", row["id"]) not in existing:
                cur.execute("""
                    INSERT INTO notifications (user_id, type, title, message, link, related_id)
                    VALUES (%s, 'overdue_followup', %s, %s, %s, %s)
                """, (user_id, f"Zpožděný follow-up: {row['name']}",
                      f"Follow-up měl být do {row['follow_up_by']}",
                      f"/followups", row["id"]))

        # 2. Birthdays today
        today_mmdd = datetime.now().strftime("%m-%d")
        cur.execute("""
            SELECT id, name, birthday FROM contacts
            WHERE user_id = %s AND birthday IS NOT NULL
            AND (RIGHT(birthday, 5) = %s)
        """, (user_id, today_mmdd))
        for row in cur.fetchall():
            if ("birthday", row["id"]) not in existing:
                cur.execute("""
                    INSERT INTO notifications (user_id, type, title, message, link, related_id)
                    VALUES (%s, 'birthday', %s, %s, %s, %s)
                """, (user_id, f"Narozeniny: {row['name']}",
                      "Nezapomeň popřát!",
                      f"/contact/{row['id']}", row["id"]))

        # 3. Goals with deadline in 3 days
        three_days = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT g.id, g.goal, c.name, g.target_date
            FROM relationship_goals g JOIN contacts c ON g.contact_id = c.id
            WHERE c.user_id = %s AND g.completed = FALSE
            AND g.target_date IS NOT NULL AND g.target_date <= %s AND g.target_date >= %s
        """, (user_id, three_days, today))
        for row in cur.fetchall():
            if ("goal_deadline", row["id"]) not in existing:
                cur.execute("""
                    INSERT INTO notifications (user_id, type, title, message, link, related_id)
                    VALUES (%s, 'goal_deadline', %s, %s, %s, %s)
                """, (user_id, f"Blíží se termín cíle: {row['name']}",
                      f"{row['goal']} (do {row['target_date']})",
                      f"/goals", row["id"]))


def get_notifications(user_id, unread_only=False, limit=20):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        query = "SELECT * FROM notifications WHERE user_id = %s"
        params = [user_id]
        if unread_only:
            query += " AND is_read = FALSE"
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(query, params)
        return _fetchall(cur)


def get_unread_notification_count(user_id):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT COUNT(*) as count FROM notifications WHERE user_id = %s AND is_read = FALSE",
            (user_id,)
        )
        return _fetchone(cur)["count"]


def mark_notification_read(notification_id, user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = %s AND user_id = %s",
            (notification_id, user_id)
        )


def mark_all_notifications_read(user_id):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE notifications SET is_read = TRUE WHERE user_id = %s", (user_id,))


# ===================== Health Score =====================

def calculate_health_score(contact, user_id):
    """Calculate health score 0-100 for a contact. Returns dict with total + components."""
    if contact["circle"] == "dormant":
        return {"total": 0, "frequency": 0, "generosity": 0, "followup": 0, "goals": 0}

    contact_id = contact["id"]
    freq_days = contact.get("contact_frequency_days")

    if freq_days:
        freq = {"ideal": freq_days, "warning": int(freq_days * 1.5), "critical": freq_days * 3}
    else:
        freq = get_circle_frequency(user_id, contact["circle"])

    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Frequency score (40%)
        cur.execute("SELECT MAX(date) as last_date FROM interactions WHERE contact_id = %s", (contact_id,))
        row = _fetchone(cur)
        last_date = row["last_date"] if row else None
        if last_date and freq["ideal"] > 0:
            days_since = (datetime.now().date() - last_date).days
            if days_since <= freq["ideal"]:
                freq_score = 100
            elif days_since >= freq["ideal"] * 3:
                freq_score = 0
            else:
                freq_score = max(0, int(100 * (1 - (days_since - freq["ideal"]) / (freq["ideal"] * 2))))
        elif freq["ideal"] == 0:
            freq_score = 50
        else:
            freq_score = 0

        # 2. Generosity score (20%)
        ninety_ago = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        one_eighty_ago = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        cur.execute(
            "SELECT COUNT(*) as c FROM generosity WHERE contact_id = %s AND date >= %s",
            (contact_id, ninety_ago)
        )
        if _fetchone(cur)["c"] > 0:
            gen_score = 100
        else:
            cur.execute(
                "SELECT COUNT(*) as c FROM generosity WHERE contact_id = %s AND date >= %s",
                (contact_id, one_eighty_ago)
            )
            gen_score = 50 if _fetchone(cur)["c"] > 0 else 0

        # 3. Follow-up score (20%)
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE follow_up_done = TRUE) as done,
                   COUNT(*) FILTER (WHERE follow_up_done = FALSE AND follow_up_by IS NOT NULL AND follow_up_by < CURRENT_DATE) as overdue,
                   COUNT(*) as total
            FROM interactions WHERE contact_id = %s AND follow_up_needed = TRUE
        """, (contact_id,))
        fu = _fetchone(cur)
        if fu["total"] > 0:
            fu_score = int(100 * fu["done"] / fu["total"])
        else:
            fu_score = 50

        # 4. Goals score (20%)
        cur.execute("""
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE completed = TRUE) as completed
            FROM relationship_goals WHERE contact_id = %s
        """, (contact_id,))
        g = _fetchone(cur)
        if g["total"] == 0:
            goal_score = 30
        elif g["completed"] > 0:
            goal_score = 100
        else:
            goal_score = 50

        total = int(freq_score * 0.4 + gen_score * 0.2 + fu_score * 0.2 + goal_score * 0.2)
        return {
            "total": total,
            "frequency": freq_score,
            "generosity": gen_score,
            "followup": fu_score,
            "goals": goal_score,
        }


def get_health_score_history(contact_id, limit=12):
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT score, calculated_at FROM health_score_history
            WHERE contact_id = %s ORDER BY calculated_at DESC LIMIT %s
        """, (contact_id, limit))
        return _fetchall(cur)


def save_health_score_snapshot(contact_id, score):
    """Save monthly snapshot. Only one per month per contact."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT id FROM health_score_history
            WHERE contact_id = %s AND calculated_at >= %s
        """, (contact_id, month_start))
        if not _fetchone(cur):
            cur.execute("""
                INSERT INTO health_score_history (contact_id, score) VALUES (%s, %s)
            """, (contact_id, score))


def get_health_trend(contact_id, current_score):
    """Compare current score with 30 days ago. Returns 'up', 'down', or 'stable'."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        thirty_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        cur.execute("""
            SELECT score FROM health_score_history
            WHERE contact_id = %s AND calculated_at <= %s
            ORDER BY calculated_at DESC LIMIT 1
        """, (contact_id, thirty_ago))
        row = _fetchone(cur)
        if not row:
            return "stable"
        diff = current_score - row["score"]
        if diff >= 10:
            return "up"
        elif diff <= -10:
            return "down"
        return "stable"


# ===================== Agenda =====================

def get_agenda_items(user_id):
    """Get weekly agenda items sorted by priority."""
    items = []
    today = datetime.now().strftime("%Y-%m-%d")
    today_mmdd = datetime.now().strftime("%m-%d")
    week_later = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    week_later_mmdd = (datetime.now() + timedelta(days=7)).strftime("%m-%d")

    # Get skips
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            "SELECT item_type, item_id FROM agenda_skips WHERE user_id = %s AND skipped_until > %s",
            (user_id, today)
        )
        skips = {(r["item_type"], r["item_id"]) for r in cur.fetchall()}

        # 1. Overdue follow-ups (highest priority)
        cur.execute("""
            SELECT i.id, i.type, i.follow_up_by, i.description, c.id as contact_id, c.name as contact_name
            FROM interactions i JOIN contacts c ON i.contact_id = c.id
            WHERE c.user_id = %s AND i.follow_up_needed = TRUE AND i.follow_up_done = FALSE
            ORDER BY i.follow_up_by ASC NULLS LAST
        """, (user_id,))
        for r in cur.fetchall():
            if ("followup", r["id"]) not in skips:
                items.append({
                    "priority": 1, "type": "followup", "id": r["id"],
                    "contact_id": r["contact_id"], "contact_name": r["contact_name"],
                    "title": f"Follow-up: {r['contact_name']}",
                    "detail": f"{r['type']} — {r['description'] or ''}",
                    "due": str(r["follow_up_by"]) if r["follow_up_by"] else None,
                    "overdue": r["follow_up_by"] and str(r["follow_up_by"]) < today,
                })

        # 2. Dormant inner circle (21+ days)
        settings = get_all_user_settings(user_id)
        inner_warn = int(settings.get("freq_inner_circle", 14)) + 7
        cur.execute("""
            SELECT c.id, c.name, MAX(i.date) as last_interaction
            FROM contacts c LEFT JOIN interactions i ON c.id = i.contact_id
            WHERE c.user_id = %s AND c.circle = 'inner_circle'
            GROUP BY c.id HAVING MAX(i.date) IS NULL OR MAX(i.date) < %s
        """, (user_id, (datetime.now() - timedelta(days=inner_warn)).strftime("%Y-%m-%d")))
        for r in cur.fetchall():
            if ("dormant_inner", r["id"]) not in skips:
                items.append({
                    "priority": 2, "type": "dormant_inner", "id": r["id"],
                    "contact_id": r["id"], "contact_name": r["name"],
                    "title": f"Usínající kontakt: {r['name']}",
                    "detail": f"Vnitřní kruh — poslední interakce: {r['last_interaction'] or 'žádná'}",
                    "due": None, "overdue": False,
                })

        # 3. Dormant close contacts (45+ days)
        close_warn = int(settings.get("freq_close", 30)) + 15
        cur.execute("""
            SELECT c.id, c.name, MAX(i.date) as last_interaction
            FROM contacts c LEFT JOIN interactions i ON c.id = i.contact_id
            WHERE c.user_id = %s AND c.circle = 'close'
            GROUP BY c.id HAVING MAX(i.date) IS NULL OR MAX(i.date) < %s
        """, (user_id, (datetime.now() - timedelta(days=close_warn)).strftime("%Y-%m-%d")))
        for r in cur.fetchall():
            if ("dormant_close", r["id"]) not in skips:
                items.append({
                    "priority": 3, "type": "dormant_close", "id": r["id"],
                    "contact_id": r["id"], "contact_name": r["name"],
                    "title": f"Usínající kontakt: {r['name']}",
                    "detail": f"Blízcí — poslední interakce: {r['last_interaction'] or 'žádná'}",
                    "due": None, "overdue": False,
                })

        # 4. Birthdays this week
        cur.execute("""
            SELECT id, name, birthday FROM contacts
            WHERE user_id = %s AND birthday IS NOT NULL
        """, (user_id,))
        for r in cur.fetchall():
            bday_mmdd = r["birthday"][-5:]  # last 5 chars = MM-DD
            if today_mmdd <= bday_mmdd <= week_later_mmdd or (week_later_mmdd < today_mmdd and (bday_mmdd >= today_mmdd or bday_mmdd <= week_later_mmdd)):
                if ("birthday", r["id"]) not in skips:
                    items.append({
                        "priority": 4, "type": "birthday", "id": r["id"],
                        "contact_id": r["id"], "contact_name": r["name"],
                        "title": f"Narozeniny: {r['name']}",
                        "detail": f"Datum: {r['birthday']}",
                        "due": r["birthday"], "overdue": False,
                    })

        # 5. Goals with approaching deadline
        cur.execute("""
            SELECT g.id, g.goal, g.target_date, c.id as contact_id, c.name as contact_name
            FROM relationship_goals g JOIN contacts c ON g.contact_id = c.id
            WHERE c.user_id = %s AND g.completed = FALSE
            AND g.target_date IS NOT NULL AND g.target_date <= %s
        """, (user_id, week_later))
        for r in cur.fetchall():
            if ("goal", r["id"]) not in skips:
                items.append({
                    "priority": 5, "type": "goal", "id": r["id"],
                    "contact_id": r["contact_id"], "contact_name": r["contact_name"],
                    "title": f"Cíl: {r['goal']}",
                    "detail": f"Kontakt: {r['contact_name']} — do {r['target_date']}",
                    "due": str(r["target_date"]), "overdue": str(r["target_date"]) < today,
                })

    items.sort(key=lambda x: (x["priority"], x.get("due") or "9999"))
    return items


def skip_agenda_item(user_id, item_type, item_id):
    """Skip an agenda item until next Monday."""
    today = datetime.now()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = (today + timedelta(days=days_until_monday)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO agenda_skips (user_id, item_type, item_id, skipped_until)
            VALUES (%s, %s, %s, %s)
        """, (user_id, item_type, item_id, next_monday))


def get_weekly_progress(user_id):
    """Count interactions since last Monday."""
    today = datetime.now()
    days_since_monday = today.weekday()  # 0=Mon
    last_monday = (today - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")

    settings = get_all_user_settings(user_id)
    weekly_goal = int(settings.get("weekly_goal", 5))

    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT COUNT(DISTINCT i.id) as count
            FROM interactions i JOIN contacts c ON i.contact_id = c.id
            WHERE c.user_id = %s AND i.date >= %s
        """, (user_id, last_monday))
        done = _fetchone(cur)["count"]
        return {"done": done, "goal": weekly_goal, "percent": min(100, int(done / weekly_goal * 100)) if weekly_goal > 0 else 100}


# ===================== Dashboard Stats =====================

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

        # Introductions this month
        cur.execute("""
            SELECT COUNT(*) as count FROM introductions
            WHERE user_id = %s AND date >= %s
        """, (user_id, month_ago))
        stats["introductions_this_month"] = _fetchone(cur)["count"]

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
