import tempfile
import unittest
from pathlib import Path

from collab.server.user_store import UserStore


class UserStoreTests(unittest.TestCase):
    def test_create_authenticate_and_reject_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            users = UserStore(Path(directory) / "users.sqlite3")
            self.assertTrue(users.create_user("alice", "correct horse battery"))
            self.assertFalse(users.create_user("alice", "another password"))
            self.assertTrue(users.authenticate("alice", "correct horse battery"))
            self.assertFalse(users.authenticate("alice", "wrong password"))
            self.assertFalse(users.authenticate("unknown", "wrong password"))


if __name__ == "__main__":
    unittest.main()
