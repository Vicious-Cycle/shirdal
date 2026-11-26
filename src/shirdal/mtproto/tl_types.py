"""Core Telegram Layer 195 TL constructors, serializers, and update/peer parsers."""

from __future__ import annotations

import html.parser
import os
import struct
from dataclasses import dataclass, field
from typing import Any

from shirdal.mtproto.tl_codec import TLReader, TLWriter

# ---------------------------------------------------------------------------
# Layer & Connection
# ---------------------------------------------------------------------------
TELEGRAM_LAYER = 195
INVOKE_WITH_LAYER_ID = 0xDA9B0D0D
INIT_CONNECTION_ID = 0xC1CD5EA9

# ---------------------------------------------------------------------------
# Service / Ping
# ---------------------------------------------------------------------------
PING_ID = 0x7ABE77EC
PING_DELAY_DISCONNECT_ID = 0xF3427B8C
PONG_ID = 0x347773C5
NEW_SESSION_CREATED_ID = 0x9EC20908

# ---------------------------------------------------------------------------
# InputPeer / Peer
# ---------------------------------------------------------------------------
INPUT_PEER_EMPTY_ID = 0x7F3B18EA
INPUT_PEER_SELF_ID = 0x7DA07EC9
INPUT_PEER_CHAT_ID = 0x35A95CB9
INPUT_PEER_USER_ID = 0xDDE8A54C
INPUT_PEER_CHANNEL_ID = 0x27BCBBFC

PEER_USER_ID = 0x59511722
PEER_CHAT_ID = 0x36C6019A
PEER_CHANNEL_ID = 0xA2A5371E

# ---------------------------------------------------------------------------
# Auth & Account
# ---------------------------------------------------------------------------
AUTH_SEND_CODE_ID = 0xA677244F
CODE_SETTINGS_ID = 0xAD253D78
AUTH_SIGN_IN_ID = 0x8D52A951
AUTH_IMPORT_BOT_AUTHORIZATION_ID = 0x67A3FF2C
ACCOUNT_GET_PASSWORD_ID = 0x548A30F5
AUTH_CHECK_PASSWORD_ID = 0xD18B4D16
INPUT_CHECK_PASSWORD_SRP_ID = 0xD27FF082
AUTH_EXPORT_AUTHORIZATION_ID = 0xE5BFFFCD
AUTH_IMPORT_AUTHORIZATION_ID = 0xA57A7DEB

# ---------------------------------------------------------------------------
# Updates & Contacts
# ---------------------------------------------------------------------------
UPDATES_GET_STATE_ID = 0xEDD4882A
UPDATES_GET_DIFFERENCE_ID = 0x19C2F763
CONTACTS_RESOLVE_USERNAME_ID = 0xF93CCBA3

# ---------------------------------------------------------------------------
# Messages & Channels
# ---------------------------------------------------------------------------
MESSAGES_SEND_MESSAGE_ID = 0x983F9745
MESSAGES_EDIT_MESSAGE_ID = 0xDFD14005
MESSAGES_DELETE_MESSAGES_ID = 0xE58E95D2
CHANNELS_DELETE_MESSAGES_ID = 0x84C1FD4E
MESSAGES_SET_TYPING_ID = 0x58943EE2
MESSAGES_SEND_REACTION_ID = 0xD30D78D4
REACTION_EMOJI_ID = 0x1B2286B8
MESSAGES_UPDATE_PINNED_MESSAGE_ID = 0xD2AAF7EC
MESSAGES_SEND_MEDIA_ID = 0x72CCC23D
CHANNELS_EDIT_BANNED_ID = 0x96E6CD81
CHAT_BANNED_RIGHTS_ID = 0x9F120418
MESSAGES_DELETE_CHAT_USER_ID = 0xD4C06C9F
CHANNELS_GET_FULL_CHANNEL_ID = 0x08736A09
MESSAGES_GET_FULL_CHAT_ID = 0xAEB00B34
USERS_GET_FULL_USER_ID = 0xB60F5918

# SendMessageAction
ACTION_TYPING_ID = 0x16BF744E
ACTION_CANCEL_ID = 0xFD5EC8F5
ACTION_UPLOAD_PHOTO_ID = 0xD1D34A26
ACTION_UPLOAD_DOCUMENT_ID = 0xAA0CDFF4

# Upload / Media
UPLOAD_SAVE_FILE_PART_ID = 0xB304A621
UPLOAD_SAVE_BIG_FILE_PART_ID = 0xDE7B673D
UPLOAD_GET_FILE_ID = 0xBE5335BE
INPUT_FILE_ID = 0xF52FF27F
INPUT_FILE_BIG_ID = 0xFA4F0BB5
INPUT_MEDIA_UPLOADED_PHOTO_ID = 0x1E287D04
INPUT_MEDIA_UPLOADED_DOCUMENT_ID = 0x5B38C6C1

# Entities
ENTITY_BOLD_ID = 0xBD610BC9
ENTITY_ITALIC_ID = 0x826F8B60
ENTITY_CODE_ID = 0x28A20571
ENTITY_PRE_ID = 0x73924BE0
ENTITY_TEXT_URL_ID = 0x76A6D327
ENTITY_UNDERLINE_ID = 0x9C4E7E8B
ENTITY_STRIKE_ID = 0xBF0693D4
ENTITY_SPOILER_ID = 0x32CA960F

# Update Containers
UPDATES_TOO_LONG_ID = 0xE317AF7E
UPDATE_SHORT_MESSAGE_ID = 0x313BC7F8
UPDATE_SHORT_CHAT_MESSAGE_ID = 0x4D6DEEA5
UPDATE_SHORT_ID = 0x78D4DEC1
UPDATES_COMBINED_ID = 0x725B04C3
UPDATES_ID = 0x74AE4240
UPDATE_SHORT_SENT_MESSAGE_ID = 0x9015E101

# Individual Updates
UPDATE_NEW_MESSAGE_ID = 0x1F2B0AFD
UPDATE_EDIT_MESSAGE_ID = 0xE40370A3
UPDATE_DELETE_MESSAGES_ID = 0xA20DB0E5
UPDATE_NEW_CHANNEL_MESSAGE_ID = 0x62BA04D9
UPDATE_EDIT_CHANNEL_MESSAGE_ID = 0x1B3F4DF7
UPDATE_DELETE_CHANNEL_MESSAGES_ID = 0xC32D5B12

# Message / User / Chat constructors
MESSAGE_ID = 0x94345242
MESSAGE_EMPTY_ID = 0x90A6CA84
MESSAGE_SERVICE_ID = 0x2B085862


def random_id() -> int:
    return struct.unpack("<q", os.urandom(8))[0]


def write_input_peer(w: TLWriter, peer_type: str, peer_id: int, access_hash: int = 0) -> None:
    ptype = peer_type.lower()
    if ptype == "self":
        w.write_uint(INPUT_PEER_SELF_ID)
    elif ptype == "user":
        w.write_uint(INPUT_PEER_USER_ID)
        w.write_long(peer_id)
        w.write_long(access_hash)
    elif ptype == "chat":
        w.write_uint(INPUT_PEER_CHAT_ID)
        w.write_long(peer_id)
    elif ptype == "channel":
        w.write_uint(INPUT_PEER_CHANNEL_ID)
        w.write_long(peer_id)
        w.write_long(access_hash)
    else:
        w.write_uint(INPUT_PEER_EMPTY_ID)


def pack_invoke_with_layer(
    layer: int,
    api_id: int,
    device_model: str,
    system_version: str,
    app_version: str,
    system_lang_code: str,
    lang_pack: str,
    lang_code: str,
    query: bytes,
) -> bytes:
    w = TLWriter()
    w.write_uint(INVOKE_WITH_LAYER_ID)
    w.write_int(layer)
    w.write_uint(INIT_CONNECTION_ID)
    w.write_int(0)  # flags
    w.write_int(api_id)
    w.write_string(device_model)
    w.write_string(system_version)
    w.write_string(app_version)
    w.write_string(system_lang_code)
    w.write_string(lang_pack)
    w.write_string(lang_code)
    w.write_raw(query)
    return w.to_bytes()


def pack_ping(ping_id: int) -> bytes:
    w = TLWriter()
    w.write_uint(PING_ID)
    w.write_long(ping_id)
    return w.to_bytes()


def pack_auth_send_code(phone_number: str, api_id: int, api_hash: str) -> bytes:
    w = TLWriter()
    w.write_uint(AUTH_SEND_CODE_ID)
    w.write_string(phone_number)
    w.write_int(api_id)
    w.write_string(api_hash)
    w.write_uint(CODE_SETTINGS_ID)
    w.write_int(0)  # flags
    return w.to_bytes()


def pack_auth_sign_in(phone_number: str, phone_code_hash: str, phone_code: str) -> bytes:
    w = TLWriter()
    w.write_uint(AUTH_SIGN_IN_ID)
    w.write_int(1)  # flags: bit 0 = phone_code
    w.write_string(phone_number)
    w.write_string(phone_code_hash)
    w.write_string(phone_code)
    return w.to_bytes()


def pack_import_bot_authorization(api_id: int, api_hash: str, bot_auth_token: str) -> bytes:
    w = TLWriter()
    w.write_uint(AUTH_IMPORT_BOT_AUTHORIZATION_ID)
    w.write_int(0)  # flags
    w.write_int(api_id)
    w.write_string(api_hash)
    w.write_string(bot_auth_token)
    return w.to_bytes()


def pack_account_get_password() -> bytes:
    w = TLWriter()
    w.write_uint(ACCOUNT_GET_PASSWORD_ID)
    return w.to_bytes()


def pack_auth_check_password(srp_id: int, A: bytes, M1: bytes) -> bytes:
    w = TLWriter()
    w.write_uint(AUTH_CHECK_PASSWORD_ID)
    w.write_uint(INPUT_CHECK_PASSWORD_SRP_ID)
    w.write_long(srp_id)
    w.write_bytes(A)
    w.write_bytes(M1)
    return w.to_bytes()


def pack_updates_get_state() -> bytes:
    w = TLWriter()
    w.write_uint(UPDATES_GET_STATE_ID)
    return w.to_bytes()


def pack_updates_get_difference(pts: int, date: int, qts: int) -> bytes:
    w = TLWriter()
    w.write_uint(UPDATES_GET_DIFFERENCE_ID)
    w.write_int(0)  # flags
    w.write_int(pts)
    w.write_int(date)
    w.write_int(qts)
    return w.to_bytes()


def pack_resolve_username(username: str) -> bytes:
    w = TLWriter()
    w.write_uint(CONTACTS_RESOLVE_USERNAME_ID)
    w.write_string(username.lstrip("@"))
    return w.to_bytes()


class _HTMLTextParser(html.parser.HTMLParser):
    """Minimal HTML -> (plain_text, [(type_id, offset, length, extra)]) parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.entities: list[tuple[int, int, int, str | None]] = []
        self._stack: list[tuple[int, int, str | None]] = []
        self._length = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        eid: int | None = None
        extra: str | None = None
        if t in ("b", "strong"):
            eid = ENTITY_BOLD_ID
        elif t in ("i", "em"):
            eid = ENTITY_ITALIC_ID
        elif t == "code":
            eid = ENTITY_CODE_ID
        elif t == "pre":
            eid = ENTITY_PRE_ID
            extra = dict(attrs).get("language", "") or ""
        elif t == "u":
            eid = ENTITY_UNDERLINE_ID
        elif t in ("s", "strike", "del"):
            eid = ENTITY_STRIKE_ID
        elif t in ("tg-spoiler", "spoiler"):
            eid = ENTITY_SPOILER_ID
        elif t == "a":
            href = dict(attrs).get("href")
            if href:
                eid = ENTITY_TEXT_URL_ID
                extra = href
        if eid is not None:
            self._stack.append((eid, self._length, extra))

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            eid, start, extra = self._stack.pop()
            length = self._length - start
            if length > 0:
                self.entities.append((eid, start, length, extra))

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        self._length += len(data.encode("utf-16-le")) // 2


def parse_html_entities(raw_html: str) -> tuple[str, list[tuple[int, int, int, str | None]]]:
    parser = _HTMLTextParser()
    parser.feed(raw_html)
    parser.close()
    return "".join(parser.text_parts), parser.entities


def _write_entities(w: TLWriter, entities: list[tuple[int, int, int, str | None]]) -> None:
    w.write_uint(0x1CB5C415)  # vector
    w.write_int(len(entities))
    for eid, offset, length, extra in entities:
        w.write_uint(eid)
        w.write_int(offset)
        w.write_int(length)
        if eid in (ENTITY_PRE_ID, ENTITY_TEXT_URL_ID):
            w.write_string(extra or "")


def pack_send_message(
    peer_type: str,
    peer_id: int,
    access_hash: int,
    text: str,
    *,
    reply_to_msg_id: int | None = None,
    parse_mode: str | None = None,
    no_webpage: bool = False,
) -> bytes:
    entities: list[tuple[int, int, int, str | None]] = []
    if parse_mode and parse_mode.lower() == "html":
        text, entities = parse_html_entities(text)

    flags = 0
    if no_webpage:
        flags |= 1 << 1
    if reply_to_msg_id is not None:
        flags |= 1 << 0
    if entities:
        flags |= 1 << 3

    w = TLWriter()
    w.write_uint(MESSAGES_SEND_MESSAGE_ID)
    w.write_int(flags)
    write_input_peer(w, peer_type, peer_id, access_hash)
    if reply_to_msg_id is not None:
        # inputReplyToMessage#22c0f6d5
        w.write_uint(0x22C0F6D5)
        w.write_int(0)  # flags
        w.write_int(reply_to_msg_id)
    w.write_string(text)
    w.write_long(random_id())
    if entities:
        _write_entities(w, entities)
    return w.to_bytes()


def pack_edit_message(
    peer_type: str,
    peer_id: int,
    access_hash: int,
    msg_id: int,
    text: str,
    *,
    parse_mode: str | None = None,
) -> bytes:
    entities: list[tuple[int, int, int, str | None]] = []
    if parse_mode and parse_mode.lower() == "html":
        text, entities = parse_html_entities(text)

    flags = 1 << 11  # message
    if entities:
        flags |= 1 << 3

    w = TLWriter()
    w.write_uint(MESSAGES_EDIT_MESSAGE_ID)
    w.write_int(flags)
    write_input_peer(w, peer_type, peer_id, access_hash)
    w.write_int(msg_id)
    w.write_string(text)
    if entities:
        _write_entities(w, entities)
    return w.to_bytes()


def pack_delete_messages(
    peer_type: str,
    peer_id: int,
    access_hash: int,
    msg_ids: list[int],
    *,
    revoke: bool = True,
) -> bytes:
    w = TLWriter()
    if peer_type.lower() == "channel":
        w.write_uint(CHANNELS_DELETE_MESSAGES_ID)
        w.write_uint(0xF36700D9)  # inputChannel
        w.write_long(peer_id)
        w.write_long(access_hash)
        w.write_vector(msg_ids, TLWriter.write_int)
    else:
        w.write_uint(MESSAGES_DELETE_MESSAGES_ID)
        w.write_int(1 if revoke else 0)
        w.write_vector(msg_ids, TLWriter.write_int)
    return w.to_bytes()


def pack_set_typing(peer_type: str, peer_id: int, access_hash: int, action: str = "typing") -> bytes:
    action_map = {
        "typing": ACTION_TYPING_ID,
        "cancel": ACTION_CANCEL_ID,
        "upload_photo": ACTION_UPLOAD_PHOTO_ID,
        "upload_document": ACTION_UPLOAD_DOCUMENT_ID,
    }
    w = TLWriter()
    w.write_uint(MESSAGES_SET_TYPING_ID)
    w.write_int(0)  # flags
    write_input_peer(w, peer_type, peer_id, access_hash)
    w.write_uint(action_map.get(action, ACTION_TYPING_ID))
    return w.to_bytes()


def pack_send_reaction(peer_type: str, peer_id: int, access_hash: int, msg_id: int, emoji: str) -> bytes:
    w = TLWriter()
    w.write_uint(MESSAGES_SEND_REACTION_ID)
    w.write_int(1 << 0)  # reaction flag
    write_input_peer(w, peer_type, peer_id, access_hash)
    w.write_int(msg_id)
    w.write_uint(0x1CB5C415)  # vector
    w.write_int(1)
    w.write_uint(REACTION_EMOJI_ID)
    w.write_string(emoji)
    return w.to_bytes()


def pack_pin_message(
    peer_type: str, peer_id: int, access_hash: int, msg_id: int, *, silent: bool = False
) -> bytes:
    w = TLWriter()
    w.write_uint(MESSAGES_UPDATE_PINNED_MESSAGE_ID)
    w.write_int(1 if silent else 0)
    write_input_peer(w, peer_type, peer_id, access_hash)
    w.write_int(msg_id)
    return w.to_bytes()


def pack_save_file_part(file_id: int, file_part: int, data: bytes) -> bytes:
    w = TLWriter()
    w.write_uint(UPLOAD_SAVE_FILE_PART_ID)
    w.write_long(file_id)
    w.write_int(file_part)
    w.write_bytes(data)
    return w.to_bytes()


def pack_send_media_document(
    peer_type: str,
    peer_id: int,
    access_hash: int,
    file_id: int,
    parts: int,
    name: str,
    mime_type: str = "application/octet-stream",
    caption: str = "",
) -> bytes:
    w = TLWriter()
    w.write_uint(MESSAGES_SEND_MEDIA_ID)
    w.write_int(0)  # flags
    write_input_peer(w, peer_type, peer_id, access_hash)
    w.write_uint(INPUT_MEDIA_UPLOADED_DOCUMENT_ID)
    w.write_int(0)  # media flags
    w.write_uint(INPUT_FILE_ID)
    w.write_long(file_id)
    w.write_int(parts)
    w.write_string(name)
    w.write_string("")  # md5_checksum
    w.write_string(mime_type)
    w.write_uint(0x1CB5C415)  # attributes vector
    w.write_int(0)
    w.write_string(caption)
    w.write_long(random_id())
    return w.to_bytes()


def pack_edit_banned(
    channel_id: int,
    channel_hash: int,
    user_id: int,
    user_hash: int,
    *,
    view_messages: bool = False,
    send_messages: bool = False,
    until_date: int = 0,
) -> bytes:
    w = TLWriter()
    w.write_uint(CHANNELS_EDIT_BANNED_ID)
    w.write_uint(0xF36700D9)  # inputChannel
    w.write_long(channel_id)
    w.write_long(channel_hash)
    write_input_peer(w, "user", user_id, user_hash)
    w.write_uint(CHAT_BANNED_RIGHTS_ID)
    rights_flags = 0
    if view_messages:
        rights_flags |= 1 << 0
    if send_messages:
        rights_flags |= 1 << 1
    w.write_int(rights_flags)
    w.write_int(until_date)
    return w.to_bytes()


@dataclass(slots=True)
class ParsedUpdate:
    kind: str  # new_message | edit_message | delete_messages | raw
    chat_id: int = 0
    chat_type: str = "private"
    sender_id: int = 0
    message_id: int = 0
    text: str = ""
    is_outgoing: bool = False
    pts: int = 0
    pts_count: int = 0
    deleted_ids: list[int] = field(default_factory=list)


def parse_updates_payload(payload: bytes) -> list[ParsedUpdate]:
    """Best-effort parser for Telegram updateShortMessage / updateShortChatMessage / updates."""
    if len(payload) < 4:
        return [ParsedUpdate(kind="raw")]
    r = TLReader(payload)
    cid = r.read_uint()

    if cid == UPDATE_SHORT_MESSAGE_ID:
        flags = r.read_int()
        msg_id = r.read_int()
        user_id = r.read_long()
        text = r.read_string()
        pts = r.read_int()
        pts_count = r.read_int()
        _date = r.read_int()
        is_out = bool(flags & (1 << 1))
        return [
            ParsedUpdate(
                kind="new_message",
                chat_id=user_id,
                chat_type="private",
                sender_id=user_id,
                message_id=msg_id,
                text=text,
                is_outgoing=is_out,
                pts=pts,
                pts_count=pts_count,
            )
        ]

    if cid == UPDATE_SHORT_CHAT_MESSAGE_ID:
        flags = r.read_int()
        msg_id = r.read_int()
        from_id = r.read_long()
        chat_id = r.read_long()
        text = r.read_string()
        pts = r.read_int()
        pts_count = r.read_int()
        _date = r.read_int()
        is_out = bool(flags & (1 << 1))
        return [
            ParsedUpdate(
                kind="new_message",
                chat_id=chat_id,
                chat_type="group",
                sender_id=from_id,
                message_id=msg_id,
                text=text,
                is_outgoing=is_out,
                pts=pts,
                pts_count=pts_count,
            )
        ]

    if cid == UPDATES_TOO_LONG_ID:
        return [ParsedUpdate(kind="updates_too_long")]

    return [ParsedUpdate(kind="raw")]
