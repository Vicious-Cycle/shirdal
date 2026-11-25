<div align="center" dir="rtl">

# Shirdal (شیر‌دال)

**فریم‌ورک سریع، ماژولار و Context-First پایتون برای تلگرام — مجهز به موتور Bot API 10.5 بدون وابستگی و هستهٔ بومی MTProto 2.0**

[English](README.md) | **فارسی**

</div>

---

<div dir="rtl">

شیر‌دال منطق ربات (`Dispatcher`، `Context`، فیلترها، `FSM`، ضدبلاک، پلاگین‌های زنده و ذخیره‌سازی) را پشت پروتکل `TransportAdapter` از لایهٔ شبکه جدا می‌کند. نتیجه یک معماری واحد است که هم با **موتور Bot API 10.5 بدون وابستگی** کار می‌کند و هم **هستهٔ بومی ۵ لایه‌ای MTProto 2.0** را در دل خود دارد.

## معماری سیستم

```text
  هندلرها و پلاگین‌های شما (Context، فیلترها، FSM، Scheduler، MultiBot)
                                │
                        TransportAdapter
         ┌──────────────────────┼──────────────────────┐
         ▼                      ▼                      ▼
   BotAPIAdapter      NativeMTProtoAdapter    Telethon / Hydrogram / Mock
 (HTTP Keep-Alive +   (TL Codec, AES-256-IGE,   (رپرهای MTProto و آداپتور
  WebhookServer)       TCP Abridged, PeerCache)  تست آفلاین)
```

## چرا Shirdal؟

- **Bot API بدون وابستگی خارجی (`BotAPIAdapter`):** کلاینت Keep-Alive با پشتیبانی اختیاری از `msgspec` و سرور `WebhookServer` داخلی روی `asyncio` (بدون نیاز به FastAPI یا aiohttp).
- **پشتیبانی کامل از Bot API 9.4 تا 10.5:** دکمه‌های رنگی (`ButtonStyle`: `primary`، `success`، `danger`)، ایموجی پرمیوم (`icon` و `custom_emoji()`)، دکمهٔ غیرفعال (`disabled`)، زمان محلی (`date_time()`)، پاسخ مخفی گروه (`ctx.reply_ephemeral()`)، استریم زندهٔ متن (`ctx.stream()`)، پیام‌های ساختاریافتهٔ `Rich Messages` (`ctx.reply_rich()` و `ctx.stream_rich()`)، تگ اعضا (`ctx.set_member_tag()`)، تاپیک در پیوی و `set_my_settings()`.
- **هستهٔ بومی ۵ لایه‌ای MTProto 2.0 (`shirdal.mtproto` و `NativeMTProtoAdapter`):**
  - کدک باینری Zero-Copy (`TLReader`/`TLWriter`) + کدجنراتور خودکار `.tl` به `@dataclass(slots=True)`.
  - رمزنگاری `AES-256-IGE`، استخراج کلید MTProto 2.0، `AuthKey`، تجزیهٔ Pollard's rho و `HandshakeSession` سه مرحله‌ای.
  - ترنسپورت `TCPAbridgedTransport`، سشن SQLite (`MTProtoSessionState`) و `MTProtoWire` (`msg_container`، `msgs_ack`، `bad_server_salt`، `gzip_packed`، `rpc_result`).
  - کش دائمی `PeerCache` (حافظه + SQLite)، ردیاب گپ آپدیت‌ها (`UpdateStateTracker`) و آپلود/دانلود موازی `FileTransferManager`.
- **آماده برای محیط واقعی:** محافظ ضدبلاک `AntiFloodAdapter`، پلاگین‌های Hot-Reload، `SQLiteStorage` (حالت WAL + کش L1)، `RedisStorage`، `MySQLStorage`، `EncryptedStorage`، `MultiBot` و CLI کامل (`shirdal new`، `shirdal doctor`، `shirdal run`).

## نصب

```bash
pip install shirdal
pip install "shirdal[fast]"    # بهینه‌سازی سرعت با uvloop و msgspec
pip install "shirdal[crypto]"  # برای NativeMTProtoAdapter و EncryptedStorage
```

## مستندات

- [راهنمای کامل فارسی](docs/fa/README.md)
- [شروع سریع و CLI](docs/getting-started.md)
- [قابلیت‌های Bot API 10.5](docs/bot-api.md)
- [راهنمای Rich Messages](docs/rich-messages.md)
- [معماری هستهٔ بومی MTProto 2.0](docs/native-mtproto.md)
- [سرور Webhook و استقرار](docs/webhook-and-deployment.md)

## اجرای تست‌ها

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

</div>
