<div align="center" dir="rtl">

# Shirdal (شیر‌دال)

**فریم‌ورک سریع و Context-First پایتون برای Bot API تلگرام و کلاینت‌های MTProto**

[English](README.md) | **فارسی**

</div>

<div dir="rtl">

شیر‌دال منطق ربات را از لایهٔ ارتباطی جدا می‌کند. هندلرها، فیلترها، ماشین وضعیت (FSM) و پلاگین‌ها را یک بار بنویسید و روی `BotAPIAdapter` (بدون وابستگی خارجی، با Polling یا `WebhookServer` داخلی)، `TelethonAdapter`، `HydrogramAdapter` یا `MockAdapter` اجرا کنید.

## قابلیت‌های اصلی

- **آداپتور Bot API بدون وابستگی (`BotAPIAdapter`):** کلاینت HTTP/HTTPS با Keep-Alive، پشتیبانی اختیاری از `msgspec` و سرور `WebhookServer` داخلی بر پایهٔ `asyncio` (بدون نیاز به FastAPI).
- **پشتیبانی از Bot API جدید (9.4 تا 10.5):** دکمه‌های رنگی (`primary`، `success`، `danger`)، آیکون و متن ایموجی پرمیوم (`icon` و `custom_emoji()`)، دکمهٔ غیرفعال (`disabled`)، زمان محلی (`date_time()`)، پاسخ مخفی در گروه (`ctx.reply_ephemeral()`)، استریم زندهٔ متن (`ctx.stream()`)، پیام‌های ساختاریافتهٔ `Rich Messages` (`ctx.reply_rich()` و `ctx.stream_rich()`)، تگ اعضا (`ctx.set_member_tag()`)، تاپیک در پیوی و `set_my_settings()`.
- **آداپتورهای MTProto:** پشتیبانی از `TelethonAdapter` و `HydrogramAdapter` (با فالبک Pyrogram)، `DeviceProfile` و `bot_token`.
- **رابط `Context` و فیلترهای ترکیبی:** متدهای `ctx.reply()`، `ctx.edit()`، `ctx.answer()`، `ctx.reply_media()`، `ctx.download()`، `ctx.react()`، `ctx.pin()` و فیلترهای `command`، `regex`، `callback`، `state`، `private`، `group` با عملگرهای `&`، `|` و `~`.
- **ابزارهای محیط واقعی:** `AntiFloodAdapter` با بازیابی خودکار `FloodWaitError`، پلاگین‌های Hot-Reload، میدل‌ورها، `SQLiteStorage` (حالت WAL + کش L1)، `RedisStorage`، `MySQLStorage`، `EncryptedStorage`، `MultiBot` و `@bot.every()`.

## نصب و شروع سریع

```bash
pip install shirdal
# یا همراه با Telethon و uvloop:
pip install "shirdal[telethon,fast]"
```

```bash
shirdal new my_bot --adapter botapi
cd my_bot
shirdal doctor
shirdal run main.py
```

## مستندات

- [راهنمای کامل فارسی](docs/fa/README.md)
- [شروع سریع و CLI](docs/getting-started.md)
- [قابلیت‌های Bot API (دکمه رنگی، ایموجی پرمیوم، Ephemeral و استریم)](docs/bot-api.md)
- [راهنمای Rich Messages](docs/rich-messages.md)
- [سرور Webhook و استقرار](docs/webhook-and-deployment.md)

## اجرای تست‌ها

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## لایسنس

منتشرشده تحت لایسنس [LGPL-3.0-or-later](LICENSE).

</div>
