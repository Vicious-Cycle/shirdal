import unittest

from shirdal.mtproto import (
    TLDecodeError,
    TLReader,
    TLWriter,
    generate_python_module,
    pack_gzip,
    parse_tl_schema,
    unpack_gzip,
)

SAMPLE_TL_SCHEMA = """
// Sample Telegram TL snippet
---types---
inputPeerEmpty#7f3b18ea = InputPeer;
inputPeerUser#dde8a54c user_id:long access_hash:long = InputPeer;
user#20b1422 flags:# self:flags.10?true id:long access_hash:flags.0?long first_name:flags.1?string bot_info_version:flags.14?int = User;

---functions---
messages.sendMessage#983f9745 flags:# no_webpage:flags.1?true peer:InputPeer message:string random_id:long = Updates;
"""


class TestPhase26MTProtoTLCodec(unittest.TestCase):
    def test_primitive_roundtrip_and_padding(self) -> None:
        w = TLWriter()
        w.write_int(-42)
        w.write_uint(0xDEADBEEF)
        w.write_long(9_000_000_000_123)
        w.write_int128((1 << 120) + 7)
        w.write_int256((1 << 250) + 99)
        w.write_double(3.14159265)
        w.write_bool(True)
        w.write_bool(False)
        w.write_string("سلام شیر‌دال 🚀")

        # Long byte array >= 254 bytes (uses 0xfe + 3-byte length header)
        big_blob = bytes(range(256)) * 2
        w.write_bytes(big_blob)
        w.write_vector([10, 20, 30], TLWriter.write_int)

        raw = w.to_bytes()
        self.assertEqual(len(raw) % 4, 0)

        r = TLReader(raw)
        self.assertEqual(r.read_int(), -42)
        self.assertEqual(r.read_uint(), 0xDEADBEEF)
        self.assertEqual(r.read_long(), 9_000_000_000_123)
        self.assertEqual(r.read_int128(), (1 << 120) + 7)
        self.assertEqual(r.read_int256(), (1 << 250) + 99)
        self.assertAlmostEqual(r.read_double(), 3.14159265)
        self.assertTrue(r.read_bool())
        self.assertFalse(r.read_bool())
        self.assertEqual(r.read_string(), "سلام شیر‌دال 🚀")
        self.assertEqual(r.read_bytes(), big_blob)
        self.assertEqual(r.read_vector(TLReader.read_int), [10, 20, 30])
        self.assertEqual(r.remaining(), 0)

    def test_gzip_packed_and_error_handling(self) -> None:
        packed = pack_gzip(b"hello mtproto payload" * 10)
        unpacked = unpack_gzip(TLReader(packed))
        self.assertEqual(unpacked, b"hello mtproto payload" * 10)

        with self.assertRaises(TLDecodeError):
            TLReader(b"\x01\x02").read_int()

        with self.assertRaises(TLDecodeError):
            TLReader(b"\x00\x00\x00\x00").read_bool()

    def test_tl_parser_and_codegen_roundtrip(self) -> None:
        defs = parse_tl_schema(SAMPLE_TL_SCHEMA)
        self.assertEqual(len(defs), 4)
        self.assertFalse(defs[2].is_function)
        self.assertTrue(defs[3].is_function)
        self.assertEqual(defs[2].constructor_id, 0x020B1422)

        code = generate_python_module(SAMPLE_TL_SCHEMA)
        ns: dict[str, object] = {}
        exec(code, ns)

        User = ns["User"]
        InputPeerUser = ns["InputPeerUser"]
        MessagesSendMessage = ns["MessagesSendMessage"]
        read_object = ns["read_object"]

        user = User(
            id=123456789,
            self=True,
            access_hash=987654321,
            first_name="Ali",
        )
        raw_user = user.to_bytes()
        decoded_user = read_object(TLReader(raw_user))
        self.assertEqual(decoded_user, user)
        self.assertTrue(decoded_user.self)
        self.assertIsNone(decoded_user.bot_info_version)

        req = MessagesSendMessage(
            peer=InputPeerUser(user_id=123456789, access_hash=987654321),
            message="تست MTProto",
            random_id=424242,
            no_webpage=True,
        )
        raw_req = req.to_bytes()
        decoded_req = read_object(TLReader(raw_req))
        self.assertEqual(decoded_req, req)
        self.assertTrue(decoded_req.no_webpage)
