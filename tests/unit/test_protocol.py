import unittest
import uuid

from collab.common.errors import ProtocolError
from collab.common.protocol import (
    MessageType, decode_message, encode_message, make_message, normalize_username,
)


class ProtocolTests(unittest.TestCase):
    def test_encode_decode_envelope(self):
        message = make_message(MessageType.PING, request_id=str(uuid.uuid4()))
        self.assertEqual(decode_message(encode_message(message)), message)

    def test_rejects_wrong_version_and_missing_request_id(self):
        with self.assertRaises(ProtocolError):
            encode_message({"v": 2, "type": "ping", "request_id": str(uuid.uuid4())})
        with self.assertRaises(ProtocolError):
            encode_message({"v": 1, "type": "ping"})

    def test_rejects_invalid_uuid(self):
        with self.assertRaises(ProtocolError):
            encode_message({"v": 1, "type": "hello", "request_id": "not-a-uuid"})

    def test_normalizes_unicode_username(self):
        self.assertEqual(normalize_username("e\u0301lodie"), "élodie")

    def test_rejects_invalid_username(self):
        for username in ("", ".", "..", "name with space", "a" * 33):
            with self.subTest(username=username), self.assertRaises(ProtocolError):
                normalize_username(username)


if __name__ == "__main__":
    unittest.main()
