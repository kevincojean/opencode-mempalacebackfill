import sqlite3
import json

def create_fixture_db(path: str):
    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE project (
        id text PRIMARY KEY,
        worktree text NOT NULL,
        vcs text,
        name text,
        icon_url text,
        icon_color text,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        time_initialized integer,
        sandboxes text NOT NULL,
        commands text,
        icon_url_override text
    )""")

    cursor.execute("""
    CREATE TABLE session (
        id text PRIMARY KEY,
        project_id text NOT NULL,
        parent_id text,
        slug text NOT NULL,
        directory text NOT NULL,
        title text NOT NULL,
        version text NOT NULL,
        share_url text,
        summary_additions integer,
        summary_deletions integer,
        summary_files integer,
        summary_diffs text,
        revert text,
        permission text,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        time_compacting integer,
        time_archived integer,
        workspace_id text,
        path text,
        agent text,
        model text,
        cost real DEFAULT 0 NOT NULL,
        tokens_input integer DEFAULT 0 NOT NULL,
        tokens_output integer DEFAULT 0 NOT NULL,
        tokens_reasoning integer DEFAULT 0 NOT NULL,
        tokens_cache_read integer DEFAULT 0 NOT NULL,
        tokens_cache_write integer DEFAULT 0 NOT NULL,
        metadata text,
        CONSTRAINT fk_session_project_id_project_id_fk FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
    )""")

    cursor.execute("""
    CREATE TABLE message (
        id text PRIMARY KEY,
        session_id text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        data text NOT NULL,
        CONSTRAINT fk_message_session_id_session_id_fk FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE
    )""")

    cursor.execute("""
    CREATE TABLE part (
        id text PRIMARY KEY,
        message_id text NOT NULL,
        session_id text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        data text NOT NULL,
        CONSTRAINT fk_part_message_id_message_id_fk FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE
    )""")

    cursor.execute(
        "INSERT INTO project (id, worktree, sandboxes, time_created, time_updated) VALUES (?, ?, ?, ?, ?)",
        ("proj_1", "/tmp/proj1", "[]", 1735689600000, 1735689600000)
    )

    sessions = [
        ("ses_test_001", 1735689600000, "Session 1"),
        ("ses_test_002", 1743465600000, "Session 2"),
        ("ses_test_003", 1756684800000, "Session 3")
    ]

    for s_id, ts, title in sessions:
        cursor.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (s_id, "proj_1", s_id, f"dir_{s_id}", title, "1.0.0", ts, ts)
        )

        roles = ["system", "user", "assistant"]
        for i, role in enumerate(roles):
            m_id = f"msg_{s_id}_{role}"
            p_id = f"part_{s_id}_{role}"
            msg_ts = ts + (i * 1000)
            
            cursor.execute(
                "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
                (m_id, s_id, msg_ts, msg_ts, json.dumps({"role": role}))
            )
            cursor.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
                (p_id, m_id, s_id, msg_ts, msg_ts, json.dumps({"type": "text", "text": f"Content for {role} in {s_id}"}))
            )

    conn.commit()
    conn.close()


def create_multi_project_fixture_db(path: str) -> None:
    """Create a test database with two projects for multi-wing testing.

    Project 1: ``proj_1`` with worktree ``/tmp/proj1`` → wing ``wing_proj1``
    Project 2: ``proj_2`` with worktree ``/home/user/projects/my-app`` → wing ``wing_my-app``
    """
    conn = sqlite3.connect(path)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE project (
        id text PRIMARY KEY,
        worktree text NOT NULL,
        vcs text,
        name text,
        icon_url text,
        icon_color text,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        time_initialized integer,
        sandboxes text NOT NULL,
        commands text,
        icon_url_override text
    )""")

    cursor.execute("""
    CREATE TABLE session (
        id text PRIMARY KEY,
        project_id text NOT NULL,
        parent_id text,
        slug text NOT NULL,
        directory text NOT NULL,
        title text NOT NULL,
        version text NOT NULL,
        share_url text,
        summary_additions integer,
        summary_deletions integer,
        summary_files integer,
        summary_diffs text,
        revert text,
        permission text,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        time_compacting integer,
        time_archived integer,
        workspace_id text,
        path text,
        agent text,
        model text,
        cost real DEFAULT 0 NOT NULL,
        tokens_input integer DEFAULT 0 NOT NULL,
        tokens_output integer DEFAULT 0 NOT NULL,
        tokens_reasoning integer DEFAULT 0 NOT NULL,
        tokens_cache_read integer DEFAULT 0 NOT NULL,
        tokens_cache_write integer DEFAULT 0 NOT NULL,
        metadata text,
        CONSTRAINT fk_session_project_id_project_id_fk FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
    )""")

    cursor.execute("""
    CREATE TABLE message (
        id text PRIMARY KEY,
        session_id text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        data text NOT NULL,
        CONSTRAINT fk_message_session_id_session_id_fk FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE
    )""")

    cursor.execute("""
    CREATE TABLE part (
        id text PRIMARY KEY,
        message_id text NOT NULL,
        session_id text NOT NULL,
        time_created integer NOT NULL,
        time_updated integer NOT NULL,
        data text NOT NULL,
        CONSTRAINT fk_part_message_id_message_id_fk FOREIGN KEY (message_id) REFERENCES part(id) ON DELETE CASCADE
    )""")

    cursor.execute(
        "INSERT INTO project (id, worktree, sandboxes, time_created, time_updated) VALUES (?, ?, ?, ?, ?)",
        ("proj_1", "/tmp/proj1", "[]", 1735689600000, 1735689600000)
    )
    cursor.execute(
        "INSERT INTO project (id, worktree, sandboxes, time_created, time_updated) VALUES (?, ?, ?, ?, ?)",
        ("proj_2", "/home/user/projects/my-app", "[]", 1735689600000, 1735689600000)
    )

    # 2 sessions for proj_1
    proj1_sessions = [
        ("ses_001", 1735689600000, "Project 1 Session A"),
        ("ses_002", 1743465600000, "Project 1 Session B"),
    ]
    for s_id, ts, title in proj1_sessions:
        cursor.execute(
            "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (s_id, "proj_1", s_id, f"dir_{s_id}", title, "1.0.0", ts, ts)
        )
        for i, role in enumerate(["system", "user", "assistant"]):
            m_id = f"msg_{s_id}_{role}"
            p_id = f"part_{s_id}_{role}"
            msg_ts = ts + (i * 1000)
            cursor.execute(
                "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
                (m_id, s_id, msg_ts, msg_ts, json.dumps({"role": role}))
            )
            cursor.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
                (p_id, m_id, s_id, msg_ts, msg_ts, json.dumps({"type": "text", "text": f"Content for {role} in {s_id}"}))
            )

    # 1 session for proj_2
    s_id = "ses_003"
    ts = 1756684800000
    cursor.execute(
        "INSERT INTO session (id, project_id, slug, directory, title, version, time_created, time_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (s_id, "proj_2", s_id, f"dir_{s_id}", "Project 2 Session A", "1.0.0", ts, ts)
    )
    for i, role in enumerate(["system", "user", "assistant"]):
        m_id = f"msg_{s_id}_{role}"
        p_id = f"part_{s_id}_{role}"
        msg_ts = ts + (i * 1000)
        cursor.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?)",
            (m_id, s_id, msg_ts, msg_ts, json.dumps({"role": role}))
        )
        cursor.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            (p_id, m_id, s_id, msg_ts, msg_ts, json.dumps({"type": "text", "text": f"Content for {role} in {s_id}"}))
        )

    conn.commit()
    conn.close()
