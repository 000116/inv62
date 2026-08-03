import re
from .local_prompts import get_rag_prompt
from .rules import apply_all_rules

def _extract_first_statement(text: str) -> str:
    text = re.sub(r"```[sS][qQ][lL]?", "", text)
    text = text.replace("```", "")

    match = re.search(r'\b(WITH|SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|MERGE)\b', text, re.IGNORECASE)
    if match:
        text = text[match.start():]

    lines = text.splitlines()
    sql_lines = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^(note|alternative|option|variant|explanation|original|before|after|output|here is)\b', stripped, re.IGNORECASE):
            break
        if re.match(r'^\d+[\.\)]\s+', stripped):
            break
        sql_lines.append(line)

    text = "\n".join(sql_lines).strip()

    depth = 0
    in_sq = False
    for idx, ch in enumerate(text):
        if ch == "'" and not in_sq:
            in_sq = True
        elif ch == "'" and in_sq:
            in_sq = False
        elif not in_sq:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth = max(0, depth - 1)
            elif ch == ';' and depth == 0:
                text = text[:idx + 1]  
                break

    return text.strip()

def translate(sql_section: str, llm):
    messages = []
    source_used = "llm"

    rule_based_sql = apply_all_rules(sql_section)
    prompt_target = sql_section if rule_based_sql == "__LLM_NEEDED__" else rule_based_sql  
    prompt = get_rag_prompt(prompt_target)

    try:
        response = llm.invoke(prompt)
        raw = response.content.strip()
        translated_sql = _extract_first_statement(raw)

        if not translated_sql:
            translated_sql = rule_based_sql if rule_based_sql != "__LLM_NEEDED__" else sql_section
            source_used = "rules (fallback from empty llm)"

    except Exception as e:
        messages.append(f"[ERROR] LLM call failed: {str(e)}")
        translated_sql = rule_based_sql if rule_based_sql != "__LLM_NEEDED__" else sql_section
        source_used = "rules (error fallback)"

    return translated_sql, source_used, messages