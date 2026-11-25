# Rich Messages

Shirdal supports Telegram Bot API 10.1–10.5 **Rich Messages** (`sendRichMessage` and `sendRichMessageDraft`) via `ctx.reply_rich()`, `ctx.stream_rich()`, and `rich_message()`.

## Sending Rich HTML or Markdown

Pass `html`, `markdown`, or `blocks` (exactly one) with optional `is_rtl=True`:

```python
await ctx.reply_rich(
    html="<h1>Daily Report</h1><p>All checks passed.</p>",
    is_rtl=False,
)
```

```python
await ctx.reply_rich(
    markdown="# Summary\n\n- **Status:** Healthy\n- **Errors:** 0",
)
```

## Structured Block Builders

Build `blocks` with typed helper functions instead of raw nested dictionaries:

```python
from shirdal import (
    button,
    rich_blockquote,
    rich_buttons,
    rich_code,
    rich_details,
    rich_divider,
    rich_footer,
    rich_heading,
    rich_math,
    rich_paragraph,
    rich_table,
)

blocks = [
    rich_heading("Sales Report", size=1),
    rich_paragraph("Overview for today:"),
    rich_table(
        [["Plan A", "120"], ["Plan B", "85"]],
        headers=["Item", "Count"],
        caption="Daily Totals",
    ),
    rich_details(
        "Diagnostics",
        [rich_code("print('ok')", language="python"), rich_math("E = mc^2")],
        is_open=True,
    ),
    rich_blockquote("Verified by pipeline", credit="CI", expandable=True),
    rich_divider(),
    rich_buttons([button("Approve", "ok", style="success")], align="center"),
    rich_footer("Shirdal Analytics"),
]

await ctx.reply_rich(blocks=blocks)
```

## Streaming Rich Messages (`sendRichMessageDraft`)

Use `ctx.stream_rich()` to show a thinking indicator (`rich_thinking`) and stream partial HTML, Markdown, or blocks before finalizing:

```python
async with ctx.stream_rich(is_rtl=True, can_stop=True) as stream:
    await stream.thinking("Analyzing...")
    await stream.write("<h1>Result</h1>")
    await stream.write("<p>Completed successfully.</p>")
```

You can also edit an existing message with a Rich Message:

```python
from shirdal import rich_message

await adapter.edit_message(chat_id, message_id, rich_message(html="<p>Updated</p>"))
```
