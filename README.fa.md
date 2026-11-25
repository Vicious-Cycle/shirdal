<div align="center" dir="rtl">

# Shirdal (شیر‌دال)

**فریم‌ورک سریع، تمیز و Context-First پایتون برای ساخت سلف‌بات‌های تلگرام**

[English](README.md) | **فارسی**

</div>

## ویژگی‌های کلیدی

- **هسته آداپتور (`TransportAdapter`):** مستقل از موتور MTProto زیرین، همراه با `TelethonAdapter`، `HydrogramAdapter`، پروفایل دستگاه تمیز (`DeviceProfile`)، پشتیبانی از `StringSession` و `MockAdapter` برای تست بدون نیاز به اکانت.
- **رابط تمیز `Context`:** متدهای `ctx.reply()`، `ctx.edit()`، `ctx.reply_media()`، `ctx.reply_album()`، `ctx.download()`، `ctx.react()`، `ctx.pin()`، `ctx.ban()`، `ctx.mute()`، `ctx.kick()`، `ctx.get_chat()`، `auto_delete` غیرمسدودکننده و `async with ctx.typing():`.
- **فیلترهای ترکیبی:** ترکیب `command`، `regex`، `state`، `outgoing`، `incoming`، `private`، `group`، `reply` و `text` با عملگرهای `&`، `|` و `~`.
- **محافظ ضدبلاک (`AntiFloodAdapter`):** فاصله‌گذاری خودکار به ازای هر چت، کنترل هم‌زمانی و بازیابی هوشمند `FloodWaitError`.
- **پلاگین‌های `Hot-Reload`:** بارگذاری و به‌روزرسانی زنده ماژول‌های `plugins/` بدون قطع اتصال اکانت.
- **میدل‌ور و ماشین وضعیت (`FSM`):** پایپ‌لاین `@bot.use`، مدیریت خطای سراسری `@bot.on_error` و `StatesGroup`.
- **ذخیره‌سازی و رمزنگاری:** `SQLiteStorage` (حالت `WAL` بهینه + کش L1)، `RedisStorage`، `MySQLStorage` و `EncryptedStorage`.
- **اجرای چنداکانتی و زمان‌بند:** مدیریت هم‌زمان اکانت‌ها با `MultiBot` و اجرای دوره‌ای با `@bot.every(...)`.
- **بهینه برای آپلودرها:** `ProgressTracker` ضداسپم و `TransferQueue` برای کنترل صف آپلود و دانلود.
- **ابزار خط فرمان (`CLI`):** دستورات `shirdal new`، `shirdal doctor` و `shirdal run`.

## نصب

```bash
pip install shirdal
# همراه با Telethon و uvloop:
pip install "shirdal[telethon,fast]"
```

## شروع سریع

```bash
shirdal new my_selfbot --adapter telethon
cd my_selfbot
shirdal doctor
shirdal run main.py
```

## اجرای تست‌ها

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## لایسنس

منتشرشده تحت لایسنس [LGPL-3.0-or-later](LICENSE).
