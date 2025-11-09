from pathlib import Path
import uuid
import getpass
from shadowbox.database.connection import DatabaseConnection
from shadowbox.database.models import UserModel, FileModel, BoxModel, row_to_metadata
from shadowbox.core.models import FileMetadata, Box
from shadowbox.core.storage import Storage


def init_env(db_path="./shadowbox.db", storage_root=None, username=None):
    # initialize db + storage + user + default box context
    db = DatabaseConnection(db_path)
    db.initialize()
    storage = Storage(storage_root)
    uname = username or getpass.getuser()

    um = UserModel(db)
    row = um.get_by_username(uname)

    if row:
        user_id = row["user_id"]
    else:
        user_id = str(uuid.uuid4())
        um.create(user_id=user_id, username=uname)

    # Ensure default box for this user
    bm = BoxModel(db)
    default_box = None
    for box in bm.list_by_user(user_id) or []:
        if box.get("box_name") == "default":
            default_box = box
            break
    if not default_box:
        default = Box(user_id=user_id, box_name="default", description="Default box")
        bm.create(default)
        default_box = bm.get(default.box_id)

    return {"db": db, "storage": storage, "username": uname, "user_id": user_id, "box_id": default_box["box_id"]}


def find_by_filename(env, filename):
    db = env["db"]
    row = db.fetch_one(
        "SELECT * FROM files "
        "WHERE user_id = ? AND box_id = ? AND filename = ? AND status != 'deleted' "
        "ORDER BY created_at DESC LIMIT 1",
        (env["user_id"], env["box_id"], filename),
    )
    if not row:
        return None

    tags = [
        r["tag_name"]
        for r in db.fetch_all(
            "SELECT t.tag_name FROM tags t "
            "JOIN file_tags ft ON ft.tag_id = t.tag_id "
            "WHERE ft.file_id = ?",
            (row["file_id"],),
        )
    ]
    return row_to_metadata(row, tags)


def select_box(env, box_name: str) -> dict:
    # select or create a box by name for the current user
    db = env["db"]
    bm = BoxModel(db)
    user_id = env["user_id"]
    existing = bm.list_by_user(user_id) or []
    for b in existing:
        if b.get("box_name") == box_name:
            env["box_id"] = b["box_id"]
            # ensure storage scaffolding exists
            env["storage"].ensure_box(user_id, b["box_id"])
            return b
    # create new box
    box = Box(user_id=user_id, box_name=box_name, description=f"Box {box_name}")
    bm.create(box)
    env["storage"].ensure_box(user_id, box.box_id)
    env["box_id"] = box.box_id
    return bm.get(box.box_id)


def format_list(env):
    # newline list of filenames in default box (sort by latest)
    fm = FileModel(env["db"])
    items = fm.list_by_box(env["box_id"], include_deleted=False, limit=1000, offset=0)
    return "\n".join(m.filename for m in items)


def open_for_get(env, filename):
    # returns a readable file object for GET from default box
    m = find_by_filename(env, filename)
    if not m:
        return None
    # unencrypted path assumed for adapter operations
    path = env["storage"].blob_root(env["user_id"], env["box_id"]) / m.hash_sha256
    if not path.exists():
        return None
    return open(path, "rb")


def finalize_put(env, tmp_path, filename):
    # import tmp file into Storage + DB in default box
    info = env["storage"].put(env["user_id"], env["box_id"], tmp_path)
    db = env["db"]
    um = UserModel(db)
    fm = FileModel(db)

    user = um.get(env["user_id"])
    meta = FileMetadata(
        user_id=env["user_id"],
        box_id=env["box_id"],
        filename=filename,
        original_path=str(tmp_path),
        size=info["size"],
        hash_sha256=info["hash"],
        owner=user["username"],
        tags=[],
    )
    fm.create(meta)
    um.update_quota(env["user_id"], user["used_bytes"] + meta.size)
    return meta.file_id


def delete_filename(env, filename):
    # soft delete by filename and update quota
    m = find_by_filename(env, filename)
    if not m:
        return False

    fm = FileModel(env["db"])
    fm.delete(m.file_id, soft=True)
    user = UserModel(env["db"]).get(env["user_id"])

    if user:
        used = max(0, user["used_bytes"] - m.size)
        UserModel(env["db"]).update_quota(env["user_id"], used)
    return True
