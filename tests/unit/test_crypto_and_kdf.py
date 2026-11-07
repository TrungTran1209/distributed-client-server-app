import sqlite3
import tempfile
import unittest
from pathlib import Path

from collab.common.crypto import (
    DEFAULT_SCRYPT_PARAMS,
    ScryptParams,
    derive_password,
    needs_rehash,
    verify_password,
)
from collab.server.user_store import UserStore


class CryptoAndKdfTests(unittest.TestCase):
    def test_scrypt_params_round_trip_spec(self):
        params = ScryptParams(version=1, n=16384, r=8, p=1, dklen=32)
        spec = params.to_spec()
        self.assertEqual(spec, "scrypt$v=1$n=16384$r=8$p=1$dklen=32")
        parsed = ScryptParams.from_spec(spec)
        self.assertEqual(parsed, params)

    def test_scrypt_params_rejects_invalid_values_and_specs(self):
        with self.assertRaises(ValueError):
            ScryptParams(n=1000)  # not a power of two
        with self.assertRaises(ValueError):
            ScryptParams(dklen=8)  # too short
        with self.assertRaises(ValueError):
            ScryptParams(salt_len=8)  # salt too short
        for bad_spec in ("", "pbkdf2$v=1$n=16384$r=8$p=1$dklen=32", "scrypt$v=1$n=notint", "scrypt$v=0$n=16384$r=8$p=1$dklen=32"):
            with self.subTest(spec=bad_spec), self.assertRaises(ValueError):
                ScryptParams.from_spec(bad_spec)

    def test_derive_and_verify_with_unique_salts_and_custom_params(self):
        custom = ScryptParams(version=2, n=4096, r=8, p=1, dklen=32)
        salt1, digest1 = derive_password("super secret passphrase", params=custom)
        salt2, digest2 = derive_password("super secret passphrase", params=custom)
        self.assertNotEqual(salt1, salt2)
        self.assertNotEqual(digest1, digest2)
        self.assertTrue(verify_password("super secret passphrase", salt1, digest1, params=custom))
        self.assertFalse(verify_password("wrong passphrase", salt1, digest1, params=custom))
        self.assertFalse(verify_password("super secret passphrase", b"", digest1, params=custom))

    def test_needs_rehash_detects_outdated_or_missing_spec(self):
        older = ScryptParams(version=1, n=4096, r=8, p=1, dklen=32)
        target = DEFAULT_SCRYPT_PARAMS
        self.assertTrue(needs_rehash(None, target))
        self.assertTrue(needs_rehash("invalid-spec", target))
        self.assertTrue(needs_rehash(older.to_spec(), target))
        self.assertFalse(needs_rehash(target.to_spec(), target))

    def test_user_store_persists_kdf_params_and_transparently_upgrades_on_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "users.sqlite3"
            weak_params = ScryptParams(version=1, n=4096, r=8, p=1, dklen=32)
            store_v1 = UserStore(db_path, kdf_params=weak_params)
            self.assertTrue(store_v1.create_user("alice", "correct horse battery"))
            self.assertEqual(store_v1.get_user_kdf_spec("alice"), weak_params.to_spec())

            # Upgrade server KDF policy and verify transparent rehash on login
            strong_params = ScryptParams(version=2, n=16384, r=8, p=1, dklen=32)
            store_v2 = UserStore(db_path, kdf_params=strong_params)
            self.assertFalse(store_v2.authenticate("alice", "wrong password"))
            self.assertEqual(store_v2.get_user_kdf_spec("alice"), weak_params.to_spec())

            self.assertTrue(store_v2.authenticate("alice", "correct horse battery"))
            self.assertEqual(store_v2.get_user_kdf_spec("alice"), strong_params.to_spec())
            self.assertTrue(store_v2.authenticate("alice", "correct horse battery"))

    def test_user_store_migrates_legacy_sqlite_table_without_kdf_params_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.sqlite3"
            salt, digest = derive_password("legacy password 123")
            with sqlite3.connect(db_path) as db:
                db.execute(
                    """CREATE TABLE users (
                        username TEXT PRIMARY KEY COLLATE BINARY,
                        salt BLOB NOT NULL,
                        password_hash BLOB NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )"""
                )
                db.execute(
                    "INSERT INTO users(username, salt, password_hash) VALUES (?, ?, ?)",
                    ("bob", salt, digest),
                )

            migrated = UserStore(db_path)
            self.assertEqual(migrated.get_user_kdf_spec("bob"), DEFAULT_SCRYPT_PARAMS.to_spec())
            self.assertTrue(migrated.authenticate("bob", "legacy password 123"))


if __name__ == "__main__":
    unittest.main()
