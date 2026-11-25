import inspect
import sys
import types
import unittest

from shirdal import HydrogramAdapter, TelethonAdapter


class TestPhase19BotToken(unittest.IsolatedAsyncioTestCase):
    def test_adapters_expose_bot_token_parameter(self) -> None:
        self.assertIn("bot_token", inspect.signature(TelethonAdapter.__init__).parameters)
        self.assertIn("bot_token", inspect.signature(HydrogramAdapter.__init__).parameters)

    async def test_telethon_adapter_passes_bot_token_on_connect(self) -> None:
        started_with: dict[str, object] = {}

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def on(self, _event: object):
                return lambda fn: fn

            def is_connected(self) -> bool:
                return True

            async def start(self, **kwargs: object) -> None:
                started_with.update(kwargs)

            async def disconnect(self) -> None:
                pass

        fake_telethon = types.ModuleType("telethon")
        fake_telethon.TelegramClient = FakeClient  # type: ignore[attr-defined]
        fake_events = types.SimpleNamespace(
            NewMessage=lambda: object(),
            MessageEdited=lambda: object(),
            MessageDeleted=lambda: object(),
        )
        fake_telethon.events = fake_events  # type: ignore[attr-defined]
        fake_sessions = types.ModuleType("telethon.sessions")
        fake_sessions.StringSession = lambda s: s  # type: ignore[attr-defined]

        prev = {k: sys.modules.get(k) for k in ("telethon", "telethon.sessions")}
        sys.modules["telethon"] = fake_telethon
        sys.modules["telethon.sessions"] = fake_sessions
        try:
            adapter = TelethonAdapter("bot", 123, "hash", bot_token="123:ABC")
            await adapter.connect()
            self.assertEqual(started_with, {"bot_token": "123:ABC"})
        finally:
            for k, v in prev.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    async def test_hydrogram_adapter_passes_bot_token_to_client(self) -> None:
        captured_kwargs: dict[str, object] = {}

        class FakeClient:
            def __init__(self, _name: str, **kwargs: object) -> None:
                captured_kwargs.update(kwargs)

            def on_message(self):
                return lambda fn: fn

            def on_edited_message(self):
                return lambda fn: fn

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        fake_hydro = types.ModuleType("hydrogram")
        fake_hydro.Client = FakeClient  # type: ignore[attr-defined]
        prev = sys.modules.get("hydrogram")
        sys.modules["hydrogram"] = fake_hydro
        try:
            HydrogramAdapter("bot", 123, "hash", bot_token="999:XYZ")
            self.assertEqual(captured_kwargs.get("bot_token"), "999:XYZ")
        finally:
            if prev is None:
                sys.modules.pop("hydrogram", None)
            else:
                sys.modules["hydrogram"] = prev
