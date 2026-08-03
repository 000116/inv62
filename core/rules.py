import re

LLM_NEEDED = "__LLM_NEEDED__"

def fix_data_types(sql: str) -> str:
    sql = re.sub(r'\bVARCHAR2\b',    'VARCHAR',  sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNVARCHAR2\b',   'NVARCHAR', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNUMBER\b',      'NUMERIC',  sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bRAW\s*\(\d+\)', 'BYTEA',    sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bLONG\s+RAW\b',  'BYTEA',    sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bLONG\b',        'TEXT',     sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bCLOB\b',        'TEXT',     sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNCLOB\b',       'TEXT',     sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bBLOB\b',        'BYTEA',    sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bBFILE\b',       'TEXT',     sql, flags=re.IGNORECASE)
    return sql

def fix_null_functions(sql: str) -> str:
    sql = re.sub(r'\bNVL\s*\(', 'COALESCE(', sql, flags=re.IGNORECASE)
    def nvl2_replace(m):
        args = _split_args(m.group(1))
        if len(args) == 3:
            return (f"CASE WHEN {args[0].strip()} IS NOT NULL "
                    f"THEN {args[1].strip()} ELSE {args[2].strip()} END")
        return m.group(0)
    sql = re.sub(r'\bNVL2\s*\(([^)]+)\)', nvl2_replace, sql, flags=re.IGNORECASE)
    return sql

def fix_decode(sql: str) -> str:
    def decode_replace(m):
        args = _split_args(m.group(1))
        if len(args) < 3:
            return m.group(0)
        expr    = args[0].strip()
        pairs   = args[1:]
        clauses = []
        default = None
        i = 0
        while i < len(pairs):
            if i + 1 < len(pairs):
                clauses.append(f"WHEN {expr} = {pairs[i].strip()} THEN {pairs[i+1].strip()}")
                i += 2
            else:
                default = pairs[i].strip()
                i += 1
        result  = "CASE " + " ".join(clauses)
        result += f" ELSE {default}" if default else ""
        result += " END"
        return result
    sql = re.sub(
        r'\bDECODE\s*\((.+?)\)(?=\s*[,\s\)]|$)',
        decode_replace, sql, flags=re.IGNORECASE | re.DOTALL
    )
    return sql

def fix_date_functions(sql: str) -> str:
    
    sql = re.sub(
        r'\bSYSDATE\s*-\s*([0-9]+|:[a-zA-Z0-9_]+)', 
        r"CURRENT_TIMESTAMP - INTERVAL '\1 days'", 
        sql, flags=re.IGNORECASE
    )
    
    sql = re.sub(
        r'\bSYSDATE\s*\+\s*([0-9]+|:[a-zA-Z0-9_]+)', 
        r"CURRENT_TIMESTAMP + INTERVAL '\1 days'", 
        sql, flags=re.IGNORECASE
    )

    sql = re.sub(r'\bSYSDATE\b', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSYSTIMESTAMP\b', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)

    trunc_fmt = {
        'YYYY': 'year', 'YY': 'year', 'Q': 'quarter',
        'MM': 'month', 'MON': 'month', 'MONTH': 'month',
        'WW': 'week', 'W': 'week', 'IW': 'week',
        'DD': 'day', 'DDD': 'day', 'DAY': 'day',
        'HH': 'hour', 'HH12': 'hour', 'HH24': 'hour',
        'MI': 'minute', 'SS': 'second',
    }
    def trunc2(m):
        col = m.group(1).strip()
        fmt = m.group(2).strip().strip("'\"").upper()
        return f"DATE_TRUNC('{trunc_fmt.get(fmt, 'day')}', {col})"

    sql = re.sub(r"\bTRUNC\s*\(([^,]+),\s*'?(\w+)'?\)", trunc2, sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"\bTRUNC\s*\(([^,)]+)\)",
        lambda m: f"DATE_TRUNC('day', {m.group(1).strip()})",
        sql, flags=re.IGNORECASE
    )
    sql = re.sub(
        r"\bADD_MONTHS\s*\(([^,]+),\s*([^)]+)\)",
        lambda m: f"({m.group(1).strip()} + ({m.group(2).strip()} || ' months')::INTERVAL)",
        sql, flags=re.IGNORECASE
    )
    sql = re.sub(
        r"\bMONTHS_BETWEEN\s*\(([^,]+),\s*([^)]+)\)",
        lambda m: (
            f"(EXTRACT(YEAR FROM AGE({m.group(1).strip()}, {m.group(2).strip()}))*12"
            f" + EXTRACT(MONTH FROM AGE({m.group(1).strip()}, {m.group(2).strip()})))"
        ),
        sql, flags=re.IGNORECASE
    )
    sql = re.sub(
        r"\bLAST_DAY\s*\(([^)]+)\)",
        lambda m: f"(DATE_TRUNC('month', {m.group(1).strip()}) + INTERVAL '1 month' - INTERVAL '1 day')",
        sql, flags=re.IGNORECASE
    )
    if re.search(r'\bNEXT_DAY\b', sql, re.IGNORECASE):
        return LLM_NEEDED
    sql = re.sub(
        r"\bTO_NUMBER\s*\(([^)]+)\)",
        lambda m: f"CAST({m.group(1).strip()} AS NUMERIC)",
        sql, flags=re.IGNORECASE
    )
    return sql

def fix_string_functions(sql: str) -> str:
    sql = re.sub(r'\bSUBSTR\s*\(', 'SUBSTRING(', sql, flags=re.IGNORECASE)
    def instr_replace(m):
        args = _split_args(m.group(1))
        if len(args) == 2:
            return f"POSITION({args[1].strip()} IN {args[0].strip()})"
        return m.group(0)
    sql = re.sub(r'\bINSTR\s*\(([^)]+)\)', instr_replace, sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"\bREGEXP_LIKE\s*\(([^,]+),\s*([^)]+)\)",
        lambda m: f"{m.group(1).strip()} ~ {m.group(2).strip()}",
        sql, flags=re.IGNORECASE
    )
    sql = re.sub(
        r"\bREGEXP_SUBSTR\s*\(([^,]+),\s*([^)]+)\)",
        lambda m: f"(REGEXP_MATCH({m.group(1).strip()}, {m.group(2).strip()}))[1]",
        sql, flags=re.IGNORECASE
    )
    return sql

def fix_aggregate_functions(sql: str) -> str:
    def listagg_replace(m):
        col  = m.group(1).strip()
        sep  = m.group(2).strip() if m.group(2) else "''"
        ordr = m.group(3).strip() if m.group(3) else ""
        return f"STRING_AGG({col}, {sep} ORDER BY {ordr})" if ordr else f"STRING_AGG({col}, {sep})"
    sql = re.sub(
        r"\bLISTAGG\s*\(([^,]+),?\s*([^)]*)\)\s*WITHIN\s+GROUP\s*\(\s*ORDER\s+BY\s+([^)]+)\)",
        listagg_replace, sql, flags=re.IGNORECASE
    )
    sql = re.sub(
        r"\bWM_CONCAT\s*\(([^)]+)\)",
        lambda m: f"STRING_AGG({m.group(1).strip()}, ',')",
        sql, flags=re.IGNORECASE
    )
    return sql

def fix_rownum(sql: str) -> str:
    if not re.search(r'\bROWNUM\b', sql, re.IGNORECASE):
        return sql

    if re.search(r'\bROWNUM\s*(>|>=)\s*\d+', sql, re.IGNORECASE):
        return LLM_NEEDED

    m = re.search(r'\bROWNUM\s*(<=|<|=)\s*(\d+)\b', sql, re.IGNORECASE)
    if m:
        op      = m.group(1)
        n       = int(m.group(2))
        limit_n = n if op in ('<=', '=') else n - 1

        sql2 = re.sub(
            r'\bWHERE\s+ROWNUM\s*(?:<=|<|=)\s*\d+\b',
            '', sql, count=1, flags=re.IGNORECASE
        )
        if sql2 != sql:
            sql = sql2.strip()
        else:
            sql2 = re.sub(r'\s+AND\s+ROWNUM\s*(?:<=|<|=)\s*\d+\b', '', sql, count=1, flags=re.IGNORECASE)
            if sql2 != sql:
                sql = sql2.strip()
            else:
                sql = re.sub(
                    r'\bWHERE\s+ROWNUM\s*(?:<=|<|=)\s*\d+\s+AND\s+',
                    'WHERE ', sql, count=1, flags=re.IGNORECASE
                )

        sql = re.sub(
            r'\bWHERE\s*(\bORDER\b|\bGROUP\b|\bHAVING\b|\bLIMIT\b)',
            r'\1', sql, flags=re.IGNORECASE
        )
        sql = re.sub(r'\bWHERE\s*$', '', sql, flags=re.IGNORECASE).strip()

        m_ob = re.search(r'\bORDER\s+BY\b', sql, re.IGNORECASE)
        if m_ob:
            sql = sql[:m_ob.start()].rstrip() + f'\nLIMIT {limit_n}\n' + sql[m_ob.start():]
        else:
            sql = sql.rstrip().rstrip(';') + f'\nLIMIT {limit_n}'

    sql = re.sub(r'\bROWNUM\b', 'ROW_NUMBER() OVER()', sql, flags=re.IGNORECASE)
    return sql

def fix_dual(sql: str) -> str:
    return re.sub(r'\bFROM\s+DUAL\b', '', sql, flags=re.IGNORECASE)

def fix_oracle_outer_join(sql: str) -> str:
    if '(+)' not in sql:
        return sql
    if sql.count('(+)') > 1:
        return LLM_NEEDED
    m = re.search(
        r"FROM\s+(\w+)\s*,\s*(\w+)\s+WHERE\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)\s*\(\+\)",
        sql, re.IGNORECASE
    )
    if m:
        t1, t2, at1, c1, at2, c2 = m.groups()
        return re.sub(
            r"FROM\s+\w+\s*,\s*\w+\s+WHERE\s+\w+\.\w+\s*=\s*\w+\.\w+\s*\(\+\)",
            f"FROM {t1} LEFT JOIN {t2} ON {at1}.{c1} = {at2}.{c2}",
            sql, flags=re.IGNORECASE
        )
    return LLM_NEEDED

def fix_minus_operator(sql: str) -> str:
    return re.sub(r'\bMINUS\b', 'EXCEPT', sql, flags=re.IGNORECASE)

def fix_ddl(sql: str) -> str:
    sql = re.sub(r'(?i)EXISTS\s*\(\s*SELECT\s+NULL\b', 'EXISTS (SELECT 1', sql)
    sql = re.sub(r'\bCREATE\s+UNIQUE\s+BITMAP\s+INDEX\b', 'CREATE UNIQUE INDEX', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bCREATE\s+BITMAP\s+INDEX\b',          'CREATE INDEX',        sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNOCYCLE\b',              '',   sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNOCACHE\b',              '',   sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bCACHE\s+\d+\b',          '',   sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bORDER\b(?=\s*;|\s*$)',    '',   sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bTABLESPACE\s+\w+\b',     '',   sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSTORAGE\s*\([^)]*\)',     '',   sql, flags=re.IGNORECASE)
    sql = re.sub(r'\b(PCTFREE|PCTUSED|INITRANS|MAXTRANS|LOGGING|NOCOMPRESS)\s+\w*', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNOCOMPRESS\b|\bCOMPRESS\b', '', sql, flags=re.IGNORECASE)
    return sql

def fix_alter_table(sql: str) -> str:
    m = re.search(r"ALTER\s+TABLE\s+(\w+)\s+ADD\s*\((.+)\)", sql, flags=re.IGNORECASE | re.DOTALL)
    if m:
        table = m.group(1)
        stmts = []
        for col in m.group(2).split(','):
            col = re.sub(r'\bNUMBER\b',   'NUMERIC', col.strip(), flags=re.IGNORECASE)
            col = re.sub(r'\bVARCHAR2\b', 'VARCHAR', col,         flags=re.IGNORECASE)
            stmts.append(f"ALTER TABLE {table} ADD COLUMN {col}")
        return ";\n".join(stmts)

    m = re.search(r"ALTER\s+TABLE\s+(\w+)\s+MODIFY\s*\(\s*(\w+)\s+([^)]+)\)", sql, flags=re.IGNORECASE)
    if m:
        typedef = re.sub(r'\bNUMBER\b',   'NUMERIC', m.group(3).strip(), flags=re.IGNORECASE)
        typedef = re.sub(r'\bVARCHAR2\b', 'VARCHAR', typedef, flags=re.IGNORECASE)
        return f"ALTER TABLE {m.group(1)} ALTER COLUMN {m.group(2)} TYPE {typedef}"

    m = re.search(r"ALTER\s+TABLE\s+(\w+)\s+MODIFY\s+(\w+)\s+NOT\s+NULL", sql, flags=re.IGNORECASE)
    if m:
        return f"ALTER TABLE {m.group(1)} ALTER COLUMN {m.group(2)} SET NOT NULL"

    m = re.search(r"ALTER\s+TABLE\s+(\w+)\s+MODIFY\s+(\w+)\s+NULL\b", sql, flags=re.IGNORECASE)
    if m:
        return f"ALTER TABLE {m.group(1)} ALTER COLUMN {m.group(2)} DROP NOT NULL"

    if re.search(r'\b(DISABLE|ENABLE)\s+(NOVALIDATE\s+)?CONSTRAINT\b', sql, re.IGNORECASE):
        return LLM_NEEDED

    return sql

def fix_materialized_view(sql: str) -> str:
    return re.sub(
        r'\bREFRESH\s+(FAST|COMPLETE|FORCE|ON\s+(COMMIT|DEMAND)|NEVER)'
        r'(\s+(WITH\s+(PRIMARY\s+KEY|ROWID)))?',
        '', sql, flags=re.IGNORECASE
    )

def fix_hierarchical(sql: str) -> str:
    if not re.search(r'\bCONNECT\s+BY\b', sql, re.IGNORECASE):
        return sql

    sql = re.sub(r'\bCONNECT_BY_ROOT\s+(\w+)', r'\1', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSYS_CONNECT_BY_PATH\s*\(([^,]+),[^)]+\)', r'\1', sql, flags=re.IGNORECASE)

    select_m  = re.search(r'SELECT\s+(.*?)\s+FROM\s+(\w+)', sql, re.IGNORECASE | re.DOTALL)
    connect_m = re.search(
        r'CONNECT\s+BY\s+(.*?)(?=\s+START\s+WITH|\s+ORDER\s+BY|\s+GROUP\s+BY|\s+WHERE|$)',
        sql, re.IGNORECASE | re.DOTALL
    )
    start_m = re.search(
        r'START\s+WITH\s+(.*?)(?=\s+CONNECT\s+BY|\s+ORDER\s+BY|\s+GROUP\s+BY|$)',
        sql, re.IGNORECASE | re.DOTALL
    )

    if not (connect_m and select_m):
        return LLM_NEEDED

    raw_cols   = select_m.group(1).strip()
    table      = select_m.group(2).strip()
    cols       = re.sub(r'\bLEVEL\b', '1', raw_cols, flags=re.IGNORECASE)
    start_cond = start_m.group(1).strip() if start_m else "1=1"
    condition  = re.sub(r'\bPRIOR\b', '', connect_m.group(1).strip(), flags=re.IGNORECASE).strip()

    if '=' not in condition:
        return LLM_NEEDED

    left, right = [x.strip() for x in condition.split('=', 1)]
    return (
        f"WITH RECURSIVE hierarchy_cte AS (\n"
        f"    SELECT {cols}, 1 AS level\n"
        f"    FROM {table}\n"
        f"    WHERE {start_cond}\n"
        f"    UNION ALL\n"
        f"    SELECT {cols}, h.level + 1\n"
        f"    FROM {table} t\n"
        f"    JOIN hierarchy_cte h ON h.{left} = t.{right}\n"
        f")\nSELECT * FROM hierarchy_cte"
    )

def fix_flashback(sql: str) -> str:
    sql = re.sub(r'\bAS\s+OF\s+TIMESTAMP\s*\(?[^)]*\)?', '', sql, flags=re.IGNORECASE | re.DOTALL)
    sql = re.sub(r'\bVERSIONS\s+BETWEEN\s+.*?(?=WHERE|$)',  '', sql, flags=re.IGNORECASE | re.DOTALL)
    return sql

def check_unsupported(sql: str) -> str:
    s = sql.upper()

    if re.search(r'<(if|isSet|isNotNull|isNotEmpty|isNull|isEmpty|iterate|choose|when|otherwise|foreach)\b',
                 sql, re.IGNORECASE):
        return LLM_NEEDED

    if "CONNECT BY" in s or "START WITH" in s:
        return LLM_NEEDED

    if re.search(r'(?i)UNION\s+ALL\s+ORDER\s+BY', s):
        return LLM_NEEDED

    checks = [
        (r'\bPIVOT\b|\bUNPIVOT\b',                                    True),
        (r'\bMODEL\b.*\bRULES\b',                                     True),
        (r'\bDECLARE\b|\bBEGIN\b|\bEXCEPTION\b',                     True),
        (r'\bXMLELEMENT\b|\bXMLFOREST\b|\bXMLAGG\b|\bXMLTABLE\b',    True),
        (r'\bSYS_XMLAGG\b|\bJSON_TABLE\b',                            True),
        (r'\bDBMS_\w+',                                                True),
        (r'\bBULK\s+COLLECT\b|\bFORALL\b',                            True),
        (r'\bCURSOR\s*\(',                                             True),
        (r'\bMULTISET\b|\bMATCH_RECOGNIZE\b|\bSUBPARTITION\b',       True),
        (r'\bINSERT\s+ALL\b',                                         True),
        (r'\bORDER\s+SIBLINGS\s+BY\b',                                True),
        (r'\bPREDICTION\b|\bCLUSTER_\w+|\bFEATURE_\w+',              True),
        (r'\bFOR\s+UPDATE\s+WAIT\b|\bFOR\s+UPDATE\s+SKIP\s+LOCKED\b', True),
        (r'\bSAMPLE\s*\(',                                            True),
        (r'\bALTER\s+SESSION\b',                                      True),
        (r'\bTABLE\s*\(',                                             True),
    ]
    for pattern, _ in checks:
        if re.search(pattern, s, re.DOTALL):
            return LLM_NEEDED

    for kw in ['SYNONYM', 'DATABASE LINK', 'CREATE USER', 'ALTER USER', 'ALTER SYSTEM']:
        if kw in s:
            return LLM_NEEDED

    if '@' in sql:
        return LLM_NEEDED

    return sql

def _split_args(s: str) -> list:
    args, depth, cur = [], 0, []
    for ch in s:
        if ch == '(':
            depth += 1
            cur.append(ch)
        elif ch == ')':
            depth -= 1
            cur.append(ch)
        elif ch == ',' and depth == 0:
            args.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        args.append(''.join(cur))
    return args

def _clean(sql: str) -> str:
    sql = re.sub(r'\n{3,}', '\n\n', sql)
    sql = re.sub(r'[ \t]+', ' ', sql)
    return sql.strip()

def apply_all_rules(sql: str) -> str:
    steps = [
        check_unsupported,
        fix_data_types,
        fix_null_functions,
        fix_decode,
        fix_date_functions,
        fix_string_functions,
        fix_aggregate_functions,
        fix_rownum,
        fix_dual,
        fix_oracle_outer_join,
        fix_minus_operator,
        fix_ddl,
        fix_alter_table,
        fix_materialized_view,
        fix_hierarchical,
        fix_flashback,
    ]

    for step in steps:
        sql = step(sql)
        if sql == LLM_NEEDED:
            return LLM_NEEDED

    return _clean(sql)
