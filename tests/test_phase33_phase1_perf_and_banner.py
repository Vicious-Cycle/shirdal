import asyncio
import contextlib
import io
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from shirdal import Shirdal, command
from shirdal.core.events import ChatRef, EventType, MessageEvent, UpdateEvent, UserRef
from shirdal.core.mock_adapter import MockAdapter
from shirdal.mtproto import crypto as mt_crypto


class TestPhase1PerfAndBanner(unittest.TestCase):
    def test_dispatcher_isolates_context_across_multiple_routes(self) -> None:
        async def run() -> None:
            adapter = MockAdapter()
            bot = Shirdal(adapter, anti_flood=False, startup_banner=False)
            seen: list[tuple[str | None, list[str]]] = []

            @bot.on(command("ping", prefix="/"))
            async def h1(ctx) -> None:
                seen.append((ctx.command, list(ctx.args)))

            @bot.on(command("other", prefix="/"))
            async def h_no_match(ctx) -> None:
                seen.append(("NOPE", []))

            @bot.on()
            async def h2(ctx) -> None:
                seen.append((ctx.command, list(ctx.args)))

            msg = MessageEvent(
                id=1,
                chat=ChatRef(id=10, type="private"),
                sender=UserRef(id=20),
                text="/ping hello world",
                is_outgoing=False,
            )
            await bot.dispatcher.dispatch(UpdateEvent(type=EventType.NEW_MESSAGE, message=msg), adapter)
            await asyncio.sleep(0.05)
            self.assertEqual(seen, [("ping", ["hello", "world"]), (None, [])])

        asyncio.run(run())

    def test_startup_banner_prints_without_logging_config_and_measures_ping(self) -> None:
        async def run() -> None:
            class FakePingAdapter(MockAdapter):
                async def invoke(self, method: str, **params):
                    if method == "getMe":
                        await asyncio.sleep(0.005)
                        return {"username": "shirdal_test_bot"}
                    return await super().invoke(method, **params)

            adapter = FakePingAdapter()
            bot = Shirdal(adapter, anti_flood=False, startup_banner=True)
            buf = io.StringIO()
            root_logger = logging.getLogger("shirdal")
            old_level = root_logger.level
            root_logger.setLevel(logging.WARNING)
            try:
                with contextlib.redirect_stdout(buf):
                    banner = await bot._log_startup_info()
            finally:
                root_logger.setLevel(old_level)

            out = buf.getvalue().strip()
            self.assertIn("@shirdal_test_bot", out)
            self.assertIn("ping:", out)
            self.assertIn("loop:", out)
            self.assertIn("json:", out)
            self.assertIn("crypto:", out)
            self.assertEqual(out, banner)

        asyncio.run(run())

    def test_crypto_uses_shircrypt_fused_packet_when_available(self) -> None:
        auth_key = bytes(range(256))
        ak = mt_crypto.AuthKey(auth_key)
        calls: list[str] = []

        fake_shircrypt = SimpleNamespace(
            BACKEND="rust",
            __version__="1.0.3",
            ige256_encrypt=lambda d, k, iv: d,
            ige256_decrypt=lambda d, k, iv: d,
            compute_msg_key=lambda a, p, from_client=True: b"\x01" * 16,
            mtproto2_kdf=lambda a, m, from_client=True: (b"\x02" * 32, b"\x03" * 32),
            mtproto2_encrypt_packet=lambda a, p, from_client=True: (
                calls.append("enc") or (b"\xAA" * 16, b"\xBB" * len(p))
            ),
            mtproto2_decrypt_packet=lambda a, m, c, from_client=False: (
                calls.append("dec") or b"\xCC" * len(c)
            ),
        )

        with patch.object(mt_crypto, "_shircrypt", fake_shircrypt):
            pkt = ak.encrypt_packet(b"hello-world", from_client=True)
            self.assertTrue(pkt.startswith(ak.key_id_bytes + b"\xAA" * 16))
            pt = ak.decrypt_packet(pkt, from_client=False)
            self.assertEqual(len(pt), len(pkt) - 24)
            self.assertEqual(calls, ["enc", "dec"])


if __name__ == "__main__":
    unittest.main()
