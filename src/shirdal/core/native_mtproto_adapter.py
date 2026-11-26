"""Native zero-bloat MTProto 2.0 TransportAdapter built on shirdal.mtproto.

All Telegram API calls are serialized from the official schema (``mtproto/data/api.tl``)
by :mod:`shirdal.mtproto.tl_runtime`, so constructor IDs always match the declared layer.
"""

from __future__ import annotations

import asyncio
import getpass
import html.parser
import logging
import mimetypes
import re
import sqlite3
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shirdal.core.adapter import AdapterError, DeviceProfile, FloodWaitError
from shirdal.core.events import (
    ChatAction,
    ChatRef,
    EventType,
    MediaRef,
    MessageEvent,
    UpdateEvent,
    UserRef,
)
from shirdal.mtproto.auth import RSAPublicKey
from shirdal.mtproto.crypto import AuthKey
from shirdal.mtproto.files import FileTransferManager
from shirdal.mtproto.rsa_keys import TELEGRAM_RSA_KEYS
from shirdal.mtproto.sender import MTProtoSender
from shirdal.mtproto.session import MTProtoRPCError, MTProtoSessionState
from shirdal.mtproto.srp import compute_check
from shirdal.mtproto.tl_runtime import TLObject, get_schema, random_long
from shirdal.mtproto.updates import PeerCache, UpdateGapAction, UpdateStateTracker

_FLOOD_RE = re.compile(r"(?:FLOOD_WAIT|SLOWMODE_WAIT|FLOOD_PREMIUM_WAIT)_(\d+)")
_MIGRATE_RE = re.compile(r"(PHONE|USER|NETWORK|FILE|STATS)_MIGRATE_(\d+)")
_LOG = logging.getLogger("shirdal.mtproto")

TELEGRAM_DCS: dict[int, tuple[str, int]] = {
    1: ("149.154.175.53", 443),
    2: ("149.154.167.51", 443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91", 443),
    5: ("91.108.56.130", 443),
}

_CHANNEL_OFFSET = 1_000_000_000_000
_DOWNLOAD_CHUNK = 512 * 1024
_BIG_FILE = 10 * 1024 * 1024
_MEDIA_CACHE_SIZE = 2000


class RPCError(AdapterError):
    """Telegram RPC error with code and message (e.g. 400 PEER_ID_INVALID)."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"MTProto RPC error [{code}]: {message}")


# --------------------------------------------------------------------- peer ids
def marked_id(peer: dict[str, Any]) -> int:
    """Convert a TL Peer to a Bot-API style id (user>0, chat<0, channel -100…)."""
    name = peer.get("_")
    if name == "peerUser":
        return int(peer["user_id"])
    if name == "peerChat":
        return -int(peer["chat_id"])
    if name == "peerChannel":
        return -(_CHANNEL_OFFSET + int(peer["channel_id"]))
    raise AdapterError(f"Unknown peer {peer!r}")


def split_marked_id(chat_id: int) -> tuple[str, int]:
    cid = int(chat_id)
    if cid > 0:
        return "user", cid
    if cid <= -_CHANNEL_OFFSET:
        return "channel", -cid - _CHANNEL_OFFSET
    return "chat", -cid


# -------------------------------------------------------------------- html mode
class _HTMLToEntities(html.parser.HTMLParser):
    _SIMPLE = {
        "b": "messageEntityBold",
        "strong": "messageEntityBold",
        "i": "messageEntityItalic",
        "em": "messageEntityItalic",
        "u": "messageEntityUnderline",
        "ins": "messageEntityUnderline",
        "s": "messageEntityStrike",
        "strike": "messageEntityStrike",
        "del": "messageEntityStrike",
        "code": "messageEntityCode",
        "tg-spoiler": "messageEntitySpoiler",
        "spoiler": "messageEntitySpoiler",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.entities: list[dict[str, Any]] = []
        self._stack: list[tuple[str, int, dict[str, Any] | None]] = []
        self._len = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        a = dict(attrs)
        if t == "br":
            self.handle_data("\n")
            return
        ent: dict[str, Any] | None = None
        if t in self._SIMPLE:
            ent = {"_": self._SIMPLE[t]}
        elif t == "pre":
            ent = {"_": "messageEntityPre", "language": a.get("language") or ""}
        elif t == "blockquote":
            ent = {"_": "messageEntityBlockquote", "collapsed": "expandable" in a}
        elif t == "tg-emoji" and a.get("emoji-id"):
            ent = {"_": "messageEntityCustomEmoji", "document_id": int(a["emoji-id"] or 0)}
        elif t == "a" and a.get("href"):
            ent = {"_": "messageEntityTextUrl", "url": a["href"]}
        self._stack.append((t, self._len, ent))

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == t:
                _, start, ent = self._stack.pop(i)
                length = self._len - start
                if ent is not None and length > 0:
                    if ent["_"] == "messageEntityCode" and self.entities:
                        last = self.entities[-1]
                        # <pre><code class="language-x"> collapses into pre
                        if last.get("_") == "messageEntityPre" and last["offset"] == start:
                            continue
                    ent.update(offset=start, length=length)
                    self.entities.append(ent)
                return

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        self._len += len(data.encode("utf-16-le")) // 2


def parse_html(text: str) -> tuple[str, list[dict[str, Any]]]:
    p = _HTMLToEntities()
    p.feed(text)
    p.close()
    ents = sorted(p.entities, key=lambda e: (e["offset"], -e["length"]))
    return "".join(p.parts), ents


# ------------------------------------------------------------------- persistence
class _AuthStore:
    """Persists login + update state next to the MTProto session sqlite."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS shirdal_auth (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    user_id INTEGER, is_bot INTEGER,
                    pts INTEGER, qts INTEGER, date INTEGER, seq INTEGER)"""
            )

    def load(self) -> tuple[int, bool, int, int, int, int] | None:
        if self.path is None or not self.path.exists():
            return None
        with sqlite3.connect(self.path) as conn:
            try:
                row = conn.execute(
                    "SELECT user_id, is_bot, pts, qts, date, seq FROM shirdal_auth WHERE id=1"
                ).fetchone()
            except sqlite3.OperationalError:
                return None
        if row is None or row[0] is None:
            return None
        return int(row[0]), bool(row[1]), *(int(x or 0) for x in row[2:])  # type: ignore[return-value]

    def save(self, user_id: int, is_bot: bool, st: UpdateStateTracker) -> None:
        if self.path is None:
            return
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """INSERT INTO shirdal_auth (id, user_id, is_bot, pts, qts, date, seq)
                VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET user_id=excluded.user_id, is_bot=excluded.is_bot,
                pts=excluded.pts, qts=excluded.qts, date=excluded.date, seq=excluded.seq""",
                (user_id, int(is_bot), st.pts, st.qts, st.date, st.seq),
            )


# ======================================================================= adapter
class NativeMTProtoAdapter:
    """Native MTProto 2.0 TransportAdapter implementing shirdal's TransportAdapter protocol.

    First run with ``session_path`` asks for phone number, login code and 2FA password
    (or uses ``bot_token``) and stores the session; later runs log in silently.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        *,
        session_path: str | Path | None = None,
        dc_id: int = 2,
        host: str | None = None,
        port: int = 443,
        auth_key: AuthKey | bytes | None = None,
        server_salt: int = 0,
        bot_token: str | None = None,
        phone: str | Callable[[], str] | None = None,
        code_callback: Callable[[], str] | None = None,
        password: str | Callable[[], str] | None = None,
        auto_login: bool | None = None,
        device: DeviceProfile | None = None,
        rsa_keys: list[RSAPublicKey] | None = None,
        rpc_timeout: float = 20.0,
        ping_interval: float = 30.0,
        auto_reconnect: bool = True,
    ) -> None:
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.phone = phone
        self.code_callback = code_callback
        self.password = password
        self.device = device or DeviceProfile.desktop()
        self.session_path = Path(session_path) if session_path is not None else None
        self.rsa_keys = rsa_keys or list(TELEGRAM_RSA_KEYS)
        self.rpc_timeout = float(rpc_timeout)
        self.auto_login = (
            auto_login if auto_login is not None else (self.session_path is not None or bool(bot_token))
        )
        self._ping_interval = float(ping_interval)
        self._auto_reconnect = auto_reconnect
        self._custom_host = host is not None

        loaded = MTProtoSessionState.load_sqlite(self.session_path) if self.session_path else None
        if loaded is not None:
            self.state = loaded
        else:
            dc_host, dc_port = TELEGRAM_DCS.get(dc_id, TELEGRAM_DCS[2])
            ak = auth_key if isinstance(auth_key, AuthKey) else (AuthKey(auth_key) if auth_key else None)
            self.state = MTProtoSessionState(
                dc_id=dc_id,
                host=host or dc_host,
                port=port if host else dc_port,
                auth_key=ak,
                server_salt=server_salt,
            )
        self.schema = get_schema()
        self.state.layer = self.schema.layer
        self._store = _AuthStore(self.session_path)
        self.peers = PeerCache(
            self.session_path.with_suffix(".peers.sqlite") if self.session_path else None
        )
        self.updates = UpdateStateTracker()
        self.files = FileTransferManager()

        self.self_id = 0
        self.is_bot = False
        self._authorized = False
        saved = self._store.load()
        if saved is not None:
            self.self_id, self.is_bot, pts, qts, date, seq = saved
            self.updates.pts, self.updates.qts, self.updates.date, self.updates.seq = pts, qts, date, seq
            self._authorized = True

        self._sender = self._make_sender(self.state, main=True)
        self._file_senders: dict[int, MTProtoSender] = {}
        self._queue: asyncio.Queue[UpdateEvent | None] = asyncio.Queue()
        self._connected = False
        self._diff_lock = asyncio.Lock()
        self._chat_info: dict[int, tuple[str, str | None]] = {}
        self._media: OrderedDict[tuple[int, int], dict[str, Any]] = OrderedDict()
        self._dialogs_loaded = False
        self._bg: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------ connection
    def _make_sender(self, state: MTProtoSessionState, *, main: bool) -> MTProtoSender:
        return MTProtoSender(
            state,
            rsa_keys=self.rsa_keys,
            wrap_first=self._wrap_init,
            on_update=self._on_raw_update if main else None,
            on_new_session=self._on_new_session if main else None,
            on_auth_key=self._save_session if main else None,
            ping_interval=self._ping_interval if main else 0,
            reconnect=self._auto_reconnect,
        )

    def _wrap_init(self, query: bytes) -> bytes:
        d = self.device
        init = self.schema.serialize(
            "initConnection",
            {
                "api_id": self.api_id,
                "device_model": d.device_model,
                "system_version": d.system_version,
                "app_version": d.app_version,
                "system_lang_code": d.system_lang_code,
                "lang_pack": "",
                "lang_code": d.lang_code,
                "query": query,
            },
        )
        return self.schema.serialize("invokeWithLayer", {"layer": self.schema.layer, "query": init})

    def _save_session(self) -> None:
        if self.session_path is not None and self.state.auth_key is not None:
            self.state.save_sqlite(self.session_path)

    def _save_auth(self) -> None:
        if self._authorized:
            self._store.save(self.self_id, self.is_bot, self.updates)

    @property
    def is_connected(self) -> bool:
        return self._connected and self._sender.is_connected

    @property
    def transport(self) -> Any:
        return self._sender.transport

    async def connect(self) -> None:
        if self._connected:
            return
        await self._sender.connect()
        self._connected = True
        self._save_session()
        if not self._authorized and self.auto_login:
            await self.start()
        if self._authorized:
            self._spawn(self._initial_sync())

    async def _initial_sync(self) -> None:
        try:
            if self.updates.pts == 0:
                await self._fetch_state()
            else:
                await self.sync_updates_state()
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("Initial updates sync failed: %s", exc)

    async def disconnect(self) -> None:
        self._connected = False
        for t in list(self._bg):
            t.cancel()
        await self._sender.disconnect()
        for s in self._file_senders.values():
            await s.disconnect()
        self._file_senders.clear()
        self._save_session()
        self._save_auth()
        await self._queue.put(None)

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _switch_dc(self, dc_id: int) -> None:
        _LOG.info("Migrating to DC %s", dc_id)
        await self._sender.disconnect()
        host, port = TELEGRAM_DCS[dc_id]
        self.state = MTProtoSessionState(dc_id=dc_id, host=host, port=port, layer=self.schema.layer)
        self._sender = self._make_sender(self.state, main=True)
        await self._sender.connect()
        self._save_session()

    # ---------------------------------------------------------------- invoking
    async def invoke_raw(self, tl_payload: bytes, *, _sender: MTProtoSender | None = None) -> bytes:
        if not self.is_connected:
            raise AdapterError("NativeMTProtoAdapter is not connected.")
        sender = _sender or self._sender
        try:
            return await sender.invoke(tl_payload, timeout=self.rpc_timeout)
        except MTProtoRPCError as exc:
            m = _FLOOD_RE.search(exc.message)
            if m:
                raise FloodWaitError(float(m.group(1)), exc.message) from exc
            raise RPCError(exc.code, exc.message) from exc
        except (TimeoutError, ConnectionError) as exc:
            raise AdapterError(f"MTProto request failed: {exc!r}") from exc

    async def call(self, method: str, **params: Any) -> Any:
        """Invoke a Telegram API method by name, e.g. ``call("help.getConfig")``."""
        payload = self.schema.serialize(method, params)
        ret_type = self.schema.return_type(method)
        for _attempt in range(3):
            try:
                raw = await self.invoke_raw(payload)
            except RPCError as exc:
                m = _MIGRATE_RE.search(exc.message)
                if not m or m.group(1) == "FILE":
                    raise
                if self._custom_host:
                    raise
                await self._switch_dc(int(m.group(2)))
                continue
            return self._decode(raw, ret_type)
        raise AdapterError(f"{method}: too many DC migrations")

    def _decode(self, raw: bytes, ret_type: str | None) -> Any:
        try:
            return self.schema.deserialize(raw, ret_type)
        except Exception:  # noqa: BLE001
            return raw

    async def invoke(self, method: str, **params: Any) -> Any:
        if "tl_payload" in params and isinstance(params["tl_payload"], (bytes, bytearray)):
            return await self.invoke_raw(bytes(params["tl_payload"]))
        return await self.call(method, **params)

    async def invoke_with_layer(self, query: bytes) -> bytes:
        return await self.invoke_raw(self._wrap_init(query))

    # ------------------------------------------------------------------- login
    async def start(self) -> TLObject | None:
        """Log in (bot token or phone/code/2FA). Safe to call when already authorized."""
        if self._authorized:
            return None
        if self.bot_token:
            return await self.import_bot_authorization()
        phone = self._resolve_input(self.phone, "Phone number (international format): ")
        sent = await self.send_code(phone)
        code = self.code_callback() if self.code_callback else input("Login code: ").strip()
        try:
            auth = await self.sign_in(phone, sent["phone_code_hash"], code)
        except RPCError as exc:
            if "SESSION_PASSWORD_NEEDED" not in exc.message:
                raise
            pw = self._resolve_input(self.password, "2FA password: ", secret=True)
            auth = await self.check_password(pw)
        return auth

    @staticmethod
    def _resolve_input(value: Any, prompt: str, *, secret: bool = False) -> str:
        if callable(value):
            return str(value())
        if value:
            return str(value)
        return getpass.getpass(prompt) if secret else input(prompt).strip()

    async def send_code(self, phone_number: str) -> TLObject:
        res = await self.call(
            "auth.sendCode",
            phone_number=phone_number,
            api_id=self.api_id,
            api_hash=self.api_hash,
            settings={"_": "codeSettings"},
        )
        if isinstance(res, dict) and res.get("_") == "auth.sentCodeSuccess":
            self._on_authorized(res["authorization"])
        return res

    async def sign_in(self, phone_number: str, phone_code_hash: str, code: str) -> TLObject:
        res = await self.call(
            "auth.signIn",
            phone_number=phone_number,
            phone_code_hash=phone_code_hash,
            phone_code=code,
        )
        return self._on_authorized(res)

    async def check_password(self, password: str) -> TLObject:
        info = await self.call("account.getPassword")
        res = await self.call("auth.checkPassword", password=compute_check(info, password))
        return self._on_authorized(res)

    async def import_bot_authorization(self, bot_token: str | None = None) -> TLObject:
        tok = bot_token or self.bot_token
        if not tok:
            raise AdapterError("bot_token is required for import_bot_authorization.")
        res = await self.call(
            "auth.importBotAuthorization",
            flags=0,
            api_id=self.api_id,
            api_hash=self.api_hash,
            bot_auth_token=tok,
        )
        return self._on_authorized(res)

    def _on_authorized(self, res: Any) -> TLObject:
        if not isinstance(res, dict):
            raise AdapterError(f"Unexpected authorization result: {res!r}")
        if res.get("_") == "auth.authorizationSignUpRequired":
            raise AdapterError(
                "This phone number is not registered on Telegram; sign up with an official app first."
            )
        user = res.get("user") or {}
        self.self_id = int(user.get("id", 0))
        self.is_bot = bool(user.get("bot", False))
        self._cache_entities([user], [])
        self._authorized = True
        self._save_session()
        self._save_auth()
        self._spawn(self._fetch_state())
        return res  # type: ignore[return-value]

    # ----------------------------------------------------------------- updates
    async def _fetch_state(self) -> None:
        st = await self.call("updates.getState")
        if isinstance(st, dict):
            self.updates.pts, self.updates.qts = st["pts"], st["qts"]
            self.updates.date, self.updates.seq = st["date"], st["seq"]
            self._save_auth()

    def _on_new_session(self) -> None:
        if self._authorized and self.updates.pts:
            self._spawn(self.sync_updates_state())

    async def sync_updates_state(self) -> None:
        """Recover missed updates via updates.getDifference."""
        if self._diff_lock.locked():
            return
        async with self._diff_lock:
            try:
                if self.updates.pts == 0:
                    await self._fetch_state()
                    return
                for _ in range(50):
                    diff = await self.call(
                        "updates.getDifference",
                        pts=self.updates.pts,
                        date=self.updates.date,
                        qts=self.updates.qts,
                    )
                    kind = diff.get("_") if isinstance(diff, dict) else None
                    if kind == "updates.differenceEmpty":
                        self.updates.date, self.updates.seq = diff["date"], diff["seq"]
                        break
                    if kind == "updates.differenceTooLong":
                        self.updates.pts = diff["pts"]
                        break
                    if kind not in ("updates.difference", "updates.differenceSlice"):
                        break
                    self._cache_entities(diff["users"], diff["chats"])
                    for msg in diff["new_messages"]:
                        await self._emit_message(msg, EventType.NEW_MESSAGE)
                    for upd in diff["other_updates"]:
                        await self._handle_update(upd, check_pts=False)
                    st = diff["state"] if kind == "updates.difference" else diff["intermediate_state"]
                    self.updates.pts, self.updates.qts = st["pts"], st["qts"]
                    self.updates.date, self.updates.seq = st["date"], st["seq"]
                    if kind == "updates.difference":
                        break
                self._save_auth()
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("Failed to sync updates state: %s", exc)

    async def _sync_channel(self, channel_id: int) -> None:
        rec = self.peers.get("channel", channel_id)
        pts = self.updates.channel_pts.get(channel_id, 0)
        if rec is None or pts == 0:
            return
        try:
            for _ in range(20):
                diff = await self.call(
                    "updates.getChannelDifference",
                    channel={"_": "inputChannel", "channel_id": channel_id, "access_hash": rec.access_hash},
                    filter={"_": "channelMessagesFilterEmpty"},
                    pts=pts,
                    limit=100,
                )
                kind = diff.get("_")
                if kind == "updates.channelDifferenceEmpty":
                    self.updates.channel_pts[channel_id] = diff["pts"]
                    return
                if kind == "updates.channelDifferenceTooLong":
                    self._cache_entities(diff["users"], diff["chats"])
                    self.updates.channel_pts[channel_id] = diff["dialog"].get("pts") or pts
                    return
                self._cache_entities(diff["users"], diff["chats"])
                for msg in diff["new_messages"]:
                    await self._emit_message(msg, EventType.NEW_MESSAGE)
                for upd in diff["other_updates"]:
                    await self._handle_update(upd, check_pts=False)
                pts = diff["pts"]
                self.updates.channel_pts[channel_id] = pts
                if diff.get("final"):
                    return
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("getChannelDifference(%s) failed: %s", channel_id, exc)

    async def _on_raw_update(self, body: bytes) -> None:
        try:
            obj = self.schema.deserialize(body)
        except Exception:  # noqa: BLE001
            await self._queue.put(UpdateEvent(type=EventType.RAW, raw=body))
            return
        if isinstance(obj, dict):
            await self._handle_updates(obj)

    async def _handle_updates(self, obj: dict[str, Any], *, emit: bool = True) -> None:
        kind = obj.get("_")
        if kind == "updatesTooLong":
            self._spawn(self.sync_updates_state())
        elif kind == "updateShortMessage":
            msg = {
                "_": "message",
                "out": obj["out"],
                "id": obj["id"],
                "from_id": {"_": "peerUser", "user_id": self.self_id if obj["out"] else obj["user_id"]},
                "peer_id": {"_": "peerUser", "user_id": obj["user_id"]},
                "message": obj["message"],
                "date": obj["date"],
                "reply_to": obj.get("reply_to"),
                "entities": obj.get("entities"),
            }
            if self._apply_pts(obj["pts"], obj["pts_count"]) and emit:
                await self._emit_message(msg, EventType.NEW_MESSAGE)
        elif kind == "updateShortChatMessage":
            msg = {
                "_": "message",
                "out": obj["out"],
                "id": obj["id"],
                "from_id": {"_": "peerUser", "user_id": obj["from_id"]},
                "peer_id": {"_": "peerChat", "chat_id": obj["chat_id"]},
                "message": obj["message"],
                "date": obj["date"],
                "reply_to": obj.get("reply_to"),
                "entities": obj.get("entities"),
            }
            if self._apply_pts(obj["pts"], obj["pts_count"]) and emit:
                await self._emit_message(msg, EventType.NEW_MESSAGE)
        elif kind == "updateShort":
            await self._handle_update(obj["update"], emit=emit)
        elif kind in ("updates", "updatesCombined"):
            self._cache_entities(obj.get("users", []), obj.get("chats", []))
            for upd in obj.get("updates", []):
                await self._handle_update(upd, emit=emit)
            if obj.get("seq"):
                self.updates.seq = obj["seq"]
            if obj.get("date"):
                self.updates.date = obj["date"]
        elif kind == "updateShortSentMessage":
            self._apply_pts(obj["pts"], obj["pts_count"])
        elif emit:
            await self._queue.put(UpdateEvent(type=EventType.RAW, raw=obj))

    def _apply_pts(self, pts: int, count: int, channel_id: int | None = None) -> bool:
        if channel_id is None:
            res = self.updates.apply_common_pts(pts, count)
        else:
            res = self.updates.apply_channel_pts(channel_id, pts, count)
        if res is UpdateGapAction.GAP_DETECTED:
            if channel_id is None:
                self._spawn(self.sync_updates_state())
            else:
                self._spawn(self._sync_channel(channel_id))
            return False
        return res is UpdateGapAction.APPLIED

    async def _handle_update(self, upd: dict[str, Any], *, check_pts: bool = True, emit: bool = True) -> None:
        kind = upd.get("_")
        if kind in ("updateNewMessage", "updateEditMessage"):
            ok = self._apply_pts(upd["pts"], upd["pts_count"]) if check_pts else True
            if ok and emit:
                et = EventType.NEW_MESSAGE if kind == "updateNewMessage" else EventType.EDIT_MESSAGE
                await self._emit_message(upd["message"], et)
        elif kind in ("updateNewChannelMessage", "updateEditChannelMessage"):
            msg = upd["message"]
            peer = msg.get("peer_id") or {}
            ch_id = int(peer.get("channel_id", 0))
            ok = self._apply_pts(upd["pts"], upd["pts_count"], ch_id) if check_pts and ch_id else True
            if ok and emit:
                et = EventType.NEW_MESSAGE if kind == "updateNewChannelMessage" else EventType.EDIT_MESSAGE
                await self._emit_message(msg, et)
        elif kind == "updateDeleteMessages":
            if check_pts:
                self._apply_pts(upd["pts"], upd["pts_count"])
            if emit:
                await self._emit_delete(0, upd["messages"])
        elif kind == "updateDeleteChannelMessages":
            ch_id = int(upd["channel_id"])
            if check_pts:
                self._apply_pts(upd["pts"], upd["pts_count"], ch_id)
            if emit:
                await self._emit_delete(-(_CHANNEL_OFFSET + ch_id), upd["messages"])
        elif kind == "updateChannelTooLong":
            self._spawn(self._sync_channel(int(upd["channel_id"])))
        elif emit:
            await self._queue.put(UpdateEvent(type=EventType.RAW, raw=upd))

    async def _emit_delete(self, chat_id: int, ids: list[int]) -> None:
        for mid in ids:
            ev = MessageEvent(id=int(mid), chat=ChatRef(id=chat_id), sender=None)
            await self._queue.put(UpdateEvent(type=EventType.DELETE_MESSAGE, message=ev))

    async def _emit_message(self, msg: dict[str, Any], et: EventType) -> None:
        ev = self._to_message_event(msg)
        if ev is not None:
            await self._queue.put(UpdateEvent(type=et, message=ev, raw=msg))

    def _to_message_event(self, msg: dict[str, Any]) -> MessageEvent | None:
        if msg.get("_") != "message":
            return None  # messageEmpty / messageService
        peer = msg["peer_id"]
        chat_id = marked_id(peer)
        ptype = peer["_"]
        ctype, title = self._chat_info.get(chat_id, (None, None))
        if ctype is None:
            ctype = {"peerUser": "private", "peerChat": "group", "peerChannel": "supergroup"}[ptype]
        out = bool(msg.get("out"))
        from_peer = msg.get("from_id")
        if from_peer is not None:
            sender_id = marked_id(from_peer)
        elif ptype == "peerUser":
            sender_id = self.self_id if out else chat_id
        else:
            sender_id = chat_id  # channel post / anonymous admin
        urec = self.peers.get("user", sender_id) if sender_id > 0 else None
        sender_name = self._chat_info.get(sender_id, (None, None))[1]
        sender = UserRef(
            id=sender_id,
            username=urec.username if urec else None,
            first_name=sender_name,
            is_self=out or (sender_id == self.self_id and self.self_id != 0),
        )
        reply_to = msg.get("reply_to") or {}
        media = msg.get("media")
        media_ref = self._media_ref(media) if media else None
        if media_ref is not None:
            self._remember_media(chat_id, int(msg["id"]), media)
        return MessageEvent(
            id=int(msg["id"]),
            chat=ChatRef(id=chat_id, type=ctype, title=title),
            sender=sender,
            text=msg.get("message") or "",
            media=media_ref,
            reply_to_id=reply_to.get("reply_to_msg_id"),
            is_outgoing=out,
            date=datetime.fromtimestamp(int(msg.get("date") or time.time()), tz=UTC),
            raw=msg,
        )

    # ------------------------------------------------------------- peer cache
    def _cache_entities(self, users: list[dict[str, Any]], chats: list[dict[str, Any]]) -> None:
        for u in users:
            if u.get("_") != "user":
                continue
            uid = int(u["id"])
            name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or None
            self._chat_info[uid] = ("private", name)
            ahash = u.get("access_hash")
            if ahash is not None and not u.get("min"):
                self.peers.put("user", uid, ahash, u.get("username"))
        for c in chats:
            kind = c.get("_")
            if kind in ("chat", "chatForbidden"):
                cid = int(c["id"])
                self._chat_info[-cid] = ("group", c.get("title"))
                self.peers.put("chat", cid, 0)
            elif kind in ("channel", "channelForbidden"):
                cid = int(c["id"])
                ctype = "channel" if c.get("broadcast") else "supergroup"
                self._chat_info[-(_CHANNEL_OFFSET + cid)] = (ctype, c.get("title"))
                ahash = c.get("access_hash")
                if ahash is not None and not c.get("min"):
                    self.peers.put("channel", cid, ahash, c.get("username"))

    async def _load_dialogs(self) -> None:
        if self._dialogs_loaded:
            return
        self._dialogs_loaded = True
        try:
            res = await self.call(
                "messages.getDialogs",
                offset_date=0,
                offset_id=0,
                offset_peer={"_": "inputPeerEmpty"},
                limit=200,
                hash=0,
            )
            if isinstance(res, dict):
                self._cache_entities(res.get("users", []), res.get("chats", []))
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("getDialogs failed: %s", exc)

    async def resolve_username(self, username: str) -> TLObject:
        res = await self.call("contacts.resolveUsername", username=username.lstrip("@"))
        self._cache_entities(res.get("users", []), res.get("chats", []))
        return res

    async def _input_peer(self, chat_id: int | str) -> dict[str, Any]:
        if isinstance(chat_id, str):
            s = chat_id.strip()
            if s.lower() in ("me", "self"):
                return {"_": "inputPeerSelf"}
            if not s.lstrip("-").isdigit():
                rec = self.peers.get_by_username(s)
                if rec is None:
                    res = await self.resolve_username(s)
                    return self._peer_to_input(res["peer"])
                return self._rec_to_input(rec.peer_type, rec.peer_id, rec.access_hash)
            chat_id = int(s)
        cid = int(chat_id)
        if cid == self.self_id and cid:
            return {"_": "inputPeerSelf"}
        ptype, pid = split_marked_id(cid)
        if ptype == "chat":
            return {"_": "inputPeerChat", "chat_id": pid}
        rec = self.peers.get(ptype, pid)
        if rec is None:
            await self._load_dialogs()
            rec = self.peers.get(ptype, pid)
        if rec is None:
            _LOG.warning(
                "No access_hash cached for peer %s; trying access_hash=0 "
                "(receive a message from it first or address it by @username).",
                cid,
            )
            return self._rec_to_input(ptype, pid, 0)
        return self._rec_to_input(ptype, pid, rec.access_hash)

    def _peer_to_input(self, peer: dict[str, Any]) -> dict[str, Any]:
        ptype, pid = split_marked_id(marked_id(peer))
        rec = self.peers.get(ptype, pid)
        return self._rec_to_input(ptype, pid, rec.access_hash if rec else 0)

    @staticmethod
    def _rec_to_input(ptype: str, pid: int, ahash: int) -> dict[str, Any]:
        if ptype == "user":
            return {"_": "inputPeerUser", "user_id": pid, "access_hash": ahash}
        if ptype == "channel":
            return {"_": "inputPeerChannel", "channel_id": pid, "access_hash": ahash}
        return {"_": "inputPeerChat", "chat_id": pid}

    @staticmethod
    def _as_input_channel(peer: dict[str, Any]) -> dict[str, Any]:
        if peer["_"] != "inputPeerChannel":
            raise AdapterError("This operation requires a supergroup or channel.")
        return {"_": "inputChannel", "channel_id": peer["channel_id"], "access_hash": peer["access_hash"]}

    @staticmethod
    def _as_input_user(peer: dict[str, Any]) -> dict[str, Any]:
        if peer["_"] == "inputPeerSelf":
            return {"_": "inputUserSelf"}
        if peer["_"] != "inputPeerUser":
            raise AdapterError("Expected a user peer.")
        return {"_": "inputUser", "user_id": peer["user_id"], "access_hash": peer["access_hash"]}

    # ---------------------------------------------------------------- results
    def _text_and_entities(self, text: str, parse_mode: str | None) -> tuple[str, list[dict[str, Any]] | None]:
        if parse_mode and parse_mode.lower() == "html":
            plain, ents = parse_html(text)
            return plain, ents or None
        return text, None

    def _sent_message_id(self, res: Any, rid: int) -> int | None:
        if not isinstance(res, dict):
            return None
        if res.get("_") == "updateShortSentMessage":
            return int(res["id"])
        for upd in res.get("updates", []) if res.get("_") in ("updates", "updatesCombined") else []:
            if upd.get("_") == "updateMessageID" and int(upd.get("random_id", 0)) == rid:
                return int(upd["id"])
        if res.get("_") == "updateShort":
            res = {"updates": [res["update"]]}
        for upd in res.get("updates", []):
            m = upd.get("message")
            if isinstance(m, dict) and "id" in m:
                return int(m["id"])
        return None

    async def _absorb(self, res: Any) -> None:
        """Apply pts/peers from an Updates result without re-emitting our own messages."""
        if isinstance(res, dict) and res.get("_", "").startswith("update"):
            await self._handle_updates(res, emit=False)

    def _local_event(
        self, chat_id: int | str, peer: dict[str, Any], mid: int, text: str, reply_to: int | None
    ) -> MessageEvent:
        cid = chat_id if isinstance(chat_id, int) else self._marked_from_input(peer)
        ctype = self._chat_info.get(cid, (None, None))[0] or (
            "private" if cid > 0 else ("group" if cid > -_CHANNEL_OFFSET else "supergroup")
        )
        return MessageEvent(
            id=mid,
            chat=ChatRef(id=cid, type=ctype),
            sender=UserRef(id=self.self_id, is_self=True),
            text=text,
            reply_to_id=reply_to,
            is_outgoing=True,
        )

    def _marked_from_input(self, peer: dict[str, Any]) -> int:
        k = peer["_"]
        if k == "inputPeerUser":
            return int(peer["user_id"])
        if k == "inputPeerChat":
            return -int(peer["chat_id"])
        if k == "inputPeerChannel":
            return -(_CHANNEL_OFFSET + int(peer["channel_id"]))
        return self.self_id

    # --------------------------------------------------------------- messages
    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        peer = await self._input_peer(chat_id)
        plain, ents = self._text_and_entities(text, parse_mode)
        rid = random_long()
        res = await self.call(
            "messages.sendMessage",
            peer=peer,
            reply_to={"_": "inputReplyToMessage", "reply_to_msg_id": reply_to} if reply_to else None,
            message=plain,
            random_id=rid,
            entities=ents,
        )
        await self._absorb(res)
        mid = self._sent_message_id(res, rid) or 0
        return self._local_event(chat_id, peer, mid, plain, reply_to)

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        peer = await self._input_peer(chat_id)
        plain, ents = self._text_and_entities(text, parse_mode)
        res = await self.call(
            "messages.editMessage", peer=peer, id=int(message_id), message=plain, entities=ents
        )
        await self._absorb(res)
        return self._local_event(chat_id, peer, int(message_id), plain, None)

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        *,
        revoke: bool = True,
    ) -> int:
        if not message_ids:
            return 0
        peer = await self._input_peer(chat_id)
        ids = [int(i) for i in message_ids]
        if peer["_"] == "inputPeerChannel":
            res = await self.call("channels.deleteMessages", channel=self._as_input_channel(peer), id=ids)
            ch = int(peer["channel_id"])
            if isinstance(res, dict) and "pts" in res:
                self._apply_pts(res["pts"], res["pts_count"], ch)
        else:
            res = await self.call("messages.deleteMessages", revoke=revoke, id=ids)
            if isinstance(res, dict) and "pts" in res:
                self._apply_pts(res["pts"], res["pts_count"])
        return int(res.get("pts_count", len(ids))) if isinstance(res, dict) else len(ids)

    # ------------------------------------------------------------------ media
    async def _upload(self, media: str | Path | bytes, progress: Any = None) -> tuple[dict[str, Any], str, str]:
        data = media if isinstance(media, bytes) else Path(media).read_bytes()
        name = "upload.bin" if isinstance(media, bytes) else Path(media).name
        big = len(data) > _BIG_FILE

        async def _save_part(file_id: int, part: int, total: int, chunk: bytes, is_big: bool) -> bool:
            if big:
                await self.call(
                    "upload.saveBigFilePart",
                    file_id=file_id,
                    file_part=part,
                    file_total_parts=total,
                    bytes=chunk,
                )
            else:
                await self.call("upload.saveFilePart", file_id=file_id, file_part=part, bytes=chunk)
            return True

        up = await self.files.upload_bytes(data, name, _save_part, progress=progress)
        if big:
            input_file = {"_": "inputFileBig", "id": up.file_id, "parts": up.parts, "name": name}
        else:
            input_file = {
                "_": "inputFile",
                "id": up.file_id,
                "parts": up.parts,
                "name": name,
                "md5_checksum": "",
            }
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return input_file, name, mime

    @staticmethod
    def _input_media(input_file: dict[str, Any], name: str, mime: str) -> dict[str, Any]:
        if mime in ("image/jpeg", "image/png"):
            return {"_": "inputMediaUploadedPhoto", "file": input_file}
        attrs: list[dict[str, Any]] = [{"_": "documentAttributeFilename", "file_name": name}]
        return {
            "_": "inputMediaUploadedDocument",
            "file": input_file,
            "mime_type": mime,
            "attributes": attrs,
        }

    async def send_media(
        self,
        chat_id: int | str,
        media: str | Path | bytes,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
        progress: Any = None,
    ) -> MessageEvent:
        peer = await self._input_peer(chat_id)
        input_file, name, mime = await self._upload(media, progress)
        plain, ents = self._text_and_entities(caption or "", parse_mode)
        rid = random_long()
        res = await self.call(
            "messages.sendMedia",
            peer=peer,
            reply_to={"_": "inputReplyToMessage", "reply_to_msg_id": reply_to} if reply_to else None,
            media=self._input_media(input_file, name, mime),
            message=plain,
            random_id=rid,
            entities=ents,
        )
        await self._absorb(res)
        mid = self._sent_message_id(res, rid) or 0
        return self._local_event(chat_id, peer, mid, plain, reply_to)

    async def send_album(
        self,
        chat_id: int | str,
        media_items: Sequence[str | Path | bytes],
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> list[MessageEvent]:
        peer = await self._input_peer(chat_id)
        singles: list[dict[str, Any]] = []
        rids: list[int] = []
        for idx, item in enumerate(media_items):
            input_file, name, mime = await self._upload(item)
            uploaded = await self.call(
                "messages.uploadMedia", peer=peer, media=self._input_media(input_file, name, mime)
            )
            if uploaded.get("_") == "messageMediaPhoto":
                p = uploaded["photo"]
                im = {"_": "inputMediaPhoto", "id": {"_": "inputPhoto", "id": p["id"], "access_hash": p["access_hash"], "file_reference": p["file_reference"]}}
            else:
                d = uploaded["document"]
                im = {"_": "inputMediaDocument", "id": {"_": "inputDocument", "id": d["id"], "access_hash": d["access_hash"], "file_reference": d["file_reference"]}}
            plain, ents = self._text_and_entities(caption or "", parse_mode) if idx == 0 else ("", None)
            rid = random_long()
            rids.append(rid)
            singles.append({"_": "inputSingleMedia", "media": im, "random_id": rid, "message": plain, "entities": ents})
        res = await self.call(
            "messages.sendMultiMedia",
            peer=peer,
            reply_to={"_": "inputReplyToMessage", "reply_to_msg_id": reply_to} if reply_to else None,
            multi_media=singles,
        )
        await self._absorb(res)
        out: list[MessageEvent] = []
        for idx, rid in enumerate(rids):
            mid = self._sent_message_id(res, rid) or 0
            out.append(self._local_event(chat_id, peer, mid, caption or "" if idx == 0 else "", reply_to))
        return out

    @staticmethod
    def _media_ref(media: dict[str, Any]) -> MediaRef | None:
        kind = media.get("_")
        if kind == "messageMediaPhoto" and media.get("photo", {}).get("_") == "photo":
            p = media["photo"]
            return MediaRef(media_type="photo", file_id=f"photo:{p['id']}", mime_type="image/jpeg")
        if kind == "messageMediaDocument" and media.get("document", {}).get("_") == "document":
            d = media["document"]
            mtype, fname = "document", None
            for a in d.get("attributes", []):
                an = a.get("_")
                if an == "documentAttributeFilename":
                    fname = a["file_name"]
                elif an == "documentAttributeVideo":
                    mtype = "video"
                elif an == "documentAttributeAudio":
                    mtype = "voice" if a.get("voice") else "audio"
                elif an == "documentAttributeSticker":
                    mtype = "sticker"
            return MediaRef(
                media_type=mtype,
                file_id=f"doc:{d['id']}",
                mime_type=d.get("mime_type"),
                file_name=fname,
                file_size=d.get("size"),
            )
        return None

    def _remember_media(self, chat_id: int, mid: int, media: dict[str, Any]) -> None:
        self._media[(chat_id, mid)] = media
        self._media.move_to_end((chat_id, mid))
        while len(self._media) > _MEDIA_CACHE_SIZE:
            self._media.popitem(last=False)

    async def _fetch_message_media(self, chat_id: int, mid: int) -> dict[str, Any] | None:
        peer = await self._input_peer(chat_id)
        if peer["_"] == "inputPeerChannel":
            res = await self.call(
                "channels.getMessages",
                channel=self._as_input_channel(peer),
                id=[{"_": "inputMessageID", "id": mid}],
            )
        else:
            res = await self.call("messages.getMessages", id=[{"_": "inputMessageID", "id": mid}])
        self._cache_entities(res.get("users", []), res.get("chats", []))
        for m in res.get("messages", []):
            if m.get("id") == mid and m.get("media"):
                return m["media"]
        return None

    @staticmethod
    def _file_location(media: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
        if media.get("_") == "messageMediaPhoto":
            p = media["photo"]
            sizes = [s for s in p.get("sizes", []) if s.get("_") in ("photoSize", "photoSizeProgressive")]
            if not sizes:
                raise AdapterError("Photo has no downloadable sizes.")
            best = max(sizes, key=lambda s: s.get("size") or max(s.get("sizes") or [0]))
            size = best.get("size") or max(best.get("sizes") or [0])
            loc = {
                "_": "inputPhotoFileLocation",
                "id": p["id"],
                "access_hash": p["access_hash"],
                "file_reference": p["file_reference"],
                "thumb_size": best["type"],
            }
            return loc, int(p["dc_id"]), int(size)
        if media.get("_") == "messageMediaDocument":
            d = media["document"]
            loc = {
                "_": "inputDocumentFileLocation",
                "id": d["id"],
                "access_hash": d["access_hash"],
                "file_reference": d["file_reference"],
                "thumb_size": "",
            }
            return loc, int(d["dc_id"]), int(d.get("size") or 0)
        raise AdapterError(f"Unsupported media type for download: {media.get('_')}")

    async def _file_sender(self, dc_id: int) -> MTProtoSender | None:
        if dc_id == self.state.dc_id or self._custom_host:
            return None
        sender = self._file_senders.get(dc_id)
        if sender is not None:
            return sender
        host, port = TELEGRAM_DCS[dc_id]
        sender = self._make_sender(MTProtoSessionState(dc_id=dc_id, host=host, port=port), main=False)
        await sender.connect()
        exported = await self.call("auth.exportAuthorization", dc_id=dc_id)
        await self.invoke_raw(
            self.schema.serialize(
                "auth.importAuthorization", {"id": exported["id"], "bytes": exported["bytes"]}
            ),
            _sender=sender,
        )
        self._file_senders[dc_id] = sender
        return sender

    async def download_media(
        self,
        message: MessageEvent,
        *,
        destination: str | Path | None = None,
        progress: Any = None,
    ) -> Path | bytes:
        media = self._media.get((message.chat.id, message.id))
        if media is None and isinstance(message.raw, dict):
            media = message.raw.get("media")
        if media is None:
            media = await self._fetch_message_media(message.chat.id, message.id)
        if media is None:
            raise AdapterError("Message has no downloadable media.")
        loc, dc_id, total = self._file_location(media)
        sender = await self._file_sender(dc_id)
        out = bytearray()
        offset = 0
        while True:
            payload = self.schema.serialize(
                "upload.getFile", {"location": loc, "offset": offset, "limit": _DOWNLOAD_CHUNK}
            )
            try:
                raw = await self.invoke_raw(payload, _sender=sender)
            except RPCError as exc:
                m = _MIGRATE_RE.search(exc.message)
                if m and m.group(1) == "FILE":
                    sender = await self._file_sender(int(m.group(2)))
                    continue
                raise
            res = self.schema.deserialize(raw, "upload.File")
            if res.get("_") != "upload.file":
                raise AdapterError("CDN downloads are not supported by NativeMTProtoAdapter yet.")
            chunk: bytes = res["bytes"]
            out += chunk
            offset += len(chunk)
            if progress is not None:
                r = progress(offset, total or offset)
                if asyncio.iscoroutine(r):
                    await r
            if len(chunk) < _DOWNLOAD_CHUNK:
                break
        if destination is not None:
            p = Path(destination)
            if p.is_dir():
                ref = self._media_ref(media)
                p = p / ((ref.file_name if ref and ref.file_name else None) or f"{message.chat.id}_{message.id}")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(bytes(out))
            return p
        return bytes(out)

    # ----------------------------------------------------------- moderation
    async def send_reaction(self, chat_id: int | str, message_id: int, emoji: str | None = None) -> None:
        peer = await self._input_peer(chat_id)
        reaction = [{"_": "reactionEmoji", "emoticon": emoji}] if emoji else []
        res = await self.call("messages.sendReaction", peer=peer, msg_id=int(message_id), reaction=reaction)
        await self._absorb(res)

    async def pin_message(self, chat_id: int | str, message_id: int, *, silent: bool = False) -> None:
        peer = await self._input_peer(chat_id)
        res = await self.call("messages.updatePinnedMessage", silent=silent, peer=peer, id=int(message_id))
        await self._absorb(res)

    async def send_chat_action(self, chat_id: int | str, action: ChatAction | str) -> None:
        peer = await self._input_peer(chat_id)
        a = str(action)
        mapping: dict[str, dict[str, Any]] = {
            "typing": {"_": "sendMessageTypingAction"},
            "cancel": {"_": "sendMessageCancelAction"},
            "upload_photo": {"_": "sendMessageUploadPhotoAction", "progress": 0},
            "upload_video": {"_": "sendMessageUploadVideoAction", "progress": 0},
            "upload_document": {"_": "sendMessageUploadDocumentAction", "progress": 0},
            "record_voice": {"_": "sendMessageRecordAudioAction"},
        }
        await self.call("messages.setTyping", peer=peer, action=mapping.get(a, mapping["typing"]))

    async def _edit_banned(self, chat_id: int | str, user_id: int | str, **rights: Any) -> None:
        peer = await self._input_peer(chat_id)
        user = await self._input_peer(user_id)
        res = await self.call(
            "channels.editBanned",
            channel=self._as_input_channel(peer),
            participant=user,
            banned_rights={"_": "chatBannedRights", "until_date": rights.pop("until_date", 0), **rights},
        )
        await self._absorb(res)

    async def ban_user(self, chat_id: int | str, user_id: int | str, *, until_date: int | None = None) -> None:
        peer = await self._input_peer(chat_id)
        if peer["_"] == "inputPeerChat":
            user = self._as_input_user(await self._input_peer(user_id))
            res = await self.call("messages.deleteChatUser", chat_id=peer["chat_id"], user_id=user)
            await self._absorb(res)
            return
        await self._edit_banned(chat_id, user_id, view_messages=True, until_date=until_date or 0)

    async def unban_user(self, chat_id: int | str, user_id: int | str) -> None:
        peer = await self._input_peer(chat_id)
        if peer["_"] == "inputPeerChat":
            return  # basic groups have no ban list
        await self._edit_banned(chat_id, user_id)

    async def mute_user(self, chat_id: int | str, user_id: int | str, *, until_date: int | None = None) -> None:
        await self._edit_banned(chat_id, user_id, send_messages=True, until_date=until_date or 0)

    async def kick_user(self, chat_id: int | str, user_id: int | str) -> None:
        await self.ban_user(chat_id, user_id)
        await self.unban_user(chat_id, user_id)

    async def get_chat(self, chat_id: int | str) -> ChatRef:
        peer = await self._input_peer(chat_id)
        k = peer["_"]
        if k in ("inputPeerUser", "inputPeerSelf"):
            res = await self.call("users.getUsers", id=[self._as_input_user(peer)])
            self._cache_entities(res if isinstance(res, list) else [], [])
            u = res[0] if isinstance(res, list) and res else {}
            name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or None
            return ChatRef(id=int(u.get("id", 0)), type="private", title=name)
        if k == "inputPeerChat":
            res = await self.call("messages.getChats", id=[peer["chat_id"]])
        else:
            res = await self.call("channels.getChannels", id=[self._as_input_channel(peer)])
        self._cache_entities([], res.get("chats", []))
        cid = self._marked_from_input(peer)
        ctype, title = self._chat_info.get(cid, ("group", None))
        return ChatRef(id=cid, type=ctype, title=title)

    # --------------------------------------------------------------- listening
    async def push_update(self, event: UpdateEvent) -> None:
        await self._queue.put(event)

    async def listen(self) -> AsyncIterator[UpdateEvent]:
        while True:
            ev = await self._queue.get()
            if ev is None:
                break
            yield ev
