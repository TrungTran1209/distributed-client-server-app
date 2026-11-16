import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path

from collab.common.errors import TransferError
from collab.transfer.manifest import (
    TransferManifest,
    allocate_non_colliding_path,
    compute_file_sha256,
    resolve_safe_paths,
    sanitize_filename,
)


class TransferManifestTests(unittest.TestCase):
    def test_sanitize_filename_strips_directory_components_and_normalizes_unicode(self):
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename(r"..\..\Windows\win.ini"), "win.ini")
        self.assertEqual(sanitize_filename(r"C:\Users\Alice\Documents\báo_cáo.pdf"), "báo_cáo.pdf")
        self.assertEqual(sanitize_filename("ba\u0301o_ca\u0301o.txt"), "báo_cáo.txt")

    def test_sanitize_filename_rejects_dangerous_or_reserved_names(self):
        invalid_cases = [
            "",
            "   ",
            ".",
            "..",
            "../../",
            r"C:\folder\\",
            "CON",
            "con.txt",
            "LPT1.log",
            "NUL",
            "bad*name.txt",
            "bad?name.txt",
            "bad|name.txt",
            "null\x00byte.bin",
            "line\nbreak.txt",
            "a" * 205 + ".txt",
        ]
        for candidate in invalid_cases:
            with self.subTest(candidate=candidate), self.assertRaises(TransferError) as ctx:
                sanitize_filename(candidate)
            self.assertEqual(ctx.exception.code, "invalid_filename")

    def test_manifest_from_file_handles_empty_and_multichunk_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_file = Path(tmp) / "empty.txt"
            empty_file.write_bytes(b"")
            m_empty = TransferManifest.from_file(empty_file, chunk_size=1024)
            self.assertEqual(m_empty.size, 0)
            self.assertEqual(m_empty.total_chunks, 0)
            self.assertEqual(m_empty.sha256, hashlib.sha256(b"").hexdigest())

            payload = b"0123456789abcdef" * 200  # 3200 bytes
            big_file = Path(tmp) / "sample.bin"
            big_file.write_bytes(payload)
            m_big = TransferManifest.from_file(big_file, chunk_size=1000)
            self.assertEqual(m_big.filename, "sample.bin")
            self.assertEqual(m_big.size, 3200)
            self.assertEqual(m_big.total_chunks, 4)
            self.assertEqual(m_big.expected_chunk_length(0), 1000)
            self.assertEqual(m_big.expected_chunk_length(2), 1000)
            self.assertEqual(m_big.expected_chunk_length(3), 200)
            size, digest = compute_file_sha256(big_file)
            self.assertEqual((size, digest), (3200, m_big.sha256))

    def test_manifest_from_offer_validates_bounds_and_wire_filename(self):
        tid = str(uuid.uuid4())
        valid = {
            "transfer_id": tid,
            "filename": "report.pdf",
            "size": 70000,
            "sha256": "a" * 64,
            "chunk_size": 65536,
            "total_chunks": 2,
        }
        parsed = TransferManifest.from_offer(valid)
        self.assertEqual(parsed.transfer_id, tid)
        self.assertEqual(parsed.total_chunks, 2)

        # Reject path separators directly inside wire filename
        with self.assertRaises(TransferError):
            TransferManifest.from_offer({**valid, "filename": "../escape.pdf"})

        # Reject mismatched total_chunks
        with self.assertRaises(TransferError):
            TransferManifest.from_offer({**valid, "total_chunks": 5})

        # Reject oversized file
        with self.assertRaises(TransferError) as ctx:
            TransferManifest.from_offer({**valid, "size": 10_000, "total_chunks": 1}, max_file_size=4096)
        self.assertEqual(ctx.exception.code, "file_too_large")

    def test_resolve_safe_paths_and_non_colliding_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            dl = Path(tmp) / "downloads"
            tid = str(uuid.uuid4())
            part_path, final_path = resolve_safe_paths(dl, tid, "notes.txt")
            self.assertTrue(part_path.resolve().is_relative_to(dl.resolve()))
            self.assertTrue(final_path.resolve().is_relative_to(dl.resolve()))
            self.assertTrue(part_path.name.endswith(".part"))

            # Existing file should not be overwritten
            final_path.write_text("first", encoding="utf-8")
            second = allocate_non_colliding_path(dl, "notes.txt")
            self.assertEqual(second.name, "notes (1).txt")


if __name__ == "__main__":
    unittest.main()
