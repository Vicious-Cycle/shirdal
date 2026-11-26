<div align="center" dir="rtl">

<img src="docs/assets/logo-banner.png" alt="لوگوی شیر‌دال" width="460" />

**یک فریم‌ورک مدرن پایتون برای ربات‌ها و یوزربات‌های تلگرام**

[مستندات آنلاین](https://vicious-cycle.github.io/shirdal/fa/) • [بنچمارک‌ها](https://github.com/Vicious-Cycle/shircrypt#benchmarks) • [دانلود مستندات (.md)](https://vicious-cycle.github.io/shirdal/shirdal-docs.md) • [English](README.md)

[![CI](https://github.com/Vicious-Cycle/shirdal/actions/workflows/ci.yml/badge.svg)](https://github.com/Vicious-Cycle/shirdal/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/shirdal.svg?color=d4a843)](https://pypi.org/project/shirdal/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%2B-3776AB.svg)](https://www.python.org/downloads/)
[![Crypto](https://img.shields.io/badge/crypto-shircrypt%204.67x-d4a843.svg)](https://github.com/Vicious-Cycle/shircrypt)
[![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)](LICENSE)

</div>

---

<div dir="rtl">

## شیر‌دال (Shirdal)

> فریم‌ورک ناهمگام، سریع و Context-First پایتون برای Bot API 10.5 و هستهٔ بومی MTProto 2.0

کد ربات را یک‌بار بنویسید و روی **Bot API**، کلاینت **Native MTProto 2.0** یا **هر دو به‌صورت هم‌زمان (`HybridAdapter`)** اجرا کنید — همراه با پشتیبانی کامل از دکمه‌های رنگی، ایموجی پرمیوم، استریم زنده و آپلود فایل‌های بالای ۵۰ مگابایت.

<div dir="ltr">

```python
import os
from shirdal import BotAPIAdapter, Context, F, Router, Shirdal

router = Router("main")

@router.on_command("start")
async def start(ctx: Context) -> None:
    reply_ctx = await ctx.ask("اسمت چیه؟", timeout=60, filters=F.text)
    await reply_ctx.reply(f"سلام <b>{reply_ctx.text}</b>!")

if __name__ == "__main__":
    bot = Shirdal(BotAPIAdapter(os.environ["BOT_TOKEN"]))
    bot.include_router(router)
    bot.run()
```

</div>

## ویژگی‌های کلیدی

- **آمادهٔ اجرا:** نصب سریع با `pip` بدون نیاز به کتابخانهٔ HTTP یا رمزنگاری خارجی.
- **حالت ترکیبی (`HybridAdapter`):** اجرای ربات روی Bot API و ارسال خودکار فایل‌های بالای ۵۰ مگابایت از طریق MTProto.
- **فوق‌العاده سریع:** شتاب‌یافته با اکستنشن Rust [**`shircrypt`**](https://github.com/Vicious-Cycle/shircrypt) (**۴.۶۷ برابر** سریع‌تر از `TgCrypto` و تا **۱۱.۸۴ برابر** در CTR) + پشتیبانی از `uvloop` و `msgspec`.
- **مدرن و ماژولار:** دارای `Router` درختی، فیلتر جادویی `F`، سیستم `FSM` با پشتیبانی از Redis/SQLite (همراه با TTL) و متد تک‌خطی `await ctx.ask()`.
- **پایدار در محیط واقعی:** محافظ ضدبلاک `AntiFloodAdapter`، پلاگین‌های Hot-Reload، زمان‌بند `@bot.every()` و تست آفلاین با `MockAdapter`.

## نصب

**نسخهٔ پایدار**

<div dir="ltr">

```bash
pip install shirdal
```

</div>

**نسخهٔ توسعه (Dev)**

<div dir="ltr">

```bash
pip install git+https://github.com/Vicious-Cycle/shirdal.git
```

</div>

**افزونه‌های اختیاری**

<div dir="ltr">

```bash
pip install "shirdal[fast]"       # uvloop + msgspec + shircrypt
pip install "shirdal[shircrypt]"  # شتاب‌دهنده Rust رمزنگاری
pip install "shirdal[redis]"      # ذخیره‌ساز Redis
pip install "shirdal[telethon]"   # آداپتر Telethon
```

</div>

## منابع

- [**مستندات کامل آنلاین**](https://vicious-cycle.github.io/shirdal/)
- [**دانلود یک‌جای مستندات (.md)**](https://vicious-cycle.github.io/shirdal/shirdal-docs.md)
- [**گزارش بنچمارک‌های shircrypt**](https://github.com/Vicious-Cycle/shircrypt)

</div>
