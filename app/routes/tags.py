"""
壹米云相册 - 标签路由
"""
import sqlite3
import logging
from flask import Blueprint, request, jsonify
from database import get_db, safe_execute
from auth import requires_auth

logger = logging.getLogger(__name__)
bp = Blueprint("tags", __name__)


@bp.route("/api/tags")
@requires_auth
def list_tags():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT t.*, COUNT(pt.photo_id) as photo_count
            FROM tags t LEFT JOIN photo_tags pt ON t.id=pt.tag_id
            GROUP BY t.id ORDER BY photo_count DESC
        """).fetchall()
    return jsonify({"tags": [{"id": r["id"], "name": r["name"], "photo_count": r["photo_count"]} for r in rows]})


@bp.route("/api/tags", methods=["POST"])
@requires_auth
def create_tag():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_db() as conn:
        try:
            conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        except sqlite3.IntegrityError:
            tid = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()["id"]
    return jsonify({"id": tid, "name": name})


@bp.route("/api/photos/<int:pid>/tags", methods=["POST"])
@requires_auth
def add_tags_to_photo(pid):
    data = request.get_json()
    tag_names = data.get("tags", [])
    with get_db() as conn:
        for name in tag_names:
            name = name.strip()
            if not name:
                continue
            try:
                conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            except sqlite3.IntegrityError:
                pass
            tag = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
            if tag:
                conn.execute("INSERT OR IGNORE INTO photo_tags (photo_id, tag_id) VALUES (?,?)", (pid, tag["id"]))
    return jsonify({"ok": True})


@bp.route("/api/photos/<int:pid>/tags/<int:tid>", methods=["DELETE"])
@requires_auth
def remove_tag_from_photo(pid, tid):
    with get_db() as conn:
        conn.execute("DELETE FROM photo_tags WHERE photo_id=? AND tag_id=?", (pid, tid))
    return jsonify({"ok": True})
