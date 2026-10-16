"""SQLite database for clip feedback and analytics."""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(r"E:\VS_CODE_Learning\Clipping_videos\data\clips.db")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_title TEXT,
            video_source TEXT,
            provider TEXT,
            model TEXT,
            clip_count INTEGER,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            filename TEXT,
            title TEXT,
            ai_score INTEGER,
            start_time REAL,
            end_time REAL,
            duration REAL,
            hook TEXT,
            reason TEXT,
            created_at TEXT,
            pinned INTEGER DEFAULT 0,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)

    # Add pinned column if upgrading an old DB
    try:
        c.execute("ALTER TABLE clips ADD COLUMN pinned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_id INTEGER,
            user_rating INTEGER,
            platform TEXT,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            shares INTEGER,
            notes TEXT,
            created_at TEXT,
            FOREIGN KEY (clip_id) REFERENCES clips(id)
        )
    """)

    conn.commit()
    conn.close()


def set_pinned(clip_id: int, pinned: bool):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE clips SET pinned = ? WHERE id = ?", (1 if pinned else 0, clip_id))
    conn.commit()
    conn.close()


def is_pinned(clip_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT pinned FROM clips WHERE id = ?", (clip_id,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0])


def get_pinned_filenames() -> set:
    """Return set of filenames that are pinned."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT filename FROM clips WHERE pinned = 1")
    rows = c.fetchall()
    conn.close()
    return {r[0] for r in rows}


def create_job(video_title, video_source, provider, model, clip_count):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO jobs (video_title, video_source, provider, model, clip_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (video_title, video_source, provider, model, clip_count, datetime.now().isoformat()))
    job_id = c.lastrowid
    conn.commit()
    conn.close()
    return job_id


def add_clip(job_id, filename, title, ai_score, start_time, end_time, duration, hook, reason):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO clips (job_id, filename, title, ai_score, start_time, end_time,
                           duration, hook, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (job_id, filename, title, ai_score, start_time, end_time, duration,
          hook, reason, datetime.now().isoformat()))
    clip_id = c.lastrowid
    conn.commit()
    conn.close()
    return clip_id


def add_feedback(clip_id, user_rating, platform, views, likes, comments, shares, notes):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO feedback (clip_id, user_rating, platform, views, likes,
                              comments, shares, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (clip_id, user_rating, platform, views, likes, comments, shares,
          notes, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_best_clips(limit=20):
    """Get clips with highest real-world performance — for future prompt tuning."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT clips.title, clips.hook, clips.ai_score,
               MAX(feedback.views) as best_views
        FROM clips
        LEFT JOIN feedback ON feedback.clip_id = clips.id
        WHERE feedback.views IS NOT NULL
        GROUP BY clips.id
        ORDER BY best_views DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [{"title": r[0], "hook": r[1], "ai_score": r[2], "views": r[3]} for r in rows]


def get_jobs(limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_clips_for_job(job_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM clips WHERE job_id = ? ORDER BY ai_score DESC", (job_id,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM jobs")
    total_jobs = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM clips")
    total_clips = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM feedback")
    total_feedback = c.fetchone()[0]
    conn.close()
    return {
        "total_jobs": total_jobs,
        "total_clips": total_clips,
        "total_feedback": total_feedback,
    }