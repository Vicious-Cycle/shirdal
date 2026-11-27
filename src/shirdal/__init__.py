from __future__ import annotations


import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from shirdal.client import SelfBot, Shirdal
    from shirdal.core.adapter import (
        AdapterError,
        DeviceProfile,
        FloodWaitError,
        TransportAdapter,
    )
    from shirdal.core.botapi_adapter import (
        BotAPIAdapter,
        ButtonStyle,
        WebhookServer,
        button,
        custom_emoji,
        custom_emoji_entity,
        date_time,
        date_time_entity,
        inline_keyboard,
        reply_button,
        reply_keyboard,
        rich_blockquote,
        rich_buttons,
        rich_code,
        rich_details,
        rich_divider,
        rich_footer,
        rich_heading,
        rich_math,
        rich_message,
        rich_paragraph,
        rich_table,
        rich_thinking,
    )
    from shirdal.core.events import (
        ChatAction,
        ChatRef,
        EventType,
        MediaRef,
        MessageEvent,
        UpdateEvent,
        UserRef,
    )
    from shirdal.core.hybrid_adapter import HybridAdapter
    from shirdal.core.hydrogram_adapter import HydrogramAdapter
    from shirdal.core.mock_adapter import MockAdapter
    from shirdal.core.native_mtproto_adapter import NativeMTProtoAdapter
    from shirdal.core.telethon_adapter import TelethonAdapter
    from shirdal.engine import (
        Context,
        Dispatcher,
        DraftStream,
        Filter,
        FSMContext,
        FSMStorage,
        MemoryStorage,
        ProgressTracker,
        RichDraftStream,
        ScheduledJob,
        Scheduler,
        State,
        StatesGroup,
        TransferProgress,
        TransferQueue,
        callback,
        command,
        group,
        incoming,
        outgoing,
        private,
        regex,
        reply,
        state,
        text,
    )
    from shirdal.engine.fsm import ANY_STATE, FSMStrategy
    from shirdal.engine.magic import F, MagicFilter
    from shirdal.engine.router import Router
    from shirdal.guard import (
        AntiFloodAdapter,
        AntiFloodConfig,
        FloodStats,
        Middleware,
        NextHandler,
    )
    from shirdal.multi import MultiBot
    from shirdal.plugins import PluginLoadResult, PluginManager
    from shirdal.storage import (
        CachedChat,
        EncryptedStorage,
        MySQLStorage,
        RedisStorage,
        SecretBox,
        SQLiteStorage,
    )

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "Shirdal": ("shirdal.client", "Shirdal"),
    "SelfBot": ("shirdal.client", "SelfBot"),
    "MultiBot": ("shirdal.multi", "MultiBot"),
    "TransportAdapter": ("shirdal.core.adapter", "TransportAdapter"),
    "DeviceProfile": ("shirdal.core.adapter", "DeviceProfile"),
    "AdapterError": ("shirdal.core.adapter", "AdapterError"),
    "FloodWaitError": ("shirdal.core.adapter", "FloodWaitError"),
    "EventType": ("shirdal.core.events", "EventType"),
    "ChatAction": ("shirdal.core.events", "ChatAction"),
    "MediaRef": ("shirdal.core.events", "MediaRef"),
    "UserRef": ("shirdal.core.events", "UserRef"),
    "ChatRef": ("shirdal.core.events", "ChatRef"),
    "MessageEvent": ("shirdal.core.events", "MessageEvent"),
    "UpdateEvent": ("shirdal.core.events", "UpdateEvent"),
    "MockAdapter": ("shirdal.core.mock_adapter", "MockAdapter"),
    "NativeMTProtoAdapter": ("shirdal.core.native_mtproto_adapter", "NativeMTProtoAdapter"),
    "TelethonAdapter": ("shirdal.core.telethon_adapter", "TelethonAdapter"),
    "BotAPIAdapter": ("shirdal.core.botapi_adapter", "BotAPIAdapter"),
    "WebhookServer": ("shirdal.core.botapi_adapter", "WebhookServer"),
    "ButtonStyle": ("shirdal.core.botapi_adapter", "ButtonStyle"),
    "button": ("shirdal.core.botapi_adapter", "button"),
    "inline_keyboard": ("shirdal.core.botapi_adapter", "inline_keyboard"),
    "reply_button": ("shirdal.core.botapi_adapter", "reply_button"),
    "reply_keyboard": ("shirdal.core.botapi_adapter", "reply_keyboard"),
    "custom_emoji": ("shirdal.core.botapi_adapter", "custom_emoji"),
    "custom_emoji_entity": ("shirdal.core.botapi_adapter", "custom_emoji_entity"),
    "date_time": ("shirdal.core.botapi_adapter", "date_time"),
    "date_time_entity": ("shirdal.core.botapi_adapter", "date_time_entity"),
    "rich_blockquote": ("shirdal.core.botapi_adapter", "rich_blockquote"),
    "rich_buttons": ("shirdal.core.botapi_adapter", "rich_buttons"),
    "rich_code": ("shirdal.core.botapi_adapter", "rich_code"),
    "rich_details": ("shirdal.core.botapi_adapter", "rich_details"),
    "rich_divider": ("shirdal.core.botapi_adapter", "rich_divider"),
    "rich_footer": ("shirdal.core.botapi_adapter", "rich_footer"),
    "rich_heading": ("shirdal.core.botapi_adapter", "rich_heading"),
    "rich_math": ("shirdal.core.botapi_adapter", "rich_math"),
    "rich_message": ("shirdal.core.botapi_adapter", "rich_message"),
    "rich_paragraph": ("shirdal.core.botapi_adapter", "rich_paragraph"),
    "rich_table": ("shirdal.core.botapi_adapter", "rich_table"),
    "rich_thinking": ("shirdal.core.botapi_adapter", "rich_thinking"),
    "HydrogramAdapter": ("shirdal.core.hydrogram_adapter", "HydrogramAdapter"),
    "HybridAdapter": ("shirdal.core.hybrid_adapter", "HybridAdapter"),
    "Context": ("shirdal.engine", "Context"),
    "DraftStream": ("shirdal.engine", "DraftStream"),
    "RichDraftStream": ("shirdal.engine", "RichDraftStream"),
    "Dispatcher": ("shirdal.engine", "Dispatcher"),
    "Filter": ("shirdal.engine", "Filter"),
    "MagicFilter": ("shirdal.engine.magic", "MagicFilter"),
    "F": ("shirdal.engine.magic", "F"),
    "Router": ("shirdal.engine.router", "Router"),
    "FSMStrategy": ("shirdal.engine.fsm", "FSMStrategy"),
    "ANY_STATE": ("shirdal.engine.fsm", "ANY_STATE"),
    "State": ("shirdal.engine", "State"),
    "StatesGroup": ("shirdal.engine", "StatesGroup"),
    "FSMStorage": ("shirdal.engine", "FSMStorage"),
    "MemoryStorage": ("shirdal.engine", "MemoryStorage"),
    "FSMContext": ("shirdal.engine", "FSMContext"),
    "Scheduler": ("shirdal.engine", "Scheduler"),
    "ScheduledJob": ("shirdal.engine", "ScheduledJob"),
    "ProgressTracker": ("shirdal.engine", "ProgressTracker"),
    "TransferProgress": ("shirdal.engine", "TransferProgress"),
    "TransferQueue": ("shirdal.engine", "TransferQueue"),
    "callback": ("shirdal.engine", "callback"),
    "command": ("shirdal.engine", "command"),
    "text": ("shirdal.engine", "text"),
    "outgoing": ("shirdal.engine", "outgoing"),
    "incoming": ("shirdal.engine", "incoming"),
    "private": ("shirdal.engine", "private"),
    "group": ("shirdal.engine", "group"),
    "reply": ("shirdal.engine", "reply"),
    "regex": ("shirdal.engine", "regex"),
    "state": ("shirdal.engine", "state"),
    "AntiFloodAdapter": ("shirdal.guard", "AntiFloodAdapter"),
    "AntiFloodConfig": ("shirdal.guard", "AntiFloodConfig"),
    "FloodStats": ("shirdal.guard", "FloodStats"),
    "Middleware": ("shirdal.guard", "Middleware"),
    "NextHandler": ("shirdal.guard", "NextHandler"),
    "PluginManager": ("shirdal.plugins", "PluginManager"),
    "PluginLoadResult": ("shirdal.plugins", "PluginLoadResult"),
    "SQLiteStorage": ("shirdal.storage", "SQLiteStorage"),
    "RedisStorage": ("shirdal.storage", "RedisStorage"),
    "MySQLStorage": ("shirdal.storage", "MySQLStorage"),
    "EncryptedStorage": ("shirdal.storage", "EncryptedStorage"),
    "SecretBox": ("shirdal.storage", "SecretBox"),
    "CachedChat": ("shirdal.storage", "CachedChat"),
}

__all__ = list(_LAZY_EXPORTS)
__version__ = "1.0.23"


def __getattr__(name: str) -> Any:
    spec = _LAZY_EXPORTS.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr_name = spec
    module = importlib.import_module(module_path)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
