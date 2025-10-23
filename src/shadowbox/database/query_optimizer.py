from .connection import DatabaseConnection


def apply_pragmas(db):
    # basic settings for our usecases
    # chosen based on https://sqlite.org/pragma.html

    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=16000")
    db.execute("PRAGMA foreign_keys=ON")


def analyze(db):
    # update stats for the planner
    db.execute("ANALYZE")
    db.execute("PRAGMA optimize")


def like_fix(s):
    # used to fix LIKE wildcards for queries from Python
    return s.replace("%", "\\%").replace("_", "\\_")


def search(db, q, user_id=None, limit=25, offset=0):
    # Simple LIKE search over filename & desc
    q = (q or "").strip()

    if not q:
        return []

    pattern = "%" + like_fix(q) + "%"

    sql = (
        "SELECT * FROM files"
        "WHERE (filename LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
    )
    params = [pattern, pattern]

    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    rows = db.fetch_all(sql, tuple(params))

    from .models import row_to_metadata

    results = []
    for r in rows:
        results.append(row_to_metadata(r, tags=[]))
    return results
