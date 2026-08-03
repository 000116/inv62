def get_rag_prompt(sql_query: str) -> str:
    prompt = f"""You are a STRICT and ROBOTIC Oracle-to-PostgreSQL syntax translator. 

CRITICAL RULES (VIOLATION WILL CAUSE SYSTEM FAILURE):
1. NO HALLUCINATIONS: DO NOT invent, assume, or add tables, schemas, or JOINs that are not explicitly present in the Oracle SQL. 
2. EXCEPTION FOR STRUCTURAL REWRITES: For highly proprietary Oracle features like MODEL, PIVOT, or UNPIVOT, you MUST restructure the query using standard PostgreSQL features (CTEs, WITH RECURSIVE, Window Functions like LAG/LEAD, or FILTER clauses) to achieve the exact same analytical logic.
3. DECODE RULE: Translate DECODE() into a standard CASE WHEN ... THEN ... END block.
4. NO PARAMETERIZING STRINGS: Hardcoded strings MUST remain hardcoded strings. ONLY change explicitly defined Oracle bind parameters (like :param_name) to $1, $2.
5. ROWNUM RULE: If ROWNUM is used in the SELECT list, translate as ROW_NUMBER() OVER (). If used in a WHERE clause for limiting, use LIMIT.
6. MERGE INTO RULE: When translating MERGE INTO to PostgreSQL's INSERT ... ON CONFLICT, you MUST:
   - NOT use table aliases for the target table in the INSERT INTO clause (e.g., write INSERT INTO emp, NOT INSERT INTO emp e).
   - ALWAYS use the special 'EXCLUDED' keyword in the DO UPDATE SET clause to refer to the new source values (e.g., SET salary = EXCLUDED.salary).
7. FORMAT: Output ONLY the valid PostgreSQL statement. End with a semicolon.
8. STRICT 1:1 TRANSLATION: DO NOT invent, assume, or add ANYTHING that is not explicitly in the input.
   - NEVER add table aliases (like 'e', 'd', 't') if they are not in the original SQL.
   - NEVER add a 'LIMIT' clause unless 'ROWNUM' explicitly exists in the original SQL.
   - NEVER change hardcoded strings into parameters ($1).
9. FORMATTING & READABILITY: You MUST preserve original newlines, indentation, and formatting. DO NOT output the SQL as a single compressed line. Output must be pretty-printed and highly readable.

TRANSLATION DICTIONARY:
- Oracle NVL(a, b) -> PostgreSQL COALESCE(a, b)
- Oracle SYSDATE -> PostgreSQL CURRENT_TIMESTAMP
- Oracle LISTAGG(col, 'sep') WITHIN GROUP (ORDER BY sort_col) -> PostgreSQL STRING_AGG(col, 'sep' ORDER BY sort_col)
- Oracle MERGE INTO -> Translate to PostgreSQL INSERT INTO ... ON CONFLICT (...) DO UPDATE SET ... (or valid PostgreSQL 15 MERGE statement)
- Oracle MODEL -> Restructure entirely using CTEs and Window Functions (e.g., LAG/LEAD/SUM OVER)
- Oracle TRUNC(date_col, 'MM') -> PostgreSQL DATE_TRUNC('month', date_col)
- Oracle WHERE ROWNUM <= N -> PostgreSQL LIMIT N (appended at the end of the query)

ORACLE SQL:
{sql_query}

POSTGRESQL SQL:"""

    return prompt