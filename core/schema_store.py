import re
import json
from pathlib import Path

_NUMERIC_TYPES = {
    'NUMERIC', 'INTEGER', 'BIGINT', 'SMALLINT', 'FLOAT4', 'FLOAT8',
    'FLOAT', 'DOUBLE PRECISION', 'REAL', 'SERIAL', 'BIGSERIAL',
}
_TEXT_TYPES = {
    'TEXT', 'VARCHAR', 'CHAR', 'CHARACTER VARYING', 'CHARACTER',
}
_DATE_TYPES = {
    'DATE', 'TIMESTAMP', 'TIMESTAMPTZ', 'TIME', 'TIMETZ', 'INTERVAL',
}

def _pg_type_family(pg_type: str) -> str:
    base = re.sub(r'\(.*\)', '', pg_type).strip().upper()
    if any(base.startswith(t) for t in _NUMERIC_TYPES):
        return 'numeric'
    if any(base.startswith(t) for t in _TEXT_TYPES):
        return 'text'
    if any(base.startswith(t) for t in _DATE_TYPES):
        return 'date'
    if base in ('BYTEA', 'BIT', 'VARBIT'):
        return 'binary'
    return 'other'

class SchemaStore:

    NO_SCHEMA_MSG = (
        "No schema provided. Apply conservative type casting where ambiguity is obvious.\n"
        "Cast string parameters to NUMERIC where columns are likely numeric.\n"
        "Cast numeric parameters to VARCHAR where columns are likely text (CHAR/VARCHAR)."
    )

    def __init__(self, schema_path: str | None = None):
        self._data: dict = {}
        self._flat: dict = {}
        self._loaded = False

        if schema_path and Path(schema_path).exists():
            self._load(schema_path)

    def _load(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            self._data = json.load(f)

        for schema_name, tables in self._data.items():
            for table_name, table_def in tables.items():
                self._flat.setdefault(table_name.upper(), []).append({
                    "schema": schema_name,
                    "table":  table_name,
                    **table_def,
                })
        self._loaded = True
        total = sum(len(t) for t in self._data.values())
        print(f"  SchemaStore: {total} tablo yüklendi ({path})")

    def get_table(self, table_name: str, schema_name: str | None = None) -> dict | None:
        entries = self._flat.get(table_name.upper(), [])
        if not entries:
            return None
        if schema_name:
            for e in entries:
                if e["schema"].upper() == schema_name.upper():
                    return e
        return entries[0]

    def get_column_pg_type(self, table_name: str, column_name: str,
                            schema_name: str | None = None) -> str | None:
        tbl = self.get_table(table_name, schema_name)
        if not tbl:
            return None
        col = tbl["columns"].get(column_name.upper())
        return col["pg_type"] if col else None

    @staticmethod
    def extract_tables_from_sql(sql: str) -> list[str]:
        clean = re.sub(r'--[^\n]*', '', sql)
        clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)

        found = set()

        from_re = re.compile(
            r'\bFROM\s+(?!\()'
            r'(?:(?P<schema>\w+)\.)?(?P<table>\w+)'
            r'(?:\s+(?:AS\s+)?(?P<alias>\w+))?',
            re.IGNORECASE
        )
        for m in from_re.finditer(clean):
            tbl = m.group('table').upper()
            if tbl not in ('SELECT', 'WHERE', 'SET', 'VALUES', 'DUAL'):
                found.add(tbl)

        join_re = re.compile(
            r'\bJOIN\s+(?!\()'
            r'(?:(?P<schema>\w+)\.)?(?P<table>\w+)',
            re.IGNORECASE
        )
        for m in join_re.finditer(clean):
            tbl = m.group('table').upper()
            found.add(tbl)

        return list(found)

    def context_for_query(self, sql: str, max_columns: int = 60) -> str:
        if not self._loaded:
            return self.NO_SCHEMA_MSG

        tables = self.extract_tables_from_sql(sql)
        if not tables:
            return self.NO_SCHEMA_MSG

        lines   = []
        col_cnt = 0

        for tbl_name in sorted(tables):
            tbl_def = self.get_table(tbl_name)
            if not tbl_def:
                continue

            lines.append(f"TABLE {tbl_def['schema']}.{tbl_name}:")
            pk_set = {p.upper() for p in tbl_def.get("pk", [])}

            for col_name, col_info in tbl_def["columns"].items():
                if col_cnt >= max_columns:
                    lines.append("  ... (truncated)")
                    break
                oracle_t = col_info.get("oracle_type", "UNKNOWN")
                pg_t = col_info.get("pg_type", "UNKNOWN")
                nullable = "" if col_info.get("nullable", True) else " NOT NULL"
                pk_mark  = " [PK]" if col_name in pk_set else ""
                risk     = self._type_risk_note(oracle_t, pg_t)
                lines.append(f"  {col_name}: {oracle_t} → {pg_t}{nullable}{pk_mark}{risk}")
                col_cnt += 1

            lines.append("")

        if not lines:
            return f"Schema loaded but tables not found: {', '.join(tables)}. Apply conservative casting."

        lines.append("CASTING RULES (apply based on column types above):")
        lines.append("  - CHAR/VARCHAR col compared to numeric param → CAST(:param AS VARCHAR) or col::NUMERIC")
        lines.append("  - DATE col compared to string param           → :param::DATE or TO_DATE(:param,'YYYY-MM-DD')")
        lines.append("  - NUMERIC col compared to string param        → :param::NUMERIC")
        lines.append("  - IN (:list) for numeric col                  → col = ANY(:list::NUMERIC[])")
        lines.append("  - IN (:list) for varchar col                  → col = ANY(:list::VARCHAR[])")

        return "\n".join(lines)

    def _type_risk_note(self, oracle_type: str, pg_type: str) -> str:
        o = oracle_type.upper()
        p = pg_type.upper()
        if o.startswith('CHAR') and not o.startswith('CHARACTER'):
            return " ⚠ CHAR — string/numeric karşılaştırmasında CAST gerekebilir"
        if o.startswith('DATE') and 'TIMESTAMP' in p:
            return " ℹ Oracle DATE → PG TIMESTAMP (zaman bileşeni içerebilir)"
        return ""

    def cast_hints_for_query(self, sql: str) -> dict[str, dict]:
        if not self._loaded:
            return {}

        hints = {}
        for tbl_name in self.extract_tables_from_sql(sql):
            tbl_def = self.get_table(tbl_name)
            if not tbl_def:
                continue
            for col_name, col_info in tbl_def["columns"].items():
                pg_t   = col_info["pg_type"]
                family = _pg_type_family(pg_t)
                key    = f"{tbl_name}.{col_name}"
                hints[key] = {
                    "pg_type":    pg_t,
                    "pg_family":  family,
                    "cast_param": _suggest_param_cast(family, pg_t),
                    "cast_col":   _suggest_col_cast(family, pg_t),
                }
        return hints

    def stats(self) -> str:
        total_t = sum(len(t) for t in self._data.values())
        total_c = sum(
            len(tbl["columns"])
            for tables in self._data.values()
            for tbl in tables.values()
        )
        return f"{len(self._data)} schema, {total_t} tablo, {total_c} sütun"

def _suggest_param_cast(family: str, pg_type: str) -> str:
    base = re.sub(r'\(.*\)', '', pg_type).strip().upper()
    if family == 'numeric':
        return f"::{base}" if base in ('INTEGER', 'BIGINT', 'SMALLINT') else "::NUMERIC"
    if family == 'date':
        return "::TIMESTAMP" if 'TIMESTAMP' in base else "::DATE"
    if family == 'text':
        return "::VARCHAR"
    return ""

def _suggest_col_cast(family: str, pg_type: str) -> str:
    base = re.sub(r'\(.*\)', '', pg_type).strip().upper()
    if family == 'numeric':
        return f"::{base}" if base in ('INTEGER', 'BIGINT', 'SMALLINT') else "::NUMERIC"
    if family == 'date':
        return "::TIMESTAMP" if 'TIMESTAMP' in base else "::DATE"
    return ""
