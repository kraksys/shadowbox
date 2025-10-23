from queue import Queue
from .connection import DatabaseConnection


class ConnectionPool:
    # fixed size pool
    def __init__(self, db_path="./shadowbox.db", size=4):
        self.queue = Queue(maxsize=size)
        self.all = []
        for _ in range(size):
            db = DatabaseConnection(db_path)
            db.initialize()
            self.queue.put(db)
            self.all.append(db)

    def acquire(self):
        # borrow a connection
        return self.queue.get()

    def release(self, db):
        # return a connection
        self.queue.put(db)

    def close(self):
        while not self.queue.empty():
            self.queue.get_nowait()
        for db in self.all:
            db.close()
        self.all = []
