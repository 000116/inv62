def split_sql(sql: str):
    if not sql or not sql.strip():
        return []

    statements = []
    current_stmt = []
    
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    paren_depth = 0
    
    i = 0
    length = len(sql)
    
    while i < length:
        char = sql[i]
        next_char = sql[i+1] if i + 1 < length else ''
        
        if not (in_single_quote or in_double_quote):
            if not in_block_comment and char == '-' and next_char == '-':
                in_line_comment = True
                current_stmt.append(char)
                current_stmt.append(next_char)
                i += 2
                continue
            if in_line_comment and char == '\n':
                in_line_comment = False
            
            if not in_line_comment and char == '/' and next_char == '*':
                in_block_comment = True
                current_stmt.append(char)
                current_stmt.append(next_char)
                i += 2
                continue
            if in_block_comment and char == '*' and next_char == '/':
                in_block_comment = False
                current_stmt.append(char)
                current_stmt.append(next_char)
                i += 2
                continue

        if in_line_comment or in_block_comment:
            current_stmt.append(char)
            i += 1
            continue

        if char == "'":
            in_single_quote = not in_single_quote
        elif char == '"':
            in_double_quote = not in_double_quote

        if not (in_single_quote or in_double_quote):
            if char == '(':
                paren_depth += 1
            elif char == ')':
                paren_depth = max(0, paren_depth - 1)
            
            if char == ';' and paren_depth == 0:
                stmt = ''.join(current_stmt).strip()
                if stmt:
                    statements.append(stmt)
                current_stmt = []
                i += 1
                continue
            
            if char == '/' and paren_depth == 0:
                prev_newline = False
                if not current_stmt or current_stmt[-1] == '\n':
                    stmt = ''.join(current_stmt).strip()
                    if stmt:
                        statements.append(stmt)
                    current_stmt = []
                    i += 1
                    continue

        current_stmt.append(char)
        i += 1

    last_stmt = ''.join(current_stmt).strip()
    if last_stmt:
        statements.append(last_stmt)

    return statements