"""MTProto encrypted sender: one TCP connection to one DC.

Handles: lazy invokeWithLayer+initConnection on the first request of every connection,
acks, msg_container, bad_server_salt / bad_msg_notification resend, new_session_created,
ping_delay_disconnect keepalive, and automatic reconnect with pending-request resend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from shirdal.mtproto.auth import HandshakeSession, RSAPublicKey
from shirdal.mtproto.crypto import MTProtoCryptoError
from shirdal.mtproto.session import (
    BAD_MSG_NOTIFICATION_ID,
    BAD_SERVER_SALT_ID,
    MSG_CONTAINER_ID,
    MSGS_ACK_ID,
    RPC_RESULT_ID,
    MTProtoRPCError,
    MTProtoSessionState,
    MTProtoWire,
)
from shirdal.mtproto.tl_codec import TLReader, TLWriter
from shirdal.mtproto.transport import MTProtoTransportError, TCPAbridgedTransport

_LOG = logging.getLogger("shirdal.mtproto")

PING_ID = 0x7ABE77EC
PONG_ID = 0x347773C5
NEW_SESSION_CREATED_ID = 0x9EC20908
PING_DELAY_DISCONNECT_ID = 0xF3427B8C
MSG_DETAILED_INFO_ID = 0x276D3EC6
MSG_NEW_DETAILED_INFO_ID = 0x809DB6DF
FUTURE_SALTS_ID = 0xAE500895
MSGS_STATE_INFO_ID = 0x04DEB57D
MSGS_ALL_INFO_ID = 0x8CC0D131
DESTROY_SESSION_OK_ID = 0xE22045FC
DESTROY_SESSION_NONE_ID = 0x62D350C9

_SERVICE_IDS = {
    MSGS_ACK_ID,
    FUTURE_SALTS_ID,
    MSGS_STATE_INFO_ID,
    MSGS_ALL_INFO_ID,
    DESTROY_SESSION_OK_ID,
    DESTROY_SESSION_NONE_ID,
}


@dataclass(slots=True)
class _Request:
    payload: bytes
    future: asyncio.Future[bytes]
    content_related: bool = True
    msg_id: int = 0
    resends: int = field(default=0)


UpdateCallback = Callable[[bytes], Awaitable[None]]
WrapCallback = Callable[[bytes], bytes]


class MTProtoSender:
    def __init__(
        self,
        state: MTProtoSessionState,
        *,
        rsa_keys: list[RSAPublicKey],
        wrap_first: WrapCallback | None = None,
        on_update: UpdateCallback | None = None,
        on_new_session: Callable[[], None] | None = None,
        on_auth_key: Callable[[], None] | None = None,
        ping_interval: float = 30.0,
        reconnect: bool = True,
        transport_timeout: float = 15.0,
    ) -> None:
        self.state = state
        self.wire = MTProtoWire(state)
        self.rsa_keys = rsa_keys
        self.wrap_first = wrap_first
        self.on_update = on_update
        self.on_new_session = on_new_session
        self.on_auth_key = on_auth_key
        self.ping_interval = ping_interval
        self.reconnect_enabled = reconnect
        self.transport_timeout = transport_timeout
        self.transport = TCPAbridgedTransport(state.host, state.port, timeout=transport_timeout)

        self._pending: dict[int, _Request] = {}
        self._inited = False
        self._running = False
        self._recv_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None
        self._reconnect_lock = asyncio.Lock()
        self._reconnect_tasks: set[asyncio.Task[None]] = set()
        self._time_synced = False

    # ---------------------------------------------------------------- lifecycle
    @property
    def is_connected(self) -> bool:
        return self._running and self.transport.is_connected

    async def connect(self) -> None:
        if self._running:
            return
        await self._open()
        self._running = True
        self._recv_task = asyncio.create_task(self._recv_loop())
        if self.ping_interval > 0:
            self._ping_task = asyncio.create_task(self._ping_loop())

    async def _open(self) -> None:
        self.transport = TCPAbridgedTransport(
            self.state.host, self.state.port, timeout=self.transport_timeout
        )
        await self.transport.connect()
        if self.state.auth_key is None:
            await self._handshake()
        self._inited = False

    async def _handshake(self) -> None:
        if not self.rsa_keys:
            raise MTProtoCryptoError("No RSA keys available for the MTProto handshake.")
        hs = HandshakeSession(self.rsa_keys)
        await self.transport.send(self.wire.pack_unencrypted(hs.step1_req_pq_multi()))
        _, res_pq = self.wire.unpack_unencrypted(await self.transport.recv())
        await self.transport.send(self.wire.pack_unencrypted(hs.step2_handle_res_pq(res_pq)))
        _, srv_dh = self.wire.unpack_unencrypted(await self.transport.recv())
        await self.transport.send(
            self.wire.pack_unencrypted(hs.step3_handle_server_dh_params(srv_dh))
        )
        _, dh_gen = self.wire.unpack_unencrypted(await self.transport.recv())
        auth_key, salt = hs.step4_handle_dh_gen(dh_gen)
        self.state.auth_key = auth_key
        self.state.server_salt = salt
        self.state.reset_runtime_counters()
        if self.on_auth_key is not None:
            self.on_auth_key()

    async def disconnect(self) -> None:
        self._running = False
        current = asyncio.current_task()
        for task in (self._ping_task, self._recv_task):
            if task is not None and task is not current:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._ping_task = None
        self._recv_task = None
        for rtask in list(self._reconnect_tasks):
            if rtask is not current:
                rtask.cancel()
                await asyncio.gather(rtask, return_exceptions=True)
        self._reconnect_tasks.clear()
        for req in self._pending.values():
            if not req.future.done():
                req.future.set_exception(ConnectionError("Disconnected before RPC completed."))
        self._pending.clear()
        await self.transport.close()

    # ------------------------------------------------------------------ sending
    async def ping(self, *, timeout: float = 10.0) -> float:
        if not self._running:
            raise ConnectionError("MTProto sender is not connected.")
        w = TLWriter()
        w.write_uint(PING_ID)
        w.write_long(struct.unpack("<q", os.urandom(8))[0])
        loop = asyncio.get_running_loop()
        req = _Request(payload=w.to_bytes(), future=loop.create_future(), content_related=True)
        t0 = time.perf_counter()
        await self._send_request(req)
        try:
            await asyncio.wait_for(asyncio.shield(req.future), timeout=timeout)
            return (time.perf_counter() - t0) * 1000.0
        finally:
            self._pending.pop(req.msg_id, None)

    async def invoke(self, payload: bytes, *, timeout: float = 20.0) -> bytes:
        if not self._running:
            raise ConnectionError("MTProto sender is not connected.")
        loop = asyncio.get_running_loop()
        req = _Request(payload=payload, future=loop.create_future())
        await self._send_request(req)
        try:
            return await asyncio.wait_for(asyncio.shield(req.future), timeout=timeout)
        finally:
            self._pending.pop(req.msg_id, None)

    async def _send_request(self, req: _Request) -> None:
        body = req.payload
        if req.content_related and not self._inited and self.wrap_first is not None:
            body = self.wrap_first(body)
            self._inited = True
        self._pending.pop(req.msg_id, None)
        msg_id, pkt = self.wire.pack_encrypted(body, content_related=req.content_related)
        req.msg_id = msg_id
        self._pending[msg_id] = req
        try:
            await self.transport.send(pkt)
        except (MTProtoTransportError, OSError) as exc:
            _LOG.warning("MTProto send failed (%s); will resend after reconnect.", exc)
            if self.reconnect_enabled and self._running:
                self._spawn_reconnect()

    def _spawn_reconnect(self) -> None:
        """Start a reconnect, keeping a strong ref so the task can't be GC'd mid-flight."""
        task = asyncio.create_task(self._reconnect())
        self._reconnect_tasks.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            self._reconnect_tasks.discard(t)
            if not t.cancelled() and (exc := t.exception()) is not None:
                _LOG.error("MTProto reconnect task crashed: %r", exc)

        task.add_done_callback(_done)

    async def _resend(self, bad_msg_id: int) -> None:
        req = self._pending.pop(bad_msg_id, None)
        if req is None or req.future.done():
            return
        req.resends += 1
        if req.resends > 5:
            req.future.set_exception(ConnectionError("Too many MTProto resends."))
            return
        await self._send_request(req)

    async def _resend_all(self) -> None:
        for req in list(self._pending.values()):
            if not req.future.done():
                await self._send_request(req)

    async def _send_service(self, body: bytes) -> None:
        _, pkt = self.wire.pack_encrypted(body, content_related=False)
        try:
            await self.transport.send(pkt)
        except (MTProtoTransportError, OSError) as exc:
            _LOG.debug("Service message send failed: %s", exc)

    # ---------------------------------------------------------------- keepalive
    async def _ping_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.ping_interval)
            if not self._running or not self.transport.is_connected:
                continue
            w = TLWriter()
            w.write_uint(PING_DELAY_DISCONNECT_ID)
            w.write_long(struct.unpack("<q", os.urandom(8))[0])
            w.write_int(int(self.ping_interval * 2.5))
            try:
                _, pkt = self.wire.pack_encrypted(w.to_bytes(), content_related=True)
                await self.transport.send(pkt)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("MTProto keepalive ping failed: %s", exc)

    # ---------------------------------------------------------------- reconnect
    async def _reconnect(self) -> None:
        if self._reconnect_lock.locked():
            return
        async with self._reconnect_lock:
            delay = 1.0
            while self._running:
                try:
                    await self.transport.close()
                    await self._open()
                    _LOG.info("MTProto reconnected to DC %s.", self.state.dc_id)
                    if self._recv_task is None or self._recv_task.done():
                        self._recv_task = asyncio.create_task(self._recv_loop())
                    await self._resend_all()
                    if self.on_new_session is not None:
                        self.on_new_session()
                    return
                except Exception as exc:  # noqa: BLE001
                    _LOG.warning("MTProto reconnect failed: %s (retry in %.0fs)", exc, delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)

    # ---------------------------------------------------------------- receiving
    async def _recv_loop(self) -> None:
        while self._running:
            try:
                raw_pkt = await self.transport.recv()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if not self._running:
                    return
                _LOG.warning("MTProto connection lost: %s", exc)
                if self.reconnect_enabled:
                    self._spawn_reconnect()
                else:
                    for req in self._pending.values():
                        if not req.future.done():
                            req.future.set_exception(ConnectionError(str(exc)))
                return

            try:
                msg_id, seq_no, body = self.wire.unpack_encrypted(raw_pkt, from_client=False)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("Dropping undecryptable MTProto packet: %s", exc)
                continue
            if not self._time_synced:
                self.state.sync_time_offset(msg_id)
                self._time_synced = True
            acks: list[int] = []
            try:
                await self._dispatch(msg_id, seq_no, body, acks)
            except Exception:  # noqa: BLE001
                _LOG.exception("Failed to process MTProto message 0x%08x", _cid(body))
            if acks:
                await self._send_service(self.wire.pack_acks(acks))

    async def _dispatch(self, msg_id: int, seq_no: int, body: bytes, acks: list[int]) -> None:
        if len(body) < 4:
            return
        if seq_no & 1:
            acks.append(msg_id)
        cid = _cid(body)

        if cid == MSG_CONTAINER_ID:
            for item_id, item_seq, item_body in self.wire.unpack_container(body):
                await self._dispatch(item_id, item_seq, item_body, acks)
            return

        if cid == RPC_RESULT_ID:
            req_id = struct.unpack_from("<q", body, 4)[0]
            req = self._pending.pop(req_id, None)
            try:
                _, res = self.wire.unpack_rpc_result(body)
            except MTProtoRPCError as exc:
                if req is not None and not req.future.done():
                    req.future.set_exception(exc)
                return
            if req is not None and not req.future.done():
                req.future.set_result(res)
            return

        if cid == BAD_SERVER_SALT_ID:
            bad_msg_id, _code, _salt = self.wire.handle_bad_server_salt(body)
            await self._resend(bad_msg_id)
            return

        if cid == BAD_MSG_NOTIFICATION_ID:
            bad_id, _bad_seq, code = self.wire.handle_bad_msg_notification(body)
            if code in (16, 17):
                self.state.sync_time_offset(msg_id)
                self.state._last_msg_id = 0
                await self._resend(bad_id)
            elif code in (32, 33, 34, 35):
                self.state.reset_runtime_counters()
                self._inited = False
                await self._resend_all()
            elif code == 48:
                await self._resend(bad_id)
            else:
                req = self._pending.pop(bad_id, None)
                if req is not None and not req.future.done():
                    req.future.set_exception(
                        MTProtoRPCError(400, f"BAD_MSG_NOTIFICATION_{code}")
                    )
            return

        if cid == NEW_SESSION_CREATED_ID:
            self.wire.handle_new_session_created(body)
            if self.on_new_session is not None:
                self.on_new_session()
            return

        if cid == PONG_ID:
            r = TLReader(body)
            r.read_uint()
            ping_msg_id = r.read_long()
            req = self._pending.pop(ping_msg_id, None)
            if req is not None and not req.future.done():
                req.future.set_result(body)
            return

        if cid in (MSG_DETAILED_INFO_ID, MSG_NEW_DETAILED_INFO_ID):
            r = TLReader(body)
            r.read_uint()
            if cid == MSG_DETAILED_INFO_ID:
                r.read_long()
            acks.append(r.read_long())
            return

        if cid in _SERVICE_IDS:
            return

        if self.on_update is not None:
            await self.on_update(body)


def _cid(body: bytes) -> int:
    return struct.unpack_from("<I", body, 0)[0] if len(body) >= 4 else 0
