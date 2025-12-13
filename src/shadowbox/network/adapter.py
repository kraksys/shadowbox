from pathlib import Path
import uuid
import getpass
import io 
from shadowbox.database.connection import DatabaseConnection
from shadowbox.database.models import (
    UserModel,
    FileModel,
    BoxModel,
    BoxShareModel,
    row_to_metadata,
)
from shadowbox.core.models import FileMetadata, Box, BoxShare
from shadowbox.core.storage import Storage
from shadowbox.core.exceptions import BoxNotFoundError, UserNotFoundError, AccessDeniedError



def init_env(db_path="./shadowbox.db", storage_root=None, username=None, storage=None):
    # initialize db + storage + user + default box context
    db = DatabaseConnection(db_path)
    db.initialize()
    if storage is None: 
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
    default_box = Non
    box_id = None
    for box in bm.list_by_user(user_id) or []:
        if box.get("box_name") == "default":
            default_box = box
            break
    # if not default_box:
    #     default = Box(user_id=user_id, box_name="default", description="Default box")
    #     bm.create(default)
    #     default_box = bm.get(default.box_id)
    if default_box:
        box_id = default_box["box_id"]

    return {"db": db, "storage": storage, "username": uname, "user_id": user_id, "box_id": box_id}


def check_permission(env, box_id, required_permission="read") -> bool:
    """
    Checks if the user in the env has the required permission for a given box_id.
    Returns True if access is granted, False otherwise.
    """
    db = env["db"]
    user_id = env["user_id"]

    bm = BoxModel(db)
    box = bm.get(box_id)

    if not box:
        return False  # Box doesn't exist

    # The owner always has full permission
    if box['user_id'] == user_id:
        return True

    # If not the owner, check the shares table
    bsm = BoxShareModel(db)
    return bsm.has_access(box_id, user_id, required_permission)


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
            "SELECT tag_name FROM tags "
            "WHERE entity_type = 'file' AND entity_id = ?",
            (row["file_id"],),
        )
    ]
    return row_to_metadata(row, tags)


def select_box(env, namespaced_box: str) -> dict:
    """
    Selects a box using the format 'owner_username/box_name'.
    Verifies that the current user has at least read permission.
    """
    db = env["db"]
    current_user_id = env["user_id"]

    # 1. Parse the new format
    if '/' not in namespaced_box:
        # For convenience, if no slash is provided, assume the user means their own box.
        owner_username = env["username"]
        box_name = namespaced_box
    else:
        parts = namespaced_box.split('/', 1)
        if len(parts) != 2:
            raise ValueError("Invalid box format. Use 'owner_username/box_name'.")
        owner_username, box_name = parts

    # 2. Find the owner and the box
    um = UserModel(db)
    owner = um.get_by_username(owner_username)
    if not owner:
        raise UserNotFoundError(f"The box owner '{owner_username}' does not exist.")

    owner_id = owner['user_id']

    bm = BoxModel(db)
    owned_boxes = bm.list_by_user(owner_id) or []
    target_box = next((b for b in owned_boxes if b.get("box_name") == box_name), None)

    if not target_box:
        raise BoxNotFoundError(f"Box '{box_name}' owned by '{owner_username}' not found.")

    box_id = target_box['box_id']

    # 3. Verify the current user has permission to access this box
    if not check_permission(env, box_id, "read"):
        raise AccessDeniedError(f"You do not have permission to access the box '{namespaced_box}'.")

    # 4. If all checks pass, set the active box in the environment
    env["box_id"] = box_id
    # Use the actual owner's ID for ensuring the storage path exists
    env["storage"].ensure_box(owner_id, box_id)

    return target_box


def format_list(env):
    # newline list of filenames in default box (sort by latest)
    if not check_permission(env, env["box_id"], "read"):
        raise AccessDeniedError("You do not have read permission for this box.")
    fm = FileModel(env["db"])
    items = fm.list_by_box(env["box_id"], include_deleted=False, limit=1000, offset=0)
    return ",\n".join(f"{m.file_id}: {{Filename: {m.filename}, Size: {m.size}, Tags: {m.tags}, Status: {m.status}, Modified: {m.modified_at}}}" for m in items)


def open_for_get(env, identifier):
    """
    Return a readable file object for GET from active box. 
    
    The identifier can be either; 
    1) file_id 
    2) filename within active box 
    """
    db = env["db"]
    storage = env["storage"]
    fm = FileModel(db) 
    
    meta = None 
    
    # Resolve by file_id first
    candidate = fm.get(identifier) 
    active_box_id = env.get("box_id")
    if candidate is not None and getattr(candidate, "box_id", None) == active_box_id: 
        meta = candidate 
    
    # If file_id resolution fails, fall back to filename lookup 
    if meta is None: 
        meta = find_by_filename(env, identifier) 
    
    if not meta: 
        return None 
        
    # Determine owning user and box  
    owner_id = getattr(meta, "user_id", env["user_id"])
    box_id = meta.box_id 
    file_hash = meta.hash_sha256 
    if not file_hash: 
        return None 
        
    # Detect per file encryption
    if meta.is_encrypted:
        # Implement per file encryption logic here
        pass
    
    blob_path = storage.blob_root(owner_id, meta.box_id) / meta.hash_sha256
    if not blob_path.exists():
        return None 
        
    # unencrypted path assumed for adapter operations 
    return open(blob_path, "rb") 
    
def finalize_put(env, tmp_path, filename):
    # import tmp file into Storage + DB in default box

    if not check_permission(env, env["box_id"], "write"):
        raise AccessDeniedError("You do not have write permission for this box.")

    db = env["db"]
    # We need to find the true owner of the box to store the file in their folder
    bm = BoxModel(db)
    box = bm.get(env["box_id"])
    if not box:
        raise BoxNotFoundError("The target box does not exist.")
    box_owner_id = box["user_id"]

    # Store the blob in the owner's storage path
    info = env["storage"].put(box_owner_id, env["box_id"], tmp_path)

    um = UserModel(db)
    fm = FileModel(db)

    # The file metadata is created by the uploader (env['user_id'])
    # but the physical file is owned by the box owner
    uploader = um.get(env["user_id"])
    meta = FileMetadata(
        user_id=box_owner_id,  # The file is owned by the box owner
        box_id=env["box_id"],
        filename=filename,
        original_path=str(tmp_path),
        size=info["size"],
        hash_sha256=info["hash"],
        owner=uploader["username"],  # Record who uploaded it
        tags=[],
    )
    fm.create(meta)

    # Quota update should affect the box owner
    owner_user = um.get(box_owner_id)
    um.update_quota(box_owner_id, owner_user["used_bytes"] + meta.size)

    return meta.file_id


def delete_filename(env, filename):
    # soft delete by filename and update quota

    if not check_permission(env, env["box_id"], "write"):
        raise AccessDeniedError("You do not have write permission for this box.")


    m = find_by_filename(env, filename)
    if not m:
        return False

    fm = FileModel(env["db"])
    fm.delete(m.file_id, soft=True)

    # Quota update should affect the box owner
    box_owner_id = m.user_id
    owner_user = UserModel(env["db"]).get(box_owner_id)
    if owner_user:
        used = max(0, owner_user["used_bytes"] - m.size)
        UserModel(env["db"]).update_quota(box_owner_id, used)
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

# TODO: Add a permission check to share_box as well,
# so only 'admin' level users can re-share a box.
def share_box(env, box_name: str, share_with_username: str, permission: str) -> str:
    """Shares a box with another user."""
    db = env["db"]
    user_id = env["user_id"]
    bm = BoxModel(db)
    um = UserModel(db)
    bsm = BoxShareModel(db)

    try:
        user_boxes = bm.list_by_user(user_id)
        box_to_share = next((box for box in user_boxes if box["box_name"] == box_name), None)
        if not box_to_share:
            raise BoxNotFoundError(f"Box '{box_name}' not found for the current user.")

        target_user_data = um.get_by_username(share_with_username)
        if not target_user_data:
            raise UserNotFoundError(f"User '{share_with_username}' not found.")
        shared_with_user_id = target_user_data["user_id"]

        if user_id == shared_with_user_id:
            raise ValueError("You cannot share a box with yourself.")

        if permission not in ["read", "write", "admin"]:
            raise ValueError(f"Invalid permission level: {permission}")

        # Delete existing share if it exists to update it
        existing_shares = bsm.list_by_box(box_to_share["box_id"])
        for share in existing_shares:
            if share["shared_with_user_id"] == shared_with_user_id:
                bsm.delete(share["share_id"])

        # Create new share
        share = BoxShare(
            box_id=box_to_share["box_id"],
            shared_by_user_id=user_id,
            shared_with_user_id=shared_with_user_id,
            permission_level=permission,
        )
        bsm.create(share)
        bm.set_shared(box_to_share["box_id"], True)

        return f"OK: Successfully shared box '{box_name}' with '{share_with_username}' with '{permission}' permissions.\n"

    except (BoxNotFoundError, UserNotFoundError, ValueError) as e:
        return f"ERROR: {e}\n"
    except Exception as e:
        return f"ERROR: An unexpected error occurred: {e}\n"


def list_available_users(env) -> str:
    """Lists all users available to share with."""
    db = env["db"]
    current_user_id = env["user_id"]
    um = UserModel(db)
    try:
        users = um.list_all()
        # Filter out the current user
        available_users = [user for user in users if user["user_id"] != current_user_id]
        if not available_users:
            return "No other users available to share with.\n"

        response_lines = ["Available users:"]
        for user in available_users:
            response_lines.append(f"- {user['username']}")

        return "\n".join(response_lines) + "\n"
    except Exception as e:
        return f"ERROR: Could not retrieve user list: {e}\n"


def list_shared_with_user(env) -> str:
    """Lists boxes that have been shared with the current user."""
    db = env["db"]
    user_id = env["user_id"]
    bsm = BoxShareModel(db)
    bm = BoxModel(db)
    um = UserModel(db)

    try:
        # Get all share records where this user is the recipient
        all_shares = bsm.list_by_user(user_id)
        recipient_shares = [s for s in all_shares if s['shared_with_user_id'] == user_id]

        if not recipient_shares:
            return "No boxes have been shared with you.\n"

        response_lines = ["Boxes shared with you:"]
        for share in recipient_shares:
            box = bm.get(share['box_id'])
            owner = um.get(share['shared_by_user_id'])

            if box and owner:
                owner_username = owner['username']
                permission = share['permission_level']
                line = (
                    f"- BOX_ID: {box['box_id']}\n"
                    f"  BOX_NAME: {owner_username}/{box['box_name']}\n"
                    f"            (Permission: {permission})"
                )
                response_lines.append(line)

        return "\n".join(response_lines) + "\n"
    except Exception as e:
        return f"ERROR: Could not retrieve shared boxes: {e}\n"
