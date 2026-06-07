"""
壹米云相册 - 人物路由
"""
import logging
from flask import Blueprint, request, jsonify
from database import get_db, safe_execute
from auth import requires_auth

logger = logging.getLogger(__name__)
bp = Blueprint("persons", __name__)


def _photo_info(row):
    from routes.photos import photo_info
    return photo_info(row)


@bp.route("/api/persons")
@requires_auth
def list_persons():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT p.*, COUNT(pp.photo_id) as photo_count
            FROM persons p
            LEFT JOIN photo_persons pp ON p.id=pp.person_id
            GROUP BY p.id ORDER BY photo_count DESC
        """).fetchall()
        persons = []
        for r in rows:
            cover = None
            if r["cover_photo_id"]:
                cr = conn.execute("SELECT * FROM photos WHERE id=?", (r["cover_photo_id"],)).fetchone()
                if cr:
                    cover = _photo_info(cr)
            persons.append({"id": r["id"], "name": r["name"], "photo_count": r["photo_count"], "cover": cover})
    return jsonify({"persons": persons})


@bp.route("/api/persons", methods=["POST"])
@requires_auth
def create_person():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_db() as conn:
        conn.execute("INSERT INTO persons (name) VALUES (?)", (name,))
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return jsonify({"id": pid, "name": name})


@bp.route("/api/persons/<int:pid>")
@requires_auth
def get_person(pid):
    with get_db() as conn:
        person = conn.execute("SELECT * FROM persons WHERE id=?", (pid,)).fetchone()
        if not person:
            return jsonify({"error": "not found"}), 404
        photos = conn.execute("""
            SELECT p.* FROM photos p
            JOIN photo_persons pp ON p.id=pp.photo_id
            WHERE pp.person_id=? AND p.is_deleted=0
            ORDER BY p.taken_at DESC
        """, (pid,)).fetchall()
    return jsonify({"id": person["id"], "name": person["name"], "photos": [_photo_info(r) for r in photos]})


@bp.route("/api/persons/<int:pid>", methods=["DELETE"])
@requires_auth
def delete_person(pid):
    with get_db() as conn:
        conn.execute("DELETE FROM photo_persons WHERE person_id=?", (pid,))
        conn.execute("DELETE FROM persons WHERE id=?", (pid,))
    return jsonify({"ok": True})


@bp.route("/api/persons/<int:pid>/name", methods=["PUT"])
@requires_auth
def rename_person(pid):
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    with get_db() as conn:
        conn.execute("UPDATE persons SET name=? WHERE id=?", (name, pid))
    return jsonify({"ok": True})


@bp.route("/api/persons/<int:pid>/photos", methods=["POST"])
@requires_auth
def add_photos_to_person(pid):
    data = request.get_json()
    ids = data.get("photo_ids", [])
    with get_db() as conn:
        for photo_id in ids:
            conn.execute("INSERT OR IGNORE INTO photo_persons (photo_id, person_id) VALUES (?,?)", (photo_id, pid))
        if ids:
            conn.execute("UPDATE persons SET cover_photo_id=? WHERE id=?", (ids[0], pid))
    return jsonify({"ok": True, "added": len(ids)})


@bp.route("/api/persons/<int:pid>/photos/<int:photo_id>", methods=["DELETE"])
@requires_auth
def remove_photo_from_person(pid, photo_id):
    with get_db() as conn:
        conn.execute("DELETE FROM photo_persons WHERE photo_id=? AND person_id=?", (photo_id, pid))
    return jsonify({"ok": True})
