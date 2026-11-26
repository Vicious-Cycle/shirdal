"""Native zero-bloat MTProto 2.0 TransportAdapter built on shirdal.mtproto."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import Any, AsyncIterator

from shirdal.core.adapter import AdapterError, DeviceProfile, FloodWaitError
from shirdal.core.events import (
    ChatAction,
    ChatRef,
    EventType,
    MessageEvent,
    UpdateEvent,
    UserRef,
)
from shirdal.mtproto.auth import HandshakeSession, RSAPublicKey
from shirdal.mtproto.crypto import AuthKey
from shirdal.mtproto.files import FileTransferManager
from shirdal.mtproto.session import (
    BAD_MSG_NOTIFICATION_ID,
    BAD_SERVER_SALT_ID,
    MSG_CONTAINER_ID,
    RPC_RESULT_ID,
    MTProtoRPCError,
    MTProtoSessionState,
    MTProtoWire,
)
from shirdal.mtproto.tl_codec import TLReader, TLWriter
from shirdal.mtproto.tl_types import (
    NEW_SESSION_CREATED_ID,
    PONG_ID,
    TELEGRAM_LAYER,
    pack_auth_check_password,
    pack_auth_send_code,
    pack_auth_sign_in,
    pack_delete_messages,
    pack_edit_banned,
    pack_edit_message,
    pack_import_bot_authorization,
    pack_invoke_with_layer,
    pack_pin_message,
    pack_ping,
    pack_resolve_username,
    pack_save_file_part,
    pack_send_media_document,
    pack_send_message,
    pack_send_reaction,
    pack_set_typing,
    pack_updates_get_difference,
    pack_updates_get_state,
    parse_updates_payload,
)
from shirdal.mtproto.transport import MTProtoTransportError, TCPAbridgedTransport
from shirdal.mtproto.updates import PeerCache, UpdateStateTracker

_FLOOD_RE = re.compile(r"FLOOD_WAIT_(\d+)")
_MIGRATE_RE = re.compile(r"(?:PHONE|USER|NETWORK)_MIGRATE_(\d+)")
_LOG = logging.getLogger("shirdal.mtproto")

TELEGRAM_DCS: dict[int, tuple[str, int]] = {
    1: ("149.154.175.53", 443),
    2: ("149.154.167.50", 443),
    3: ("149.154.175.100", 443),
    4: ("149.154.167.91", 443),
    5: ("91.108.56.130", 443),
}


class NativeMTProtoAdapter:
    """Native MTProto 2.0 TransportAdapter implementing shirdal's TransportAdapter protocol."""

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
        device: DeviceProfile | None = None,
        rsa_keys: list[RSAPublicKey] | None = None,
        rpc_timeout: float = 20.0,
    ) -> None:
        self.api_id = int(api_id)
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.device = device or DeviceProfile.desktop()
        self.session_path = Path(session_path) if session_path is not None else None
        self.rsa_keys = rsa_keys or []
        self.rpc_timeout = float(rpc_timeout)

        loaded = MTProtoSessionState.load_sqlite(self.session_path) if self.session_path else None
        if loaded is not None:
            self.state = loaded
        else:
            dc_host, dc_port = TELEGRAM_DCS.get(dc_id, ("149.154.167.50", 443))
            ak = auth_key if isinstance(auth_key, AuthKey) else (AuthKey(auth_key) if auth_key else None)
            self.state = MTProtoSessionState(
                dc_id=dc_id,
                host=host or dc_host,
                port=port if host else dc_port,
                auth_key=ak,
                server_salt=server_salt,
            )

        self.wire = MTProtoWire(self.state)
        self.transport = TCPAbridgedTransport(self.state.host, self.state.port)
        self.peers = PeerCache(
            self.session_path.with_suffix(".peers.sqlite") if self.session_path else None
        )
        self.updates = UpdateStateTracker()
        self.files = FileTransferManager()

        self._connected = False
        self._authorized = False
        self._queue: asyncio.Queue[UpdateEvent | None] = asyncio.Queue()
        self._pending_rpcs: dict[int, asyncio.Future[bytes]] = {}
        self._recv_task: asyncio.Task[Any] | None = None
        self._ping_task: asyncio.Task[Any] | None = None
        self._next_local_msg_id = 1
        self._ping_interval = 30.0

    @property
    def is_connected(self) -> bool:
        return self._connected and self.transport.is_connected

    async def _perform_handshake(self) -> None:
        if not self.rsa_keys:
            raise AdapterError("Cannot perform MTProto handshake without rsa_keys or preloaded AuthKey.")
        hs = HandshakeSession(self.rsa_keys)
        await self.transport.send(self.wire.pack_unencrypted(hs.step1_req_pq_multi()))
        _, res_pq = self.wire.unpack_unencrypted(await self.transport.recv())
        await self.transport.send(self.wire.pack_unencrypted(hs.step2_handle_res_pq(res_pq)))
        _, srv_dh = self.wire.unpack_unencrypted(await self.transport.recv())
        await self.transport.send(self.wire.pack_unencrypted(hs.step3_handle_server_dh_params(srv_dh)))
        _, dh_gen = self.wire.unpack_unencrypted(await self.transport.recv())
        auth_key, salt = hs.step4_handle_dh_gen(dh_gen)
        self.state.auth_key = auth_key
        self.state.server_salt = salt
        if self.session_path is not None:
            self.state.save_sqlite(self.session_path)

    async def connect(self) -> None:
        if self._connected:
            return
        await self.transport.connect()
        if self.state.auth_key is None:
            await self._perform_handshake()
        self._connected = True
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def disconnect(self) -> None:
        self._connected = False
        for task in (self._ping_task, self._recv_task):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._ping_task = None
        self._recv_task = None
        for fut in self._pending_rpcs.values():
            if not fut.done():
                fut.set_exception(AdapterError("Disconnected before RPC completed."))
        self._pending_rpcs.clear()
        await self.transport.close()
        if self.session_path is not None and self.state.auth_key is not None:
            self.state.save_sqlite(self.session_path)
        await self._queue.put(None)

    async def _ping_loop(self) -> None:
        while self._connected:
            await asyncio.sleep(self._ping_interval)
            if not self._connected:
                break
            try:
                ping_id = struct.unpack("<q", os.urandom(8))[0]
                _, pkt = self.wire.pack_encrypted(pack_ping(ping_id), content_related=False)
                await self.transport.send(pkt)
            except Exception as exc:
                _LOG.warning("MTProto keepalive ping failed: %s", exc)

    async def _recv_loop(self) -> None:
        while self._connected:
            try:
                raw_pkt = await self.transport.recv()
            except asyncio.CancelledError:
                break
            except MTProtoTransportError as exc:
                _LOG.warning("MTProto transport error in recv_loop: %s", exc)
                break
            except Exception as exc:
                _LOG.exception("Unexpected error in recv_loop: %s", exc)
                break

            try:
                msg_id, seq_no, body = self.wire.unpack_encrypted(raw_pkt, from_client=False)
                self.state.sync_time_offset(msg_id)
                await self._dispatch_wire_body(msg_id, seq_no, body)
            except Exception as exc:
                _LOG.warning("Failed to dispatch MTProto packet: %s", exc)
                continue

    async def _dispatch_wire_body(self, msg_id: int, seq_no: int, body: bytes) -> None:
        if len(body) < 4:
            return
        cid = struct.unpack_from("<I", body, 0)[0]

        if cid == MSG_CONTAINER_ID:
            for item_id, item_seq, item_body in self.wire.unpack_container(body):
                await self._dispatch_wire_body(item_id, item_seq, item_body)
            return

        if cid == BAD_SERVER_SALT_ID:
            self.wire.handle_bad_server_salt(body)
            return

        if cid == BAD_MSG_NOTIFICATION_ID:
            bad_id, bad_seq, err_code = self.wire.handle_bad_msg_notification(body)
            _LOG.warning("bad_msg_notification: msg_id=%s seq=%s code=%s", bad_id, bad_seq, err_code)
            return

        if cid == NEW_SESSION_CREATED_ID:
            self.wire.handle_new_session_created(body)
            return

        if cid == PONG_ID:
            self.wire.handle_pong(body)
            return

        if cid == RPC_RESULT_ID:
            try:
                req_id, res_bytes = self.wire.unpack_rpc_result(body)
                fut = self._pending_rpcs.pop(req_id, None)
                if fut and not fut.done():
                    fut.set_result(res_bytes)
            except MTProtoRPCError as exc:
                req_id = struct.unpack_from("<q", body, 4)[0]
                fut = self._pending_rpcs.pop(req_id, None)
                if fut and not fut.done():
                    m = _FLOOD_RE.search(exc.message)
                    if m:
                        fut.set_exception(FloodWaitError(float(m.group(1)), exc.message))
                    else:
                        fut.set_exception(AdapterError(f"MTProto RPC error [{exc.code}]: {exc.message}"))
            return

        if seq_no & 1:
            ack_body = self.wire.pack_acks([msg_id])
            _, ack_pkt = self.wire.pack_encrypted(ack_body, content_related=False)
            await self.transport.send(ack_pkt)

        parsed_list = parse_updates_payload(body)
        for parsed in parsed_list:
            if parsed.kind == "new_message":
                msg = MessageEvent(
                    id=parsed.message_id,
                    chat=ChatRef(id=parsed.chat_id, type=parsed.chat_type),
                    sender=UserRef(id=parsed.sender_id, is_self=parsed.is_outgoing),
                    text=parsed.text,
                    is_outgoing=parsed.is_outgoing,
                )
                await self._queue.put(UpdateEvent(type=EventType.MESSAGE, message=msg, raw=body))
            elif parsed.kind == "updates_too_long":
                asyncio.create_task(self.sync_updates_state())
            else:
                await self._queue.put(UpdateEvent(type=EventType.RAW, raw=body))

    async def invoke_raw(self, tl_payload: bytes) -> bytes:
        if not self.is_connected:
            raise AdapterError("NativeMTProtoAdapter is not connected.")
        loop = asyncio.get_running_loop()
        req_id, pkt = self.wire.pack_encrypted(tl_payload, content_related=True)
        fut: asyncio.Future[bytes] = loop.create_future()
        self._pending_rpcs[req_id] = fut
        try:
            await self.transport.send(pkt)
            return await asyncio.wait_for(fut, timeout=self.rpc_timeout)
        finally:
            self._pending_rpcs.pop(req_id, None)

    async def invoke(self, method: str, **params: Any) -> Any:
        if "tl_payload" in params and isinstance(params["tl_payload"], (bytes, bytearray)):
            return await self.invoke_raw(bytes(params["tl_payload"]))
        w = TLWriter()
        w.write_string(method)
        return await self.invoke_raw(w.to_bytes())

    async def push_update(self, event: UpdateEvent) -> None:
        await self._queue.put(event)

    async def listen(self) -> AsyncIterator[UpdateEvent]:
        while True:
            ev = await self._queue.get()
            if ev is None:
                break
            yield ev

    def _resolve_peer(self, chat_id: int | str) -> tuple[str, int, int]:
        if isinstance(chat_id, str) and not chat_id.lstrip("-").isdigit():
            rec = self.peers.get_by_username(chat_id)
            if rec is not None:
                return rec.peer_type, rec.peer_id, rec.access_hash
            return "user", 0, 0
        cid = int(chat_id)
        if cid < 0:
            s = str(cid)
            if s.startswith("-100"):
                real_id = int(s[4:])
                rec = self.peers.get("channel", real_id)
                return "channel", real_id, rec.access_hash if rec else 0
            real_id = abs(cid)
            return "chat", real_id, 0
        rec = self.peers.get("user", cid)
        return "user", cid, rec.access_hash if rec else 0

    async def invoke_with_layer(self, query: bytes) -> bytes:
        wrapped = pack_invoke_with_layer(
            TELEGRAM_LAYER,
            self.api_id,
            self.device.device_model,
            self.device.system_version,
            self.device.app_version,
            self.device.system_lang_code,
            "",
            self.device.lang_code,
            query,
        )
        return await self.invoke_raw(wrapped)

    async def send_code(self, phone_number: str) -> bytes:
        return await self.invoke_with_layer(pack_auth_send_code(phone_number, self.api_id, self.api_hash))

    async def sign_in(self, phone_number: str, phone_code_hash: str, code: str) -> bytes:
        res = await self.invoke_raw(pack_auth_sign_in(phone_number, phone_code_hash, code))
        self._authorized = True
        return res

    async def check_password(self, srp_id: int, A: bytes, M1: bytes) -> bytes:
        res = await self.invoke_raw(pack_auth_check_password(srp_id, A, M1))
        self._authorized = True
        return res

    async def import_bot_authorization(self, bot_token: str | None = None) -> bytes:
        tok = bot_token or self.bot_token
        if not tok:
            raise AdapterError("bot_token is required for import_bot_authorization.")
        res = await self.invoke_with_layer(pack_import_bot_authorization(self.api_id, self.api_hash, tok))
        self._authorized = True
        return res

    async def sync_updates_state(self) -> None:
        try:
            if self.updates.pts == 0:
                await self.invoke_raw(pack_updates_get_state())
            else:
                await self.invoke_raw(pack_updates_get_difference(self.updates.pts, self.updates.date, self.updates.qts))
        except Exception as exc:
            _LOG.warning("Failed to sync updates state: %s", exc)

    async def resolve_username(self, username: str) -> bytes:
        return await self.invoke_raw(pack_resolve_username(username))

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        ptype, pid, ahash = self._resolve_peer(chat_id)
        cid = int(chat_id) if isinstance(chat_id, int) or str(chat_id).lstrip("-").isdigit() else pid
        mid = self._next_local_msg_id
        self._next_local_msg_id += 1
        payload = pack_send_message(
            ptype,
            pid,
            ahash,
            text,
            reply_to_msg_id=reply_to,
            parse_mode=parse_mode,
        )
        await self.invoke_raw(payload)
        return MessageEvent(
            id=mid,
            chat=ChatRef(id=cid, type="channel" if ptype == "channel" else "private"),
            sender=UserRef(id=0, is_self=True),
            text=text,
            reply_to_id=reply_to,
            is_outgoing=True,
        )

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "html",
    ) -> MessageEvent:
        ptype, pid, ahash = self._resolve_peer(chat_id)
        cid = int(chat_id) if isinstance(chat_id, int) or str(chat_id).lstrip("-").isdigit() else pid
        payload = pack_edit_message(ptype, pid, ahash, int(message_id), text, parse_mode=parse_mode)
        await self.invoke_raw(payload)
        return MessageEvent(
            id=int(message_id),
            chat=ChatRef(id=cid),
            sender=UserRef(id=0, is_self=True),
            text=text,
            is_outgoing=True,
        )

    async def delete_messages(
        self,
        chat_id: int | str,
        message_ids: list[int],
        *,
        revoke: bool = True,
    ) -> int:
        if not message_ids:
            return 0
        ptype, pid, ahash = self._resolve_peer(chat_id)
        await self.invoke_raw(pack_delete_messages(ptype, pid, ahash, message_ids, revoke=revoke))
        return len(message_ids)

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
        del caption, reply_to, parse_mode
        data = media if isinstance(media, bytes) else Path(media).read_bytes()
        name = "upload.bin" if isinstance(media, bytes) else Path(media).name

        async def _save_part(file_id: int, part: int, total: int, chunk: bytes, is_big: bool) -> bool:
            del total, is_big
            await self.invoke_raw(pack_save_file_part(file_id, part, chunk))
            return True

        up = await self.files.upload_bytes(data, name, _save_part, progress=progress)
        ptype, pid, ahash = self._resolve_peer(chat_id)
        cid = int(chat_id) if isinstance(chat_id, int) or str(chat_id).lstrip("-").isdigit() else pid
        mid = self._next_local_msg_id
        self._next_local_msg_id += 1
        await self.invoke_raw(
            pack_send_media_document(
                ptype,
                pid,
                ahash,
                up.file_id,
                up.parts,
                name,
                caption=caption or "",
            )
        )
        return MessageEvent(
            id=mid,
            chat=ChatRef(id=cid),
            sender=UserRef(id=0, is_self=True),
            text=caption or "",
            is_outgoing=True,
        )

    async def send_album(
        self,
        chat_id: int | str,
        media_items: Sequence[str | Path | bytes],
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        parse_mode: str | None = "html",
    ) -> list[MessageEvent]:
        out: list[MessageEvent] = []
        for idx, item in enumerate(media_items):
            out.append(
                await self.send_media(
                    chat_id,
                    item,
                    caption=caption if idx == 0 else None,
                    reply_to=reply_to,
                    parse_mode=parse_mode,
                )
            )
        return out

    async def download_media(
        self,
        message: MessageEvent,
        *,
        destination: str | Path | None = None,
        progress: Any = None,
    ) -> Path | bytes:
        del message, progress
        if destination is not None:
            p = Path(destination)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"")
            return p
        return b""

    async def send_reaction(
        self, chat_id: int | str, message_id: int, emoji: str | None = None
    ) -> None:
        ptype, pid, ahash = self._resolve_peer(chat_id)
        await self.invoke_raw(pack_send_reaction(ptype, pid, ahash, int(message_id), emoji or ""))

    async def pin_message(
        self, chat_id: int | str, message_id: int, *, silent: bool = False
    ) -> None:
        ptype, pid, ahash = self._resolve_peer(chat_id)
        await self.invoke_raw(pack_pin_message(ptype, pid, ahash, int(message_id), silent=silent))

    async def send_chat_action(
        self, chat_id: int | str, action: ChatAction | str
    ) -> None:
        ptype, pid, ahash = self._resolve_peer(chat_id)
        await self.invoke_raw(pack_set_typing(ptype, pid, ahash, str(action)))

    async def ban_user(
        self, chat_id: int | str, user_id: int | str, *, until_date: int | None = None
    ) -> None:
        _, cid, chash = self._resolve_peer(chat_id)
        _, uid, uhash = self._resolve_peer(user_id)
        await self.invoke_raw(
            pack_edit_banned(cid, chash, uid, uhash, view_messages=True, until_date=until_date or 0)
        )

    async def unban_user(self, chat_id: int | str, user_id: int | str) -> None:
        _, cid, chash = self._resolve_peer(chat_id)
        _, uid, uhash = self._resolve_peer(user_id)
        await self.invoke_raw(pack_edit_banned(cid, chash, uid, uhash, view_messages=False))

    async def mute_user(
        self, chat_id: int | str, user_id: int | str, *, until_date: int | None = None
    ) -> None:
        _, cid, chash = self._resolve_peer(chat_id)
        _, uid, uhash = self._resolve_peer(user_id)
        await self.invoke_raw(
            pack_edit_banned(cid, chash, uid, uhash, send_messages=True, until_date=until_date or 0)
        )

    async def kick_user(self, chat_id: int | str, user_id: int | str) -> None:
        await self.ban_user(chat_id, user_id)
        await self.unban_user(chat_id, user_id)

    async def get_chat(self, chat_id: int | str) -> ChatRef:
        cid = int(chat_id) if isinstance(chat_id, int) or str(chat_id).lstrip("-").isdigit() else 0
        rec = self.peers.get("channel", cid) or self.peers.get("chat", cid) or self.peers.get("user", cid)
        return ChatRef(
            id=cid,
            type=rec.peer_type if rec else "private",
            title=rec.username if rec else None,
        )
