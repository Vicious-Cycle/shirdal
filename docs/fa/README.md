<div dir="rtl">

# مستندات فارسی Shirdal (شیر‌دال)

شیر‌دال یک فریم‌ورک پایتون (۳.۱۱ به بالا) برای ساخت ربات‌های Bot API و کلاینت‌های MTProto است که لایهٔ منطق برنامه را از لایهٔ ارتباطی جدا می‌کند.

## نصب و ساخت پروژه

```bash
pip install shirdal
shirdal new my_bot --adapter botapi
cd my_bot
shirdal doctor
shirdal run main.py
```

## دکمه‌های رنگی، غیرفعال و ایموجی پرمیوم

در `button()` (کیبورد شیشه‌ای) و `reply_button()` (کیبورد معمولی) می‌توانید از `style` (`primary`، `success`، `danger`)، `icon` (آیدی ایموجی کاستوم) و `disabled=True` استفاده کنید:

```python
from shirdal import ButtonStyle, button, custom_emoji, date_time, inline_keyboard

badge = custom_emoji("5368324170671202286", "✨")
when = date_time(1764100000, "فردا", format="r")

kb = inline_keyboard([
    [
        button("تایید", "ok", style=ButtonStyle.SUCCESS, icon="5368324170671202286"),
        button("حذف", "del", style="danger"),
    ],
    [button("غیرفعال", "lock", style="primary", disabled=True)],
])

await ctx.reply(f"{badge} زمان اجرا: {when}", reply_markup=kb)
```

## پیام مخفی گروه (`Ephemeral`) و تگ اعضا

```python
# ارسال پاسخ که فقط برای کاربر ارسال‌کننده قابل مشاهده است
await ctx.reply_ephemeral("این پیام فقط برای شما نمایش داده می‌شود.")

# ثبت لقب متنی برای عضو گروه بدون نیاز به ادمین کردن
await ctx.set_member_tag("ویژه")
```

## استریم زنده و Rich Messages

برای پاسخ‌های هوش مصنوعی یا پیام‌های گزارش‌محور با جدول، آکاردئون و پشتیبانی راست‌به‌چپ (`is_rtl=True`):

```python
from shirdal import rich_heading, rich_table

async with ctx.stream_rich(is_rtl=True, can_stop=True) as stream:
    await stream.thinking("در حال پردازش...")
    await stream.update(
        blocks=[
            rich_heading("گزارش وضعیت", size=1),
            rich_table([["کاربران فعال", "۱٬۴۲۰"]], headers=["شاخص", "مقدار"]),
        ]
    )
```

## سرور Webhook داخلی (بدون FastAPI)

```python
server = adapter.create_webhook_server(
    host="0.0.0.0",
    port=8080,
    path="/tg-webhook",
    secret_token="my-secret",
)
await server.start()
```

مسیر `GET /health` برای بررسی سلامت سرویس و `POST /tg-webhook` با بررسی هدر `X-Telegram-Bot-Api-Secret-Token` به‌صورت آماده در دسترس است.

</div>
