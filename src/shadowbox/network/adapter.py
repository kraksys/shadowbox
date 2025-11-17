from pathlib import Path
import uuid
import getpass
from shadowbox.database.connection import DatabaseConnection
from shadowbox.database.models import UserModel, FileModel, BoxModel, row_to_metadata, BoxShareModel
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


def list_boxes(env) -> str:
    """Lists all boxes for the current user."""
    db = env["db"]
    user_id = env["user_id"]
    bm = BoxModel(db)
    try:
        boxes = bm.list_by_user(user_id)
        if not boxes:
            return "No boxes found for this user.\n"

        response_lines = ["Available boxes:"]
        for box in boxes:
            response_lines.append(f"- {box['box_name']} (ID: {box['box_id']})")
        return "\n".join(response_lines) + "\n"
    except Exception as e:
        return f"ERROR: Failed to list boxes: {e}\n"


# def share_box(env, box_name: str, share_with_username: str, permission: str) -> str:
#     """Shares a box with another user."""
#     db = env["db"]
#     user_id = env["user_id"]
#     bm = BoxModel(db)
#     um = UserModel(db)
#     bsm = BoxShareModel(db)
#
#     try:
#         user_boxes = bm.list_by_user(user_id)
#         box_to_share = next((box for box in user_boxes if box["box_name"] == box_name), None)
#         if not box_to_share:
#             raise BoxNotFoundError(f"Box '{box_name}' not found for the current user.")
#
#         target_user_data = um.get_by_username(share_with_username)
#         if not target_user_data:
#             raise UserNotFoundError(f"User '{share_with_username}' not found.")
#         shared_with_user_id = target_user_data["user_id"]
#
#         if user_id == shared_with_user_id:
#             raise ValueError("You cannot share a box with yourself.")
#
#         if permission not in ["read", "write", "admin"]:
#             raise ValueError(f"Invalid permission level: {permission}")
#
#         # Delete existing share if it exists to update it
#         existing_shares = bsm.list_by_box(box_to_share["box_id"])
#         for share in existing_shares:
#             if share["shared_with_user_id"] == shared_with_user_id:
#                 bsm.delete(share["share_id"])
#
#         # Create new share
#         share = BoxShare(
#             box_id=box_to_share["box_id"],
#             shared_by_user_id=user_id,
#             shared_with_user_id=shared_with_user_id,
#             permission_level=permission,
#         )
#         bsm.create(share)
#         bm.set_shared(box_to_share["box_id"], True)
#
#         return f"OK: Successfully shared box '{box_name}' with '{share_with_username}' with '{permission}' permissions.\n"
#
#     except (BoxNotFoundError, UserNotFoundError, ValueError) as e:
#         return f"ERROR: {e}\n"
#     except Exception as e:
#         return f"ERROR: An unexpected error occurred: {e}\n"
#
#
# def list_available_users(env) -> str:
#     """Lists all users available to share with."""
#     db = env["db"]
#     current_user_id = env["user_id"]
#     um = UserModel(db)
#     try:
#         users = um.list_all()
#         # Filter out the current user
#         available_users = [user for user in users if user["user_id"] != current_user_id]
#         if not available_users:
#             return "No other users available to share with.\n"
#
#         response_lines = ["Available users:"]
#         for user in available_users:
#             response_lines.append(f"- {user['username']}")
#
#         return "\n".join(response_lines) + "\n"
#     except Exception as e:
#         return f"ERROR: Could not retrieve user list: {e}\n"