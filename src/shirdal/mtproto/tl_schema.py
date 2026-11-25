"""Minimal Telegram .tl schema parser and Python dataclass code generator."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field

_DECL_RE = re.compile(
    r"^(?P<name>[a-zA-Z_][a-zA-Z0-9_.]*)(?:#(?P<id>[0-9a-fA-F]+))?\s*(?P<args>.*?)\s*=\s*(?P<result>[^;]+);$"
)
_FLAG_TYPE_RE = re.compile(r"^(?P<flag_field>[a-zA-Z_][a-zA-Z0-9_]*)\.(?P<bit>\d+)\?(?P<inner>.+)$")
_VECTOR_RE = re.compile(r"^[Vv]ector<(?P<inner>.+)>$")

_PRIMITIVE_READERS = {
    "int": "r.read_int()",
    "long": "r.read_long()",
    "int128": "r.read_int128()",
    "int256": "r.read_int256()",
    "double": "r.read_double()",
    "bytes": "r.read_bytes()",
    "string": "r.read_string()",
    "Bool": "r.read_bool()",
}

_PRIMITIVE_WRITERS = {
    "int": "w.write_int({val})",
    "long": "w.write_long({val})",
    "int128": "w.write_int128({val})",
    "int256": "w.write_int256({val})",
    "double": "w.write_double({val})",
    "bytes": "w.write_bytes({val})",
    "string": "w.write_string({val})",
    "Bool": "w.write_bool({val})",
}

_PRIMITIVE_PY_TYPES = {
    "int": "int",
    "long": "int",
    "int128": "int",
    "int256": "int",
    "double": "float",
    "bytes": "bytes",
    "string": "str",
    "Bool": "bool",
    "true": "bool",
}


@dataclass(slots=True, frozen=True)
class TLParam:
    name: str
    type_name: str
    flag_field: str | None = None
    flag_bit: int | None = None
    is_vector: bool = False
    is_flag_holder: bool = False


@dataclass(slots=True, frozen=True)
class TLDefinition:
    name: str
    constructor_id: int
    params: tuple[TLParam, ...] = field(default_factory=tuple)
    result_type: str = ""
    is_function: bool = False


def _tl_class_name(tl_name: str) -> str:
    parts = re.split(r"[._]", tl_name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _compute_constructor_id(clean_line: str) -> int:
    normalized = clean_line.rstrip(";").strip()
    return zlib.crc32(normalized.encode("utf-8")) & 0xFFFFFFFF


def parse_tl_schema(schema_text: str) -> list[TLDefinition]:
    """Parse a Telegram .tl schema string into TLDefinition records."""
    definitions: list[TLDefinition] = []
    is_function = False

    for raw_line in schema_text.splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue
        if line == "---functions---":
            is_function = True
            continue
        if line == "---types---":
            is_function = False
            continue

        m = _DECL_RE.match(line)
        if not m:
            continue

        name = m.group("name")
        hex_id = m.group("id")
        cid = int(hex_id, 16) if hex_id else _compute_constructor_id(line)
        args_raw = m.group("args").strip()
        result_type = m.group("result").strip()

        params: list[TLParam] = []
        if args_raw:
            for token in args_raw.split():
                if token.startswith("{") and token.endswith("}"):
                    continue
                if ":" not in token:
                    continue
                p_name, p_type = token.split(":", 1)
                if p_type == "#":
                    params.append(TLParam(name=p_name, type_name="#", is_flag_holder=True))
                    continue

                flag_field: str | None = None
                flag_bit: int | None = None
                fm = _FLAG_TYPE_RE.match(p_type)
                if fm:
                    flag_field = fm.group("flag_field")
                    flag_bit = int(fm.group("bit"))
                    p_type = fm.group("inner")

                is_vector = False
                vm = _VECTOR_RE.match(p_type)
                if vm:
                    is_vector = True
                    p_type = vm.group("inner")

                params.append(
                    TLParam(
                        name=p_name,
                        type_name=p_type,
                        flag_field=flag_field,
                        flag_bit=flag_bit,
                        is_vector=is_vector,
                    )
                )

        definitions.append(
            TLDefinition(
                name=name,
                constructor_id=cid,
                params=tuple(params),
                result_type=result_type,
                is_function=is_function,
            )
        )

    return definitions


def generate_python_module(schema_text: str) -> str:
    """Generate a lightweight Python module with @dataclass(slots=True) TL types."""
    defs = parse_tl_schema(schema_text)
    lines: list[str] = [
        '"""Auto-generated Telegram TL schema types (Shirdal tlgen)."""',
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from typing import Any",
        "",
        "from shirdal.mtproto.tl_codec import TLDecodeError, TLReader, TLWriter",
        "",
        "",
        "class TLObject:",
        "    CONSTRUCTOR_ID = 0",
        "    QUALNAME = ''",
        "",
        "    def write_body(self, w: TLWriter) -> None:",
        "        raise NotImplementedError",
        "",
        "    def to_bytes(self) -> bytes:",
        "        w = TLWriter()",
        "        w.write_uint(self.CONSTRUCTOR_ID)",
        "        self.write_body(w)",
        "        return w.to_bytes()",
        "",
        "    @classmethod",
        "    def from_reader(cls, r: TLReader) -> TLObject:",
        "        raise NotImplementedError",
        "",
        "",
        "CONSTRUCTOR_REGISTRY: dict[int, type[TLObject]] = {}",
        "",
        "",
        "def read_object(r: TLReader) -> TLObject:",
        "    cid = r.read_uint()",
        "    cls = CONSTRUCTOR_REGISTRY.get(cid)",
        "    if cls is None:",
        "        raise TLDecodeError(f'Unknown TL constructor id: 0x{cid:08x}')",
        "    return cls.from_reader(r)",
        "",
    ]

    for d in defs:
        cls_name = _tl_class_name(d.name)
        data_params = [p for p in d.params if not p.is_flag_holder]
        flag_holders = [p.name for p in d.params if p.is_flag_holder]

        lines.append("@dataclass(slots=True)")
        lines.append(f"class {cls_name}(TLObject):")
        lines.append(f"    CONSTRUCTOR_ID = 0x{d.constructor_id:08x}")
        lines.append(f"    QUALNAME = {d.name!r}")

        # Required fields first, optional flag fields after
        req_fields = [p for p in data_params if p.flag_field is None]
        opt_fields = [p for p in data_params if p.flag_field is not None]

        for p in req_fields:
            base_py = _PRIMITIVE_PY_TYPES.get(p.type_name, "Any")
            py_t = f"list[{base_py}]" if p.is_vector else base_py
            lines.append(f"    {p.name}: {py_t}")

        for p in opt_fields:
            base_py = _PRIMITIVE_PY_TYPES.get(p.type_name, "Any")
            if p.type_name == "true":
                lines.append(f"    {p.name}: bool = False")
            elif p.is_vector:
                lines.append(f"    {p.name}: list[{base_py}] | None = None")
            else:
                lines.append(f"    {p.name}: {base_py} | None = None")

        # write_body
        lines.append("")
        lines.append("    def write_body(self, w: TLWriter) -> None:")
        if not d.params:
            lines.append("        return None")
        for fh in flag_holders:
            lines.append(f"        {fh} = 0")
            for p in opt_fields:
                if p.flag_field != fh:
                    continue
                if p.type_name == "true":
                    lines.append(f"        if self.{p.name}:")
                else:
                    lines.append(f"        if self.{p.name} is not None:")
                lines.append(f"            {fh} |= (1 << {p.flag_bit})")

        for p in d.params:
            if p.is_flag_holder:
                lines.append(f"        w.write_uint({p.name})")
                continue
            if p.type_name == "true":
                continue
            indent = "        "
            if p.flag_field is not None:
                lines.append(f"        if self.{p.name} is not None:")
                indent = "            "
            val_expr = f"self.{p.name}"
            if p.is_vector:
                item_w = _PRIMITIVE_WRITERS.get(p.type_name)
                if item_w:
                    expr = item_w.format(val="item")
                    lines.append(f"{indent}w.write_vector({val_expr}, lambda w, item: {expr})")
                else:
                    lines.append(f"{indent}w.write_vector({val_expr}, lambda w, item: w.write_raw(item.to_bytes()))")
            else:
                prim_w = _PRIMITIVE_WRITERS.get(p.type_name)
                if prim_w:
                    lines.append(f"{indent}{prim_w.format(val=val_expr)}")
                else:
                    lines.append(f"{indent}w.write_raw({val_expr}.to_bytes())")

        # from_reader
        lines.append("")
        lines.append("    @classmethod")
        lines.append(f"    def from_reader(cls, r: TLReader) -> {cls_name}:")
        for p in d.params:
            if p.is_flag_holder:
                lines.append(f"        {p.name} = r.read_uint()")
                continue
            if p.type_name == "true":
                lines.append(f"        {p.name} = bool({p.flag_field} & (1 << {p.flag_bit}))")
                continue

            if p.is_vector:
                item_r = _PRIMITIVE_READERS.get(p.type_name, "read_object(r)")
                read_expr = f"r.read_vector(lambda r: {item_r})"
            else:
                read_expr = _PRIMITIVE_READERS.get(p.type_name, "read_object(r)")

            if p.flag_field is not None:
                lines.append(
                    f"        {p.name} = {read_expr} if ({p.flag_field} & (1 << {p.flag_bit})) else None"
                )
            else:
                lines.append(f"        {p.name} = {read_expr}")

        ctor_args = ", ".join(f"{p.name}={p.name}" for p in data_params)
        lines.append(f"        return cls({ctor_args})")
        lines.append("")
        lines.append(f"CONSTRUCTOR_REGISTRY[{cls_name}.CONSTRUCTOR_ID] = {cls_name}")
        lines.append("")

    return "\n".join(lines)
