"""
### (Test Mode)

LAN file-sharing server:
- Advertises itself with Zeroconf (_shadowbox._tcp.local.)
- Serves a simple line-oriented protocol:

    LIST
    -> sends a newline-separated list of filenames, then closes

    GET <filename>
    -> streams that file's bytes, then closes

    PUT <filename> <size>
    -> server replies READY
    -> client sends exactly <size> bytes; server writes file atomically and replies OK or ERROR

    DELETE <filename>
    -> server deletes the file if exists and replies OK or ERROR

    LIST_BOXES
    -> sends a newline-separated list of available boxes for the user

    SHARE_BOX <box_name> <share_with_username> [permission]
    -> shares a box with another user

    LIST_AVAILABLE_USERS
    -> lists all users available for sharing

server.py [shared_dir] [port]

Default shared_dir = ./shared_dir
Default port = 9999

### (Core Mode) - Normal operation
    Args: --db, --storage-root, --username

    Usage:
        python -m shadowbox.network.server --mode test --shared-dir ./shared_dir --port 9999
        python -m shadowbox.network.server --mode core --db ./shadowbox.db --storage-root ~/.shdwbox --username bob --port 9999
"""
import json
import os
import socket
import threading
import sys
import argparse
from zeroconf import Zeroconf, ServiceInfo

from .adapter import init_env, format_list, open_for_get, finalize_put, delete_filename, select_box, list_boxes, share_box, list_available_users, list_shared_with_user

SERVICE_TYPE = "_shadowbox._tcp.local."
file_locks = {}
file_locks_lock = threading.Lock()


def get_file_lock(path):
    """Return a Lock object for a given path."""
    with file_locks_lock:
        lock = file_locks.get(path)
        if lock is None:
            lock = threading.Lock()
            file_locks[path] = lock
        return lock


def delete_path(path):
    """Delete a file or directory (even non-empty) using only os."""
    if not os.path.exists(path):
        return  # Nothing to delete

    if os.path.isfile(path) or os.path.islink(path):
        os.remove(path)  # Delete file or symbolic link
    elif os.path.isdir(path):
        # Recursively delete directory contents
        for entry in os.listdir(path):
            entry_path = os.path.join(path, entry)
            delete_path(entry_path)
        os.rmdir(path)  # Delete the now-empty directory


def get_local_ip():
    """A trick to get the current IP using a UDP socket."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def send_json(conn, data):
    """Helper to send a python dict/list as a newline-terminated JSON string."""
    try:
        payload = json.dumps(data)
        conn.sendall((payload + "\n").encode())
    except Exception as e:
        print(f"Error sending JSON: {e}")

def handle_client(conn, addr, context):
    """Handle a single client connection."""
    print(f"[+] Connection from {addr}")
    conn.settimeout(10.0)  # The idea is to open a new connection for every action so 10s is enough
    try:
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(1024)
            if not chunk:
                break
            data += chunk
        line = data.decode().strip()
        print(f"Received command: {line} from {addr}")

        if line.upper() == "LIST":
            # TODO: make a tree form the inside directories, preferably recursively
            # so far it works only if the depth is 1
            if context["mode"] == "test":
                shared_dir = context["shared_dir"]
                files = os.listdir(shared_dir)
                response = ""
                for file in files:
                    if os.path.isdir(os.path.join(shared_dir, file)):
                        extra_files = os.listdir(os.path.join(shared_dir, file))
                        response = (
                            response + "\n" + file + " (dir)" + "\n | " + "\n | ".join(extra_files)
                        )
                    else:
                        response = response + "\n" + file
                    conn.sendall(response.encode())
                    print(f"Sent file list ({len(files)} entries)")
            else:
                env = context["env"]
                response = format_list(env)
                conn.sendall(response.encode())
                print("Sent file list (core mode)")

        elif line.upper().startswith("BOX "):
            if context["mode"] == "test":
                conn.sendall(b"ERROR: BOX unsupported in test mode\n")
            else:
                _, box_name = line.split(" ", 1)
                env = context["env"]
                try:
                    box = select_box(env, box_name)
                    msg = f"OK: Selected box '{box_name}' ({box['box_id']})\n"
                    conn.sendall(msg.encode())
                    print(f"Selected box {box_name} -> {box['box_id']}")
                except Exception as e:
                    msg = f"ERROR: Could not select box: {e}\n"
                    conn.sendall(msg.encode())
        
        elif line.upper().startswith("GET "):
            # TODO: it needs to be able to get files from inside other directories and create the given directory
            # I am not doing this before I talk with the db team about how to mange this
            # so far it works if you only want to access the file and read for it
            # example: python client.py [dir_name]/[nested_file] [name_of_file_to_be_stored]
            # This will take the contents of the nested file and save them to a new file (IT CAN'T CREATE DIR).
            # example WON'T WORK: python client.py [dir_name]/[nested_file]

            _, file_name = line.split(" ", 1)
            if context["mode"] == "test":
                shared_dir = context["shared_dir"]
                filepath = os.path.join(shared_dir, file_name)

                f_lock = get_file_lock(filepath)
                acquired = f_lock.acquire(timeout=10.0)
                if not acquired:
                    msg = f"ERROR: Could not acquire file lock for: {file_name}\n"
                    try:
                        conn.sendall(msg.encode())
                    except Exception:
                        pass 
                    print(f"GET failed (lock busy): {file_name}")
                else: 
                    try:
                        if not os.path.isfile(filepath):
                            msg = f"ERROR: File Not Found: {file_name}\n"
                            conn.sendall(msg.encode())
                            print(f"File not found (test): {file_name}")
                        else: 
                            with open(filepath, "rb") as f:
                                while True:
                                    chunk = f.read(8192)
                                    if not chunk: 
                                        break
                                    conn.sendall(chunk)
                            print(f"Sent file (test): {file_name}")
                    finally:
                        f_lock.release()
            else:
                env = context["env"]
                f = open_for_get(env, file_name)
                if not f: 
                    msg = f"ERROR: File Not Found: {file_name}\n"
                    conn.sendall(msg.encode())
                    print(f"File not found: {file_name}")
                else: 
                    with f:
                        while True:
                            chunk = f.read(8192)
                            if not chunk:
                                break
                            conn.sendall(chunk)
                    print(f"Sent file: {file_name}")

            # No need to set filepath here; handled per-branch above

        elif line.upper().startswith("PUT "):
            # IT WORKS!!!!!
            # it can even create folders if the user gives a nested file name
            # example: python client.py put file dir/nested_file
            parts = line.split(" ", 2)
            if len(parts) < 3:
                conn.sendall(b"ERROR: PUT requires filename and size\n")
                print("PUT rejected: missing args")
            else:
                _, file_name, size_str = parts
                try:
                    total_size = int(size_str)
                    if total_size < 0:
                        raise ValueError("negative size")
                except Exception:
                    conn.sendall(b"ERROR: Invalid size\n")
                    print(f"PUT rejected: invalid size '{size_str}'")
                    return

                if context["mode"] == "test":
                    shared_dir = context["shared_dir"]
                    filepath = os.path.join(shared_dir, file_name)
                    tmp_path = filepath + ".tmp"
                    f_lock = get_file_lock(os.path.realpath(filepath))
                    acquired = f_lock.acquire(timeout=10.0)
                    if not acquired:
                        conn.sendall(b"ERROR: Could not acquire file lock\n")
                        print(f"PUT failed (lock busy): {file_name}")
                        return 
                    try:
                        os.makedirs(os.path.dirname(filepath), exist_ok=True)
                        conn.sendall(b"READY\n")
                        remaining = total_size 
                        with open(tmp_path, "wb") as out_f:
                            while remaining > 0:
                                chunk = conn.recv(min(8192, remaining))
                                if not chunk:
                                    raise IOError("connection closed before all bytes received")
                                out_f.write(chunk)
                                remaining -= len(chunk)
                        os.replace(tmp_path, filepath)
                        conn.sendall(f"OK: Uploaded {file_name}\n".encode())
                        print(f"Uploaded file: {file_name} ({total_size} bytes)")
                    except Exception as e: 
                        try:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                        except Exception:
                            pass 
                        msg = f"ERROR: Upload failed: {e}\n"
                        try:
                            conn.sendall(msg.encode())
                        except Exception:
                            pass 
                        print(f"Upload failed for {file_name}: {e}")
                    finally:
                        f_lock.release()
                else:
                    env = context["env"]
                    user_root = str(env["storage"].user_root(env["user_id"]))
                    incoming_dir = os.path.join(user_root, "incoming")
                    os.makedirs(incoming_dir, exist_ok=True)
                    filepath = os.path.join(incoming_dir, file_name)
                    tmp_path = filepath + ".tmp"

                    f_lock = get_file_lock(os.path.realpath(filepath))
                    acquired = f_lock.acquire(timeout=10.0)
                    if not acquired:
                        conn.sendall(b"ERROR: Could not acquire file lock\n")
                        print(f"PUT failed (core, lock busy): {file_name}")
                        return 

                    try: 
                        conn.sendall(b"READY\n")
                        remaining = total_size 
                        with open(tmp_path, "wb") as out_f:
                            while remaining > 0:
                                chunk = conn.recv(min(8192, remaining))
                                if not chunk: 
                                    raise IOError("connection closed before all bytes received")
                                out_f.write(chunk)
                                remaining -= len(chunk) 
                        finalize_put(env, tmp_path, file_name) 
                        try:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                        except Exception:
                            pass 
                        conn.sendall(f"OK: Uploaded {file_name}\n".encode())
                        print(f"Uploaded file: {file_name} ({total_size} bytes)")
                    except Exception as e:
                        try: 
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                        except Exception:
                            pass 
                        msg = f"ERROR: Upload failed: {e}\n"
                        try:
                            conn.sendall(msg.encode())
                        except Exception:
                            pass 
                        print(f"Upload failed for {file_name}: {e}")
                    finally:
                        f_lock.release()

        elif line.upper().startswith("DELETE "):
            _, file_name = line.split(" ", 1)

            # TODO: either make a new option to delete directories or delete this, but maybe add a warning or something
            # This can be turned back into an error
            # if os.path.isdir(filepath):
            #     msg = f"ERROR: Not a file: {file_name}\n"
            #     conn.sendall(msg.encode())
            #     print(f"DELETE failed, is a directory: {file_name}")
            #     return


            if context["mode"] == "test":
                shared_dir = context["shared_dir"]
                filepath = os.path.join(shared_dir, file_name)
                if not os.path.exists(filepath):
                    msg = f"ERROR: File not found: {file_name}\n"
                    conn.sendall(msg.encode())
                    print(f"DELETE failed, not found: {file_name}")
                    return 
                try:
                    if os.path.isdir(filepath):
                        delete_path(filepath)
                        msg = f"OK: Deleted: {file_name}\n"
                        conn.sendall(msg.encode())
                        print(f"Deleted directory: {file_name}")
                    else: 
                        os.remove(filepath)
                        msg = f"OK: Deleted {file_name}\n"
                        conn.sendall(msg.encode())
                        print(f"Deleted file: {file_name}")
                except Exception as e:
                    msg = f"ERROR: Could not delete {file_name}: {e}\n"
                    conn.sendall(msg.encode())
                    print(f"Error deleting {file_name}: {e}")
            else: 
                env = context["env"]
                ok = delete_filename(env, file_name)
                if ok:
                    msg = f"OK: Deleted {file_name}\n"
                    conn.sendall(msg.encode())
                    print(f"Deleted: {file_name}")
                else: 
                    msg = f"ERROR: File not found: {file_name}\n"
                    conn.sendall(msg.encode())
                    print(f"DELETE failed, not found: {file_name}")


        elif line.upper() == "LIST_BOXES":
            if context["mode"] == "core":
                response = list_boxes(context["env"])
                conn.sendall(response.encode())
            else:
                conn.sendall(b"ERROR: Command only available in core mode\n")

        elif line.upper().startswith("SHARE_BOX "):
            if context["mode"] == "core":
                parts = line.strip().split(" ", 3)
                if len(parts) < 3:
                    conn.sendall(b"ERROR: SHARE_BOX requires <box_name> and <share_with_username>\n")
                else:
                    box_name = parts[1]
                    share_with_user = parts[2]
                    permission = parts[3] if len(parts) > 3 else "read"
                    response = share_box(context["env"], box_name, share_with_user, permission)
                    conn.sendall(response.encode())
            else:
                conn.sendall(b"ERROR: Command only available in core mode\n")

        elif line.upper() == "LIST_AVAILABLE_USERS":
            if context["mode"] == "core":
                response = list_available_users(context["env"])
                conn.sendall(response.encode())
            else:
                conn.sendall(b"ERROR: Command only available in core mode\n")
        elif line.upper() == "LIST_SHARED_BOXES":
            if context["mode"] == "core":
                response = list_shared_with_user(context["env"])
                conn.sendall(response.encode())
            else:
                conn.sendall(b"ERROR: Command only available in core mode\n")
        else:
            msg = "ERROR - Unknown command\n"
            conn.sendall(msg.encode())

    except socket.timeout:
        print(f"Timeout from {addr}")
    except Exception as e:
        print(f"Error handling {addr}: {e}")
    finally:
        conn.close()
        print(f"[-] Disconnected {addr}")


def start_tcp_server(context, port):
    """Start a simple threaded TCP server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    s.listen(5)
    if context["mode"] == "test":
        print(f"TCP server listening on port {port}, serving '{context['shared_dir']}'")
    else: 
        print(f"TCP server listening on port {port}, core mode (DB+Storage)")
    while True:
        conn, addr = s.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr, context), daemon=True)
        t.start()


# Zeroconf advertisement
def advertise_service(name, port):
    """Advertise this server using Zeroconf."""
    zeroconf = Zeroconf()
    local_ip = get_local_ip()
    local_ip_bytes = socket.inet_aton(local_ip)
    props = {"name": name, "version": "1.0"}

    info = ServiceInfo(
        SERVICE_TYPE,
        f"{name}.{SERVICE_TYPE}",
        addresses=[local_ip_bytes],
        port=port,
        properties=props,
        server=f"{socket.gethostname()}.local.",
    )
    zeroconf.register_service(info)
    print(f"Zeroconf service registered: {name} @ {local_ip}:{port}")
    return zeroconf, info


# Main entry point (augmented with argparse)
def main():
    parser = argparse.ArgumentParser(description="ShadowBox LAN server")
    parser.add_argument("--mode", choices=["test", "core"], default="test")
    parser.add_argument("--shared-dir", default="./shared_dir")
    parser.add_argument("--db", dest="db_path", default="./shadowbox.db")
    parser.add_argument("--storage-root", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--name", default=None)
    parser.add_argument("--no-advertise", action="store_true")

    args = parser.parse_args()

    if args.mode == "test":
        shared_dir = args.shared_dir
        if not os.path.exists(shared_dir):
            os.makedirs(shared_dir)
        context = {"mode": "test", "shared_dir": shared_dir}
    else:
        env = init_env(db_path=args.db_path, storage_root=args.storage_root, username=args.username)
        context = {"mode": "core", "env": env}

    name = args.name or f"FileServer-{socket.gethostname()}"

    if args.no_advertise:
        zeroconf = None
        info = None
    else:
        zeroconf, info = advertise_service(name, args.port)

    try:
        start_tcp_server(context, args.port)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if not args.no_advertise:
            print("Unregistering Zeroconf service...")
            try:
                zeroconf.unregister_service(info)
            except Exception:
                pass
            zeroconf.close()


if __name__ == "__main__":
    main()
