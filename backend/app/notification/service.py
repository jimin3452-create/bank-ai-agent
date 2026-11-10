from psycopg import Connection

from app.common.errors import AppError


def list_notifications(conn: Connection, user_id, unread_only: bool, limit: int) -> dict:
    where = "user_id = %s" + (" AND read_at IS NULL" if unread_only else "")
    items = conn.execute(
        f"SELECT id, type, message, read_at, created_at FROM notifications WHERE {where} "
        "ORDER BY created_at DESC, id DESC LIMIT %s", (user_id, limit)).fetchall()
    unread = conn.execute("SELECT count(*) AS n FROM notifications WHERE user_id = %s AND read_at IS NULL",
                          (user_id,)).fetchone()["n"]
    return {"items": items, "unread_count": unread}


def mark_read(conn: Connection, user_id, notification_id: int) -> dict:
    row = conn.execute(
        "UPDATE notifications SET read_at = COALESCE(read_at, now()) WHERE id = %s AND user_id = %s "
        "RETURNING id, type, message, read_at, created_at", (notification_id, user_id)).fetchone()
    if row is None:
        raise AppError(404, "NOT_FOUND", "알림을 찾을 수 없습니다")
    return row


def mark_all_read(conn: Connection, user_id) -> dict:
    n = conn.execute("UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL", (user_id,)).rowcount
    return {"updated": n}
