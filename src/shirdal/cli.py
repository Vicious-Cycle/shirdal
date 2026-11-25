from __future__ import annotations

import argparse
import importlib.util
import os
import runpy
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

_MAIN_TEMPLATE = """import os
from shirdal import SelfBot, SQLiteStorage{adapter_import}

{adapter_init}
bot = SelfBot(
    adapter,
    anti_flood=True,
    plugins_dir="plugins",
    hot_reload=True,
    storage=SQLiteStorage("shirdal.db"),
)

if __name__ == "__main__":
    bot.run()
"""

_PLUGIN_PING_TEMPLATE = """from shirdal import Context, SelfBot, command, outgoing


def setup(bot: SelfBot) -> None:
    @bot.on(command("ping", prefix=".") & outgoing)
    async def ping_cmd(ctx: Context) -> None:
        msg = await ctx.edit("⚡ Checking...")
        await msg.edit("🏓 Pong! Shirdal is alive.", auto_delete=10)
"""

_ENV_TEMPLATE = """API_ID=123456
API_HASH=your_api_hash_here
SESSION_NAME=my_account
"""


def _adapter_snippet(adapter: str) -> tuple[str, str]:
    if adapter == "telethon":
        return (
            ", TelethonAdapter",
            'adapter = TelethonAdapter(\n'
            '    os.getenv("SESSION_NAME", "my_account"),\n'
            '    int(os.getenv("API_ID", "0")),\n'
            '    os.getenv("API_HASH", ""),\n'
            ')',
        )
    if adapter == "hydrogram":
        return (
            ", HydrogramAdapter",
            'adapter = HydrogramAdapter(\n'
            '    os.getenv("SESSION_NAME", "my_account"),\n'
            '    int(os.getenv("API_ID", "0")),\n'
            '    os.getenv("API_HASH", ""),\n'
            ')',
        )
    return (", MockAdapter", "adapter = MockAdapter()")


def cmd_new(args: argparse.Namespace) -> int:
    target = Path(args.dir) / args.name
    if target.exists() and any(target.iterdir()):
        print(f"Error: directory '{target}' already exists and is not empty.", file=sys.stderr)
        return 1

    plugins_dir = target / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    adapter_import, adapter_init = _adapter_snippet(args.adapter)
    (target / "main.py").write_text(
        _MAIN_TEMPLATE.format(adapter_import=adapter_import, adapter_init=adapter_init),
        encoding="utf-8",
    )
    (plugins_dir / "ping.py").write_text(_PLUGIN_PING_TEMPLATE, encoding="utf-8")
    (target / ".env.example").write_text(_ENV_TEMPLATE, encoding="utf-8")
    print(f"Created shirdal project at {target}")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 11)
    print(f"Python: {py_ver} ({'OK' if py_ok else 'FAIL: requires >=3.11'})")
    print(f"SQLite: {sqlite3.sqlite_version} (OK)")

    optional = ("uvloop", "msgspec", "telethon", "hydrogram", "redis", "cryptography")
    for pkg in optional:
        found = importlib.util.find_spec(pkg) is not None
        print(f"  - {pkg}: {'installed' if found else 'not installed'}")
    return 0 if py_ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    script = Path(args.target)
    if not script.exists():
        print(f"Error: target '{script}' not found.", file=sys.stderr)
        return 1
    sys.path.insert(0, str(script.parent.resolve()))
    os.chdir(script.parent.resolve())
    runpy.run_path(str(script.name), run_name="__main__")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shirdal",
        description="Shirdal self-bot framework CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="Create a new shirdal self-bot project")
    p_new.add_argument("name", help="Project directory name")
    p_new.add_argument(
        "--adapter",
        choices=("telethon", "hydrogram", "mock"),
        default="telethon",
        help="Default MTProto adapter",
    )
    p_new.add_argument("--dir", default=".", help="Parent directory")
    p_new.set_defaults(func=cmd_new)

    p_doc = sub.add_parser("doctor", help="Check Python and optional dependencies")
    p_doc.set_defaults(func=cmd_doctor)

    p_run = sub.add_parser("run", help="Run a shirdal entry script")
    p_run.add_argument("target", nargs="?", default="main.py", help="Path to main.py")
    p_run.set_defaults(func=cmd_run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
