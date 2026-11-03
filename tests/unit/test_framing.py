import socket
import struct
import unittest

from collab.common.errors import ProtocolError
from collab.common.framing import encode_frame, recv_frame
from collab.common.protocol import MAX_FRAME_SIZE


class FramingTests(unittest.TestCase):
    def test_frame_round_trip(self):
        left, right = socket.socketpair()
        try:
            left.sendall(encode_frame(b"payload"))
            self.assertEqual(recv_frame(right), b"payload")
        finally:
            left.close()
            right.close()

    def test_rejects_empty_or_oversized_frame(self):
        with self.assertRaises(ProtocolError):
            encode_frame(b"")
        with self.assertRaises(ProtocolError):
            encode_frame(b"x" * (MAX_FRAME_SIZE + 1))

    def test_rejects_oversized_received_frame(self):
        left, right = socket.socketpair()
        try:
            left.sendall(struct.pack("!I", MAX_FRAME_SIZE + 1))
            with self.assertRaises(ProtocolError):
                recv_frame(right)
        finally:
            left.close()
            right.close()

    def test_raises_eof_on_truncated_frame(self):
        left, right = socket.socketpair()
        try:
            left.sendall(struct.pack("!I", 4) + b"ab")
            left.close()
            with self.assertRaises(EOFError):
                recv_frame(right)
        finally:
            right.close()


if __name__ == "__main__":
    unittest.main()
