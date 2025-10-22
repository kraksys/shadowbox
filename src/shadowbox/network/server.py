"""
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

server.py [shared_dir] [port]

Default shared_dir = ./shared_dir
Default port = 9999
"""
import keyboard
import os
import socket
import threading
import sys
from zeroconf import Zeroconf, ServiceInfo

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

def handle_client(conn, addr, shared_dir):
    """Handle a single client connection."""
    print(f"[+] Connection from {addr}")
    conn.settimeout(10.0) # The idea is to open a new connection for every action so 10s is enough
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
            files = os.listdir(shared_dir)
            response = ""
            for file in files:
                if os.path.isdir(os.path.join(shared_dir, file)):
                    extra_files = os.listdir(os.path.join(shared_dir, file))
                    response = response + "\n" + file + " (dir)" + "\n | " + "\n | ".join(extra_files)
                else:
                    response = response + "\n" + file

            conn.sendall(response.encode())
            print(f"Sent file list ({len(files)} entries)")

        elif line.upper().startswith("GET "):
            # TODO: it needs to be able to get files from inside other directories and create the given directory
            # I am not doing this before I talk with the db team about how to mange this
            # so far it works if you only want to access the file and read for it
            # example: python client.py [dir_name]/[nested_file] [name_of_file_to_be_stored]
            # This will take the contents of the nested file and save them to a new file (IT CAN'T CREATE DIR).
            # example WON'T WORK: python client.py [dir_name]/[nested_file]

            _, file_name = line.split(" ", 1)
            filepath = os.path.join(shared_dir, file_name)

            # locking the file
            f_lock = get_file_lock(filepath)
            acquired = f_lock.acquire(timeout=10.0)
            # the timeout could be an issue for big files but 10 sec should be good enough
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
                        # remember the user can still ask for [folder_name]/[file_from_the_folder]
                        msg = f"ERROR: File not found: {file_name}\n"
                        conn.sendall(msg.encode())
                        print(f"File not found: {file_name}")
                    else:
                        with open(filepath, "rb") as f:
                            while True:
                                chunk = f.read(8192)
                                if not chunk:
                                    break
                                conn.sendall(chunk)
                        print(f"Sent file: {file_name}")
                finally:
                    f_lock.release()


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

                filepath = os.path.join(shared_dir, file_name)
                tmp_path = filepath + ".tmp"

                # Lock the target file to avoid races with GET/DELETE/PUT
                f_lock = get_file_lock(os.path.realpath(filepath))
                acquired = f_lock.acquire(timeout=10.0)
                if not acquired:
                    conn.sendall(b"ERROR: Could not acquire file lock\n")
                    print(f"PUT failed (lock busy): {file_name}")
                    return

                try:
                    # Ensure parent directory exists
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)

                    # Tell the client to start sending bytes
                    conn.sendall(b"READY\n")

                    # Read exactly total_size bytes
                    remaining = total_size
                    with open(tmp_path, "wb") as out_f:
                        while remaining > 0:
                            chunk = conn.recv(min(8192, remaining))
                            if not chunk:
                                raise IOError("connection closed before all bytes received")
                            out_f.write(chunk)
                            remaining -= len(chunk)

                    # Atomic move into place (avoids partial file visibility)
                    os.replace(tmp_path, filepath)
                    conn.sendall(f"OK: Uploaded {file_name}\n".encode())
                    print(f"Uploaded file: {file_name} ({total_size} bytes)")

                except Exception as e:
                    # Clean up tmp file on failure
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

            filepath = os.path.join(shared_dir, file_name)
            if not os.path.exists(filepath):
                msg = f"ERROR: File not found: {file_name}\n"
                conn.sendall(msg.encode())
                print(f"DELETE failed, not found: {file_name}")
                return

            # TODO: either make a new option to delete directories or delete this, but maybe add a warning or something
            # This can be turned back into an error
            # if os.path.isdir(filepath):
            #     msg = f"ERROR: Not a file: {file_name}\n"
            #     conn.sendall(msg.encode())
            #     print(f"DELETE failed, is a directory: {file_name}")
            #     return

            try:
                if os.path.isdir(filepath):
                    delete_path(filepath)
                    # os.removedirs(filepath) # this can remove only empty dir
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
            msg = "ERROR: Unknown command\n"
            conn.sendall(msg.encode())


    except socket.timeout:
        print(f"Timeout from {addr}")
    except Exception as e:
        print(f"Error handling {addr}: {e}")
    finally:
        conn.close()
        print(f"[-] Disconnected {addr}")

def start_tcp_server(shared_dir, port):
    """Start a simple threaded TCP server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    s.listen(5)
    print(f"TCP server listening on port {port}, serving '{shared_dir}'")
    while True:
        if keyboard.is_pressed('q'):
            print("end")
            break

        else:
            conn, addr = s.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr, shared_dir), daemon=True)
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


# Main entry point
def main():
    shared_dir = sys.argv[1] if len(sys.argv) > 1 else "./shared_dir"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9999
    name = f"FileServer-{socket.gethostname()}"

    if not os.path.exists(shared_dir):
        # This will make a new empty dir if we give it a non-existent one
        # We may need to remove this, because it can cause us issues in the future
        os.makedirs(shared_dir)

    zeroconf, info = advertise_service(name, port)

    try:
        start_tcp_server(shared_dir, port)
    except KeyboardInterrupt: # we can trigger this only while the server is starting
        print("\nShutting down...")
    finally:
        print("Unregistering Zeroconf service...")
        zeroconf.unregister_service(info)
        zeroconf.close()


if __name__ == "__main__":
    main()
