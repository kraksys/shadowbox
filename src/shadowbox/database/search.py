from .connection import DatabaseConnection


def tags_map(db, file_ids):
    """file_id to [tag] map in one query using polymorphic tags table"""
    if not file_ids:
        return {}
    placeholders = ",".join(["?"] * len(file_ids))
    sql = (
        "SELECT entity_id, tag_name "
        "FROM tags "
        f"WHERE entity_type = 'file' AND entity_id IN ({placeholders})"
    )
    rows = db.fetch_all(sql, tuple(file_ids))
    m = {}
    for r in rows:
        fileid = r["entity_id"]
        if fileid not in m:
            m[fileid] = []
        m[fileid].append(r["tag_name"])
    return m


def rows_to_metadata(db, rows):
    """convert rows to FileMetadata, with tags"""
    from .models import row_to_metadata

    ids = [r["file_id"] for r in rows]
    tm = tags_map(db, ids)
    out = []
    for r in rows:
        out.append(row_to_metadata(r, tm.get(r["file_id"], [])))
    return out


def search_fts(db, q, user_id=None, limit=25, offset=0):
    """ranked FTS search"""
    q = (q or "").strip()
    if not q:
        return []

    sql = """
    SELECT f.*, bm25(files_fts) AS rank
    FROM files_fts
    JOIN files f ON f.file_id = files_fts.file_id
    WHERE files_fts MATCH ?
    """
    params = [q]

    if user_id:
        sql += " AND f.user_id = ?"
        params.append(user_id)

    sql += " ORDER BY rank LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(offset)

    rows = db.fetch_all(sql, tuple(params))
    return rows_to_metadata(db, rows)


def fuzzy_search_fts(db, term, user_id=None, limit=25, offset=0):
    """Simple prefix fuzziness via token*"""
    tokens = [t for t in (term or "").strip().split() if t]
    if not tokens:
        return []
    expanded = " ".join(t + "*" for t in tokens)
    return search_fts(db, expanded, user_id=user_id, limit=limit, offset=offset)


def search_by_tag(db, tag, user_id=None, box_id=None, limit=100, offset=0):
    """Return files tagged with a given tag, uses the polymorphic tags table (where entity_type = file and tag_name match the tag)"""
    tag = (tag or "").strip()
    if not tag:
        return []

    sql = """
    SELECT f.*
    FROM files f
    JOIN tags t
        ON t.entity_type = 'file'
        AND t.entity_id = f.file_id
    WHERE t.tag_name = ?
    """
    params = [tag]

    if user_id:
        sql += " AND f.user_id = ?"
        params.append(user_id)

    if box_id:
        sql += " AND f.box_id = ?"
        params.append(box_id)

    sql += " ORDER BY f.created_at DESC LIMIT ? OFFSET ?"
    params.append(limit)
    params.append(offset)

    rows = db.fetch_all(sql, tuple(params))
    return rows_to_metadata(db, rows)
