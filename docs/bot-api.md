# Bot API Features

`BotAPIAdapter` supports Telegram Bot API 9.4 through 10.5 features with concise Python helpers.

## Colored Buttons & Custom Emoji Icons

Use `button()` for inline keyboards and `reply_button()` for reply keyboards. Both accept `style` (`"primary"`, `"success"`, `"danger"` or `ButtonStyle`) and `icon` / `icon_custom_emoji_id`:

```python
from shirdal import ButtonStyle, button, inline_keyboard, reply_button, reply_keyboard

ikb = inline_keyboard(
    [
        [
            button("Approve", "ok", style=ButtonStyle.SUCCESS, icon="5368324170671202286"),
            button("Delete", "del", style="danger"),
        ],
        [
            button("Locked", "noop", style="primary", disabled=True),
            button("Copy Code", copy_text="SHIRDAL-101"),
        ],
    ],
    force_reply=True,
)

rkb = reply_keyboard(
    [
        [reply_button("Pay", style="primary", icon="51234567890"), "Help"],
        [reply_button("Share Contact", style="success", request_contact=True)],
    ],
    one_time_keyboard=True,
)
```

## Premium Custom Emoji & Localized Date/Time

```python
from shirdal import custom_emoji, custom_emoji_entity, date_time, date_time_entity

badge = custom_emoji("5368324170671202286", fallback="✨")
when = date_time(1764100000, "Tomorrow", format="r")
await ctx.reply(f"{badge} Scheduled for {when}")
```

For raw `entities` without `parse_mode`, use `custom_emoji_entity(offset, length, emoji_id)` and `date_time_entity(offset, length, unix_time, format=...)`.

## Ephemeral Group Replies

Send messages in groups that are only visible to the triggering user:

```python
await ctx.reply_ephemeral("Only you can see this response.")
```

On `BotAPIAdapter`, you can also manage ephemeral messages directly with `send_ephemeral_message()`, `edit_ephemeral_message()`, and `delete_ephemeral_message()`.

## Live Draft Streaming (`sendMessageDraft`)

Stream progressive text (such as LLM output) without hitting `editMessageText` rate limits:

```python
async with ctx.stream(can_stop=True, min_interval=0.25) as s:
    await s.write("Thinking... ")
    await s.write("Done.")
# Automatically finalizes with sendMessage on exit
```

## Member Tags, Private Topics & Bot Settings

```python
# Set a text tag on a group member (Bot API 9.5+)
await ctx.set_member_tag("VIP")

# Create a topic in a supergroup or private chat (Bot API 9.4+)
await adapter.create_forum_topic(chat_id, "Support", icon_custom_emoji_id="5368324170671202286")

# Update bot settings (Bot API 10.5+)
await adapter.set_my_settings(has_topic_sidebar=True, callback_query_mode="inline")
```
