"""Schema-driven TL runtime: serialize / deserialize any Telegram API object at runtime.

The official Telegram API schema (``data/api.tl``) is parsed once, lazily, and every
constructor and method becomes available by name. Objects are plain ``TLObject`` dicts
with the constructor name stored under the ``"_"`` key, e.g.::

    {"_": "inputPeerUser", "user_id": 1, "access_hash": 2}

Flags (``flags:#``) are computed automatically from which optional fields are present,
so callers never touch bit masks.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from shirdal.mtproto.tl_codec import (
    BOOL_FALSE_ID,
    BOOL_TRUE_ID,
    GZIP_PACKED_ID,
    VECTOR_ID,
    TLDecodeError,
    TLReader,
    TLWriter,
    unpack_gzip,
)

SCHEMA_PATH = Path(__file__).with_name("data") / "api.tl"

_LINE_RE = re.compile(r"^([a-zA-Z0-9_.]+)#([0-9a-fA-F]+)\s*(.*?)=\s*([^;]+);\s*$")
_FLAG_RE = re.compile(r"^([a-zA-Z0-9_]+)\.(\d+)\?(.+)$")
_PRIMITIVES = {"int", "long", "double", "string", "bytes", "int128", "int256"}


class TLObject(dict):
    """A TL object: a dict whose ``"_"`` key is the constructor name."""

    @property
    def name(self) -> str:
        return str(self.get("_", ""))

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


@dataclass(slots=True, frozen=True)
class Param:
    name: str
    type: str
    flag_field: str | None = None
    flag_bit: int = 0


@dataclass(slots=True, frozen=True)
class Combinator:
    name: str
    id: int
    params: tuple[Param, ...]
    result: str
    is_function: bool


class Schema:
    def __init__(self, text: str) -> None:
        self.by_id: dict[int, Combinator] = {}
        self.ctors: dict[str, Combinator] = {}
        self.funcs: dict[str, Combinator] = {}
        self.ctors_by_type: dict[str, list[Combinator]] = {}
        self.layer = 0
        is_func = False
        for raw in text.splitlines():
            line = raw.strip()
            m_layer = re.match(r"^//\s*LAYER\s+(\d+)", line)
            if m_layer:
                self.layer = int(m_layer.group(1))
                continue
            if not line or line.startswith("//"):
                continue
            if line == "---functions---":
                is_func = True
                continue
            if line == "---types---":
                is_func = False
                continue
            if "[" in line:  # vector#1cb5c415 {t:Type} # [ t ] = Vector t;
                continue
            m = _LINE_RE.match(line)
            if m is None:
                continue
            name, cid, args, result = m.group(1), int(m.group(2), 16), m.group(3), m.group(4).strip()
            params: list[Param] = []
            for tok in args.split():
                if tok.startswith("{"):
                    continue
                pname, _, ptype = tok.partition(":")
                fm = _FLAG_RE.match(ptype)
                if fm:
                    params.append(Param(pname, fm.group(3), fm.group(1), int(fm.group(2))))
                else:
                    params.append(Param(pname, ptype))
            comb = Combinator(name, cid, tuple(params), result, is_func)
            if is_func:
                self.funcs[name] = comb
            else:
                self.ctors[name] = comb
                self.ctors_by_type.setdefault(result, []).append(comb)
            self.by_id.setdefault(cid, comb)

    # ------------------------------------------------------------------ write
    def serialize(self, name: str, params: dict[str, Any] | None = None) -> bytes:
        """Serialize a method call or constructor by name."""
        comb = self.funcs.get(name) or self.ctors.get(name)
        if comb is None:
            raise TLDecodeError(f"Unknown TL combinator: {name}")
        w = TLWriter()
        self._write_combinator(w, comb, params or {})
        return w.to_bytes()

    def _write_combinator(self, w: TLWriter, comb: Combinator, values: dict[str, Any]) -> None:
        w.write_uint(comb.id)
        self._write_fields(w, comb, values)

    def _write_fields(self, w: TLWriter, comb: Combinator, values: dict[str, Any]) -> None:
        flag_values: dict[str, int] = {}
        for p in comb.params:
            if p.flag_field is None:
                continue
            v = values.get(p.name)
            present = bool(v) if p.type == "true" else v is not None
            if present:
                flag_values[p.flag_field] = flag_values.get(p.flag_field, 0) | (1 << p.flag_bit)
        for p in comb.params:
            if p.type == "#":
                w.write_uint(flag_values.get(p.name, 0))
                continue
            v = values.get(p.name)
            if p.flag_field is not None:
                if p.type == "true" or v is None:
                    continue
            elif v is None:
                if p.name == "random_id" and p.type == "long":
                    v = random_long()
                elif p.type == "true":
                    continue
                else:
                    raise TLDecodeError(f"{comb.name}: missing required field '{p.name}'")
            self._write_value(w, p.type, v)

    def _write_value(self, w: TLWriter, tl_type: str, v: Any) -> None:
        if tl_type == "int":
            w.write_int(int(v))
        elif tl_type == "long":
            w.write_long(int(v))
        elif tl_type == "double":
            w.write_double(float(v))
        elif tl_type == "string":
            w.write_bytes(v if isinstance(v, (bytes, bytearray)) else str(v).encode("utf-8"))
        elif tl_type == "bytes":
            w.write_bytes(bytes(v) if not isinstance(v, str) else v.encode("utf-8"))
        elif tl_type == "int128":
            w.write_int128(v)
        elif tl_type == "int256":
            w.write_int256(v)
        elif tl_type == "Bool":
            w.write_uint(BOOL_TRUE_ID if v else BOOL_FALSE_ID)
        elif tl_type in ("!X", "X"):
            if isinstance(v, (bytes, bytearray)):
                w.write_raw(bytes(v))
            else:
                self._write_object(w, v)
        elif tl_type.startswith(("Vector<", "vector<")):
            inner = tl_type[7:-1]
            if tl_type[0] == "V":
                w.write_uint(VECTOR_ID)
            items = list(v)
            w.write_int(len(items))
            for item in items:
                self._write_value(w, inner, item)
        elif tl_type.startswith("%"):
            cands = self.ctors_by_type.get(tl_type[1:]) or []
            if len(cands) != 1:
                raise TLDecodeError(f"Cannot write bare type {tl_type}")
            self._write_fields(w, cands[0], v)
        else:
            if isinstance(v, (bytes, bytearray)):
                w.write_raw(bytes(v))
            else:
                self._write_object(w, v)

    def _write_object(self, w: TLWriter, v: Any) -> None:
        if not isinstance(v, dict) or "_" not in v:
            raise TLDecodeError(f"Expected TL object dict with '_' key, got {v!r}")
        comb = self.ctors.get(v["_"]) or self.funcs.get(v["_"])
        if comb is None:
            raise TLDecodeError(f"Unknown TL constructor: {v['_']}")
        self._write_combinator(w, comb, v)

    # ------------------------------------------------------------------- read
    def deserialize(self, data: bytes, tl_type: str | None = None) -> Any:
        r = TLReader(data)
        return self.read_value(r, tl_type or "Object")

    def read_value(self, r: TLReader, tl_type: str) -> Any:
        if tl_type == "int":
            return r.read_int()
        if tl_type == "long":
            return r.read_long()
        if tl_type == "double":
            return r.read_double()
        if tl_type == "string":
            raw = r.read_bytes()
            return raw.decode("utf-8", errors="replace")
        if tl_type == "bytes":
            return r.read_bytes()
        if tl_type == "int128":
            return r.read_int128_bytes()
        if tl_type == "int256":
            return r.read_int256_bytes()
        if tl_type == "Bool":
            cid = r.read_uint()
            if cid == BOOL_TRUE_ID:
                return True
            if cid == BOOL_FALSE_ID:
                return False
            raise TLDecodeError(f"Expected Bool, got 0x{cid:08x}")
        if tl_type.startswith("Vector<") or tl_type.startswith("vector<"):
            inner = tl_type[7:-1]
            if tl_type[0] == "V":
                cid = r.read_uint()
                if cid == GZIP_PACKED_ID:
                    return self.read_value(TLReader(_gunzip_rest(r)), tl_type)
                if cid != VECTOR_ID:
                    raise TLDecodeError(f"Expected vector, got 0x{cid:08x}")
            n = r.read_int()
            return [self.read_value(r, inner) for _ in range(n)]
        if tl_type.startswith("%"):
            cands = self.ctors_by_type.get(tl_type[1:]) or []
            if len(cands) != 1:
                raise TLDecodeError(f"Cannot read bare type {tl_type}")
            return self._read_fields(r, cands[0])
        return self.read_object(r)

    def read_object(self, r: TLReader) -> Any:
        cid = r.read_uint()
        if cid == GZIP_PACKED_ID:
            return self.read_object(TLReader(_gunzip_rest(r)))
        if cid == BOOL_TRUE_ID:
            return True
        if cid == BOOL_FALSE_ID:
            return False
        if cid == VECTOR_ID:
            n = r.read_int()
            # Element type unknown: try objects, fall back to longs.
            start = r.pos
            try:
                return [self.read_object(r) for _ in range(n)]
            except TLDecodeError:
                r._pos = start
                return [r.read_long() for _ in range(n)]
        comb = self.by_id.get(cid)
        if comb is None:
            raise TLDecodeError(f"Unknown constructor id 0x{cid:08x}")
        return self._read_fields(r, comb)

    def _read_fields(self, r: TLReader, comb: Combinator) -> TLObject:
        obj = TLObject(_=comb.name)
        flags: dict[str, int] = {}
        for p in comb.params:
            if p.type == "#":
                flags[p.name] = r.read_uint()
                continue
            if p.flag_field is not None:
                if not flags.get(p.flag_field, 0) & (1 << p.flag_bit):
                    if p.type == "true":
                        obj[p.name] = False
                    continue
                if p.type == "true":
                    obj[p.name] = True
                    continue
            elif p.type == "true":
                obj[p.name] = True
                continue
            obj[p.name] = self.read_value(r, p.type)
        return obj

    def return_type(self, method: str) -> str | None:
        f = self.funcs.get(method)
        return f.result if f else None


def _gunzip_rest(r: TLReader) -> bytes:
    return unpack_gzip(r, expect_header=False)


def random_long() -> int:
    return struct.unpack("<q", os.urandom(8))[0]


@lru_cache(maxsize=1)
def get_schema() -> Schema:
    return Schema(SCHEMA_PATH.read_text(encoding="utf-8"))


def serialize(name: str, **params: Any) -> bytes:
    return get_schema().serialize(name, params)


def deserialize(data: bytes, tl_type: str | None = None) -> Any:
    return get_schema().deserialize(data, tl_type)


def api_layer() -> int:
    return get_schema().layer


__all__ = [
    "SCHEMA_PATH",
    "Schema",
    "TLObject",
    "api_layer",
    "deserialize",
    "get_schema",
    "random_long",
    "serialize",
]
