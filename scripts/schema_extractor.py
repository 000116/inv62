import re
import json
import argparse
import sys
from pathlib import Path

def oracle_type_to_pg(oracle_type: str) -> str:
    t = oracle_type.strip().upper()

    m = re.match(r'NUMBER\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)', t)
    if m:
        p, s = m.group(1), m.group(2)
        if int(s) == 0:
            return f"NUMERIC({p})"
        return f"NUMERIC({p},{s})"

    m = re.match(r'NUMBER\s*\(\s*(\d+)\s*\)', t)
    if m:
        return f"NUMERIC({m.group(1)})"

    if t == 'NUMBER':
        return 'NUMERIC'

    m = re.match(r'(?:N)?VARCHAR2\s*\(\s*(\d+)\s*(?:BYTE|CHAR)?\s*\)', t)
    if m:
        return f"VARCHAR({m.group(1)})"

    m = re.match(r'CHAR\s*\(\s*(\d+)\s*(?:BYTE|CHAR)?\s*\)', t)
    if m:
        return f"CHAR({m.group(1)})"

    m = re.match(r'FLOAT\s*\(\s*(\d+)\s*\)', t)
    if m:
        return 'FLOAT8' if int(m.group(1)) > 23 else 'FLOAT4'

    m = re.match(r'TIMESTAMP\s*\(\s*(\d+)\s*\)', t)
    if m:
        return f"TIMESTAMP({m.group(1)})"

    if 'TIMESTAMP' in t and 'TIME ZONE' in t:
        return 'TIMESTAMPTZ'

    m = re.match(r'RAW\s*\(\s*\d+\s*\)', t)
    if m:
        return 'BYTEA'

    simple = {
        'DATE':           'TIMESTAMP',
        'TIMESTAMP':      'TIMESTAMP',
        'CLOB':           'TEXT',
        'NCLOB':          'TEXT',
        'BLOB':           'BYTEA',
        'LONG RAW':       'BYTEA',
        'BFILE':          'TEXT',
        'LONG':           'TEXT',
        'XMLTYPE':        'XML',
        'INTEGER':        'INTEGER',
        'INT':            'INTEGER',
        'SMALLINT':       'SMALLINT',
        'FLOAT':          'FLOAT8',
        'BINARY_FLOAT':   'FLOAT4',
        'BINARY_DOUBLE':  'FLOAT8',
        'VARCHAR':        'VARCHAR',
        'NVARCHAR':       'VARCHAR',
        'CHAR':           'CHAR',
        'NCHAR':          'CHAR',
        'BOOLEAN':        'BOOLEAN',
        'INTERVAL YEAR TO MONTH': 'INTERVAL',
        'INTERVAL DAY TO SECOND': 'INTERVAL',
    }
    for oracle, pg in simple.items():
        if t.startswith(oracle):
            return pg

    return oracle_type.strip()

def extract_from_oracle(dsn: str, schemas: list[str] | None = None) -> dict:
    try:
        import oracledb
    except ImportError:
        print("HATA: Oracle bağlantısı için → pip install oracledb")
        sys.exit(1)

    print(f"Oracle'a bağlanılıyor: {dsn.split('@')[-1]}...")
    conn = oracledb.connect(dsn)
    cur  = conn.cursor()

    schema_filter = ""
    params        = {}
    if schemas:
        placeholders  = ", ".join(f":s{i}" for i in range(len(schemas)))
        schema_filter = f"AND owner IN ({placeholders})"
        params        = {f"s{i}": s.upper() for i, s in enumerate(schemas)}

    col_query = f"""
        SELECT owner, table_name, column_name, column_id,
               data_type, data_length, data_precision, data_scale, nullable
        FROM   all_columns
        WHERE  1=1 {schema_filter}
        ORDER  BY owner, table_name, column_id
    """
    cur.execute(col_query, params)
    rows = cur.fetchall()
    print(f"  {len(rows)} sütun bulundu.")

    pk_query = f"""
        SELECT ac.owner, ac.table_name, acc.column_name
        FROM   all_constraints ac
        JOIN   all_cons_columns acc
               ON ac.owner = acc.owner
              AND ac.constraint_name = acc.constraint_name
        WHERE  ac.constraint_type = 'P'
        {schema_filter}
        ORDER  BY ac.owner, ac.table_name, acc.position
    """
    cur.execute(pk_query, params)
    pk_rows = cur.fetchall()

    cur.close()
    conn.close()

    pk_map: dict[tuple, list] = {}
    for owner, table, col in pk_rows:
        pk_map.setdefault((owner, table), []).append(col)

    schema: dict = {}
    for owner, table, col, pos, dtype, dlen, dprec, dscale, nullable in rows:
        if dprec is not None and dscale is not None:
            oracle_type = f"{dtype}({dprec},{dscale})"
        elif dprec is not None:
            oracle_type = f"{dtype}({dprec})"
        elif dtype in ('VARCHAR2', 'CHAR', 'NVARCHAR2', 'NCHAR', 'RAW') and dlen:
            oracle_type = f"{dtype}({dlen})"
        else:
            oracle_type = dtype

        pg_type = oracle_type_to_pg(oracle_type)

        schema.setdefault(owner, {}).setdefault(table, {"columns": {}, "pk": [], "source": "oracle_db"})
        schema[owner][table]["columns"][col] = {
            "oracle_type": oracle_type,
            "pg_type":     pg_type,
            "nullable":    (nullable == 'Y'),
            "position":    pos,
        }
        schema[owner][table]["pk"] = pk_map.get((owner, table), [])

    return schema

_COL_RE = re.compile(
    r'^\s*"?(?P<col>\w+)"?\s+'
    r'(?P<type>'
    r'(?:INTERVAL\s+\w+\s+TO\s+\w+)'
    r'|(?:TIMESTAMP(?:\s*\(\d+\))?(?:\s+WITH(?:\s+LOCAL)?\s+TIME\s+ZONE)?)'
    r'|(?:\w+(?:\s*\(\s*[\d,\s]+\s*\))?)'
    r')'
    r'(?:\s+(?P<rest>.*))?$',
    re.IGNORECASE
)

_TABLE_RE = re.compile(
    r'CREATE\s+(?:GLOBAL\s+TEMPORARY\s+)?TABLE\s+'
    r'(?:"?(?P<schema>\w+)"?\.)?"?(?P<table>\w+)"?\s*\(',
    re.IGNORECASE
)

_PK_INLINE_RE = re.compile(
    r'CONSTRAINT\s+\w+\s+PRIMARY\s+KEY\s*\(([^)]+)\)',
    re.IGNORECASE
)

_PK_COL_RE = re.compile(r'PRIMARY\s+KEY\b', re.IGNORECASE)

def parse_ddl_file(content: str, default_schema: str = "PUBLIC") -> dict:
    schema: dict = {}

    for table_m in _TABLE_RE.finditer(content):
        schema_name = (table_m.group("schema") or default_schema).upper()
        table_name  = table_m.group("table").upper()
        start       = table_m.end()

        depth   = 1
        pos     = start
        block   = []
        while pos < len(content) and depth > 0:
            ch = content[pos]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            if depth > 0:
                block.append(ch)
            pos += 1
        block_text = ''.join(block)

        columns: dict  = {}
        pk_cols: list  = []
        position       = 0

        pk_m = _PK_INLINE_RE.search(block_text)
        if pk_m:
            pk_cols = [c.strip().strip('"').upper() for c in pk_m.group(1).split(',')]

        for line in block_text.splitlines():
            line = line.strip().rstrip(',')
            if not line or line.startswith('--'):
                continue

            upper = line.upper()
            if re.match(r'\bCONSTRAINT\b|\bINDEX\b|\bCHECK\b|\bUNIQUE\b|\bFOREIGN\b', upper):
                continue

            if _PK_COL_RE.search(line):
                col_m = _COL_RE.match(line)
                if col_m:
                    pk_cols.append(col_m.group("col").upper())
                continue

            m = _COL_RE.match(line)
            if not m:
                continue

            col         = m.group("col").upper()
            oracle_type = m.group("type").strip()
            pg_type     = oracle_type_to_pg(oracle_type)
            rest        = (m.group("rest") or "").upper()
            nullable    = "NOT NULL" not in rest
            position   += 1

            columns[col] = {
                "oracle_type": oracle_type,
                "pg_type":     pg_type,
                "nullable":    nullable,
                "position":    position,
            }

        if columns:
            schema.setdefault(schema_name, {})[table_name] = {
                "columns": columns,
                "pk":      pk_cols,
                "source":  "ddl_file",
            }

    return schema

def extract_from_ddl(ddl_path: str, default_schema: str = "PUBLIC") -> dict:
    path   = Path(ddl_path)
    files  = list(path.rglob("*.sql")) + list(path.rglob("*.txt")) if path.is_dir() else [path]
    schema: dict = {}

    for f in files:
        print(f"  Parse ediliyor: {f.name}")
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  UYARI: {f.name} okunamadı — {e}")
            continue

        partial = parse_ddl_file(content, default_schema)
        for sch, tables in partial.items():
            schema.setdefault(sch, {}).update(tables)

    return schema

def main():
    ap = argparse.ArgumentParser(description="Oracle Schema Extractor → schema.json")
    ap.add_argument("--mode",           choices=["oracle", "ddl"], required=True)
    ap.add_argument("--dsn",            default="",  help="Oracle DSN: user/pass@host:1521/SID")
    ap.add_argument("--schemas",        default="",  help="Virgülle ayrılmış Oracle schema adları (boşsa hepsi)")
    ap.add_argument("--ddl-path",       default=".", help="DDL dosyası veya dizini")
    ap.add_argument("--default-schema", default="PUBLIC", help="DDL modunda varsayılan schema adı")
    ap.add_argument("--output",         default="schema.json")
    args = ap.parse_args()

    if args.mode == "oracle":
        schemas = [s.strip() for s in args.schemas.split(",") if s.strip()] or None
        data    = extract_from_oracle(args.dsn, schemas)
    else:
        data = extract_from_ddl(args.ddl_path, args.default_schema)

    total_tables  = sum(len(t) for t in data.values())
    total_columns = sum(
        len(tbl["columns"])
        for tables in data.values()
        for tbl in tables.values()
    )
    print(f"\n  {len(data)} schema, {total_tables} tablo, {total_columns} sütun bulundu.")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Schema kaydedildi → {args.output}")

if __name__ == "__main__":
    main()
