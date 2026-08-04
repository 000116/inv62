from __future__ import annotations

import os
import re
import json
import time
import pickle
import importlib

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import AzureOpenAI
    from azure.identity import AzureCliCredential
except ImportError:
    AzureOpenAI = None
    AzureCliCredential = None

try:
    from pglast import parser as pg_parser
    from pglast.parser import ParseError
    PGLAST_OK = True
except ImportError:
    PGLAST_OK = False

try:
    import pandas as pd
    PANDAS_OK = True
except ImportError:
    PANDAS_OK = False

try:
    from .rules import apply_all_rules, LLM_NEEDED
except ImportError:
    raise RuntimeError("rules.py bulunamadı.")

try:
    from .prompts import SystemPrompts
except ImportError:
    raise RuntimeError("prompts.py bulunamadı.")

try:
    from .schema_store import SchemaStore
except ImportError:
    raise RuntimeError("schema_store.py bulunamadı.")

AZURE_ENDPOINT   = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_API_VER    = "2025-01-01-preview"
DEPLOYMENT_MODEL = os.environ.get("AZURE_DEPLOYMENT_NAME")

ML_MODEL_PATH = "smart_router_model_v5.pkl"
DEFAULT_SCHEMA = os.environ.get("SCHEMA_PATH", "schema.json")

PRICE_INPUT  = 0.15
PRICE_OUTPUT = 0.60

RULE_P = [
    r'\bNVL\s*\(', r'\bSYSDATE\b', r'\bROWNUM\b', r'\bDECODE\s*\(',
    r'\bVARCHAR2\b', r'\bFROM\s+DUAL\b', r':[a-zA-Z_]\w*'
]
SQLCODER_P = [
    r'\bROW_NUMBER\s*\(\)', r'\bRANK\s*\(\)', r'\bDENSE_RANK\s*\(\)',
    r'\bLEAD\s*\(', r'\bLAG\s*\(', r'\bLISTAGG\s*\(',
    r'\bTO_DATE\s*\(', r'\bTO_CHAR\s*\(', r'\bCONNECT\s+BY\b',
    r'\(\+\)', r'\bMERGE\s+INTO\b'
]
GEMINI_P = [
    r'\bPIVOT\b', r'\bUNPIVOT\b', r'\bCONNECT_BY_ROOT\b', r'\bFLASHBACK\b',
    r'\bAS\s+OF\s+TIMESTAMP\b', r'\bBITMAP\b', r'\bSYNONYM\b',
    r'\bMATCH_RECOGNIZE\b', r'\bSUBPARTITION\b', r'\bINSERT\s+ALL\b',
    r'\bORDER\s+SIBLINGS\s+BY\b'
]
GPT_P = [
    r'\bDECLARE\b', r'\bBEGIN\b', r'\bDBMS_\w+',
    r'\bXMLELEMENT\b', r'\bCURSOR\s*\(', r'\bBULK\s+COLLECT\b',
    r'<(IF|ISSET|ISNOTNULL|ISNOTEMPTY|ISNULL|ISEMPTY|ITERATE|CHOOSE|WHEN|OTHERWISE|FOREACH)[\s>]',
    r'</(IF|ISSET|ISNOTNULL|ISNOTEMPTY|ISNULL|ISEMPTY|ITERATE|CHOOSE|WHEN|OTHERWISE|FOREACH)>'
]

LABEL_NAMES  = {0: "Rule", 1: "Llama", 2: "SQLCoder", 3: "Gemini", 4: " GPT (OpenAI)"}
LABEL_TO_LLM = {1: "llama", 2: "sqlcoder", 3: "gemini"}

class Budget:
    def __init__(self, limit: float = 0.80, initial_spent: float = 0.0):
        self.limit = limit
        self.spent = initial_spent
        self.calls = 0

    def charge(self, in_tok: int, out_tok: int) -> float:
        cost = in_tok / 1_000_000 * PRICE_INPUT + out_tok / 1_000_000 * PRICE_OUTPUT
        
        if self.spent + cost > self.limit:
            raise RuntimeError(f"🚨 KESİN DURDURMA: Bütçe limiti aşıldı! Belirlenen Limit: ${self.limit:.2f}")
            
        self.spent += cost
        self.calls += 1
        return cost

    def exceeded(self) -> bool:
        return self.spent >= self.limit

    def remaining(self) -> float:
        return max(0.0, self.limit - self.spent)

    def pct(self) -> float:
        return min(100.0, self.spent / self.limit * 100) if self.limit > 0 else 0.0

def estimate_cost(text: str, out_tokens: int = 600) -> float:
    in_tok = len(text) // 3
    return in_tok / 1_000_000 * PRICE_INPUT + out_tokens / 1_000_000 * PRICE_OUTPUT

def build_azure_client():
    if AzureOpenAI is None or not AZURE_ENDPOINT:
        return None
    try:
        credential = AzureCliCredential()
        token_provider = lambda: credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        ).token
        return AzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version=AZURE_API_VER,
        )
    except Exception:
        return None

def _shadow_sql(sql: str) -> str:
    s = sql

    s = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', s, flags=re.DOTALL)

    for tag in ('if', 'isSet', 'isNotNull', 'isNull', 'isNotEmpty',
                'isEmpty', 'iterate', 'dynamic', 'choose', 'when',
                'otherwise', 'foreach'):
        s = re.sub(
            rf'<{tag}\b[^>]*>.*?</{tag}\s*>',
            ' ', s, flags=re.IGNORECASE | re.DOTALL
        )

    s = re.sub(r'</?[a-zA-Z0-9:_-]+(?:\s[^>]*)?\s*/?>', ' ', s)

    s = re.sub(r'#\{?[a-zA-Z0-9_.]+\}?', "'X'", s)

    s = re.sub(r'(?<![:<])\b:[a-zA-Z_]\w*', "'X'", s)

    s = re.sub(r'\?', '1', s)

    s = re.sub(r'/\*\+.*?\*/', '', s, flags=re.DOTALL)

    s = re.sub(r'[ \t]{2,}', ' ', s)

    return s

def pglast_validate(sql: str) -> tuple[bool, str]:
    if not PGLAST_OK:
        return True, ""
    if not sql or not sql.strip():
        return False, "Bos SQL"

    shadow = (
        _shadow_sql(sql)
        .replace("```sql", "")
        .replace("```", "")
        .strip()
        .rstrip(";")
    )

    if not shadow.strip():
        return False, "Bos SQL (shadow sonrasi)"

    try:
        pg_parser.parse_sql(shadow)
        return True, ""
    except ParseError as e:
        return False, f"Syntax Error: {str(e)}"
    except Exception as e:
        return False, str(e)

def _gpt_call(client, prompt: str, budget: Budget,
              response_json: bool = False) -> dict:
    if budget.exceeded():
        return {"ok": False, "content": None, "cost": 0.0, "error": "Bütçe aşıldı"}
    try:
        kwargs = dict(
            model=DEPLOYMENT_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        if response_json:
            kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**kwargs)
        usage = resp.usage
        cost = budget.charge(usage.prompt_tokens, usage.completion_tokens)
        return {"ok": True, "content": resp.choices[0].message.content.strip(),
                "cost": cost, "error": ""}
    except Exception as e:
        return {"ok": False, "content": None, "cost": 0.0, "error": str(e)}

def gpt_translate(client, oracle_sql: str,
                  schema_ctx: str, budget: Budget) -> dict:
    prompt = SystemPrompts.TRANSLATE_PROMPT.format(
        schema_context=schema_ctx, sql=oracle_sql.strip()
    )
    r = _gpt_call(client, prompt, budget)
    if not r["ok"]:
        return {"ok": False, "sql": None, "cost": r["cost"], "error": r["error"]}
    raw = re.sub(r"```sql\s*|```", "", r["content"], flags=re.IGNORECASE).strip()
    return {"ok": True, "sql": raw, "cost": r["cost"], "error": ""}

def gpt_semantic(client, oracle_sql: str, pg_sql: str,
                 schema_ctx: str, budget: Budget) -> dict:
    prompt = SystemPrompts.SEMANTIC_PROMPT.format(
        schema_context=schema_ctx,
        oracle=oracle_sql.strip(),
        postgres=pg_sql.strip(),
    )
    r = _gpt_call(client, prompt, budget, response_json=False)
    if not r["ok"]:
        return {"valid": False, "issues": r["error"], "cost": r["cost"]}
    raw = re.sub(r"```json\s*|```", "", r["content"]).strip()
    try:
        data = json.loads(raw)
        return {
            "valid": bool(data.get("valid", False)),
            "issues": data.get("critical_mismatch", ""),
            "cost": r["cost"],
        }
    except Exception:
        valid = '"valid": true' in raw.lower()
        return {"valid": valid, "issues": raw[:300], "cost": r["cost"]}

def gpt_fix(client, oracle_sql: str, wrong_sql: str,
            error: str, schema_ctx: str, budget: Budget) -> dict:
    prompt = SystemPrompts.FIX_PROMPT.format(
        critical_mismatch=error,
        oracle=oracle_sql.strip(),
        pg_wrong=wrong_sql.strip(),
        schema_context=schema_ctx,
    )
    r = _gpt_call(client, prompt, budget)
    if not r["ok"]:
        return {"ok": False, "sql": None, "cost": r["cost"], "error": r["error"]}
    raw = re.sub(r"```sql\s*|```", "", r["content"], flags=re.IGNORECASE).strip()
    return {"ok": True, "sql": raw, "cost": r["cost"], "error": ""}

def _extract_features(sql: str) -> dict:
    if not sql or not isinstance(sql, str):
        sql = ""
    s = sql.upper()
    tokens = s.lstrip().split()
    first = tokens[0] if tokens else ''
    return {
        'sql_length': len(sql),
        'token_count': len(sql.split()),
        'is_select': int(first == 'SELECT'),
        'is_create': int(first == 'CREATE'),
        'is_insert': int(first == 'INSERT'),
        'is_merge': int(first == 'MERGE'),
        'is_plsql': int(bool(re.search(r'\bDECLARE\b|\bBEGIN\b', s))),
        'has_join': int(bool(re.search(r'\bJOIN\b', s))),
        'join_count': len(re.findall(r'\bJOIN\b', s)),
        'has_subquery': int(s.count('SELECT') > 1),
        'subquery_count': max(0, s.count('SELECT') - 1),
        'has_group_by': int(bool(re.search(r'\bGROUP\s+BY\b', s))),
        'has_order_by': int(bool(re.search(r'\bORDER\s+BY\b', s))),
        'has_case': int(bool(re.search(r'\bCASE\b', s))),
        'has_distinct': int(bool(re.search(r'\bDISTINCT\b', s))),
        'has_union': int(bool(re.search(r'\bUNION\b', s))),
        'has_exists': int(bool(re.search(r'\bEXISTS\b', s))),
        'has_aggregate': int(bool(re.search(r'\b(SUM|COUNT|AVG|MAX|MIN)\s*\(', s))),
        'has_window_func': int(bool(re.search(r'\bOVER\s*\(', s))),
        'has_partition': int(bool(re.search(r'\bPARTITION\s+BY\b', s))),
        'has_cte': int(bool(re.search(r'\bWITH\b', s))),
        'where_count': len(re.findall(r'\bWHERE\b', s)),
        'has_rownum': int(bool(re.search(r'\bROWNUM\b', s))),
        'has_nvl': int(bool(re.search(r'\bNVL\s*\(', s))),
        'has_decode': int(bool(re.search(r'\bDECODE\s*\(', s))),
        'has_connect_by': int(bool(re.search(r'\bCONNECT\s+BY\b', s))),
        'has_pivot': int(bool(re.search(r'\bPIVOT\b|\bUNPIVOT\b', s))),
        'has_match_recognize': int(bool(re.search(r'\bMATCH_RECOGNIZE\b', s))),
        'has_subpartition': int(bool(re.search(r'\bSUBPARTITION\b', s))),
        'has_insert_all': int(bool(re.search(r'\bINSERT\s+ALL\b', s))),
        'has_siblings': int(bool(re.search(r'\bORDER\s+SIBLINGS\s+BY\b', s))),
        'has_sysdate': int(bool(re.search(r'\bSYSDATE\b', s))),
        'has_oracle_join': int(bool(re.search(r'\(\+\)', s))),
        'has_dbms': int(bool(re.search(r'\bDBMS_\w+', s))),
        'has_xml': int(bool(re.search(r'\bXML\w+\b', s))),
        'has_dual': int(bool(re.search(r'\bFROM\s+DUAL\b', s))),
        'has_merge': int(bool(re.search(r'\bMERGE\s+INTO\b', s))),
        'rule_pattern_count': sum(1 for p in RULE_P if re.search(p, s, re.DOTALL)),
        'sqlcoder_pattern_count': sum(1 for p in SQLCODER_P if re.search(p, s, re.DOTALL)),
        'gemini_pattern_count': sum(1 for p in GEMINI_P if re.search(p, s, re.DOTALL)),
        'gpt_pattern_count': sum(1 for p in GPT_P if re.search(p, s, re.DOTALL)),
    }

def load_ml_router(path: str = ML_MODEL_PATH) -> tuple:
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        return data["model"], data["feature_cols"]
    except Exception:
        return None, None

def predict_llm(sql: str, ml_model, feature_cols) -> str:
    if ml_model is not None and feature_cols is not None and PANDAS_OK:
        try:
            feats = _extract_features(sql)
            df_f = pd.DataFrame([feats])[feature_cols]
            label = int(ml_model.predict(df_f).item())
            if label == 4:
                return "openai"
            return LABEL_TO_LLM.get(label, "openai")
        except Exception:
            pass

    s = sql.upper()
    for p in GPT_P:
        if re.search(p, s, re.DOTALL):
            return "openai"
    for p in GEMINI_P:
        if re.search(p, s, re.DOTALL):
            return "gemini"
    for p in SQLCODER_P:
        if re.search(p, s, re.DOTALL):
            return "sqlcoder"
    return "llama"

_llm_cache: dict = {}

def _get_local_llm(name: str):
    if name in _llm_cache:
        return _llm_cache[name]
    try:
        mod = importlib.import_module(f"llm.{name}")
        llm = mod.get_llm()
        _llm_cache[name] = llm
        return llm
    except Exception:
        return None

def translate_local(oracle_sql: str, llm_name: str) -> tuple[str | None, str]:
    llm = _get_local_llm(llm_name)
    if llm is None:
        return None, f"{llm_name} yüklenemedi"
    try:
        from .local_translator import translate as do_translate
        pg_sql, _, _ = do_translate(oracle_sql, llm)
        return (pg_sql or None), ("" if pg_sql else "Boş yanıt")
    except Exception as e:
        return None, str(e)

def run_semantic(client, oracle_sql: str, pg_sql: str,
                 schema_ctx: str, budget: Budget,
                 do_semantic: bool, label: str, log_fn) -> dict:
    if not do_semantic or client is None:
        log_fn(f"  ↷ Semantic [{label}] atlandı")
        return {"valid": True, "issues": "", "cost": 0.0, "skipped": True}

    est = estimate_cost(
        SystemPrompts.SEMANTIC_PROMPT.format(
            schema_context=schema_ctx, oracle=oracle_sql, postgres=pg_sql
        )
    )
    log_fn(f"  🔎 Semantic [{label}] (~${est:.5f}) çalışıyor...")
    sem = gpt_semantic(client, oracle_sql, pg_sql, schema_ctx, budget)
    sem["skipped"] = False
    icon = "✔" if sem["valid"] else "✗"
    msg = "OK" if sem["valid"] else sem["issues"][:80]
    log_fn(f"  {icon} Semantic [{label}] (${sem['cost']:.5f}): {msg}")
    return sem

def _fast_track(oracle_sql: str, log_fn) -> dict:
    log_fn("🔧 Fast Track — Kural motoru çalışıyor...")
    try:
        out = apply_all_rules(oracle_sql)
    except Exception as e:
        log_fn(f"  ✗ Rules crash: {e}")
        return {"ok": False, "pg_sql": None, "error": f"Rules crash: {e}"}

    if out == LLM_NEEDED:
        log_fn("  → LLM_NEEDED — Smart Router'a yönlendiriliyor")
        return {"ok": False, "pg_sql": None, "error": "LLM_NEEDED"}

    ok, err = pglast_validate(out)
    if ok:
        log_fn("  ✔ Syntax geçti")
        return {"ok": True, "pg_sql": out, "error": ""}
    else:
        log_fn(f"  ✗ Syntax hatası: {err[:70]}")
        return {"ok": False, "pg_sql": out, "error": err}

def _deep_track(oracle_sql: str, llm_name: str, client,
                schema_ctx: str, budget: Budget,
                do_semantic: bool, log_fn) -> dict:
    out = {
        "pg_sql": None, "source": llm_name,
        "syntax_ok": False, "semantic_ok": None,
        "parse_error": "", "semantic_issues": "",
        "cost_translate": 0.0, "cost_semantic": 0.0,
        "fallback_used": False, "status": "HUMAN_REVIEW",
    }

    current_sql, error_reason = _do_translate(
        oracle_sql, llm_name, client, schema_ctx, budget, log_fn, out
    )
    if current_sql is None:
        out["parse_error"] = error_reason
        return out

    result = _validate_and_check(
        oracle_sql, current_sql, client, schema_ctx, budget,
        do_semantic, "Val-B", log_fn, out
    )

    if result == "SUCCESS":
        out["status"] = "SUCCESS"
        out["pg_sql"] = current_sql
        return out

    if result == "HUMAN_REVIEW":
        if client is None:
            log_fn("  ✗ Fallback için OpenAI client yok → Human Review")
            return out

        error_for_fix = out.get("semantic_issues") or out.get("parse_error") or "Bilinmeyen hata"
        log_fn(f"\n  🔧 Fallback (OpenAI, 1x): {error_for_fix[:60]}")
        fix_est = estimate_cost(
            SystemPrompts.FIX_PROMPT.format(
                critical_mismatch=error_for_fix,
                oracle=oracle_sql, pg_wrong=current_sql, schema_context=schema_ctx
            )
        )
        log_fn(f"  [?] Fallback tahmini: ~${fix_est:.5f}")

        fix = gpt_fix(client, oracle_sql, current_sql, error_for_fix, schema_ctx, budget)
        out["cost_translate"] += fix["cost"]
        out["fallback_used"] = True

        if not fix["ok"]:
            log_fn(f"  ✗ Fallback API hatası: {fix['error'][:60]}")
            return out

        current_sql = fix["sql"]
        out["source"] = f"{out['source']}+gpt_fallback"
        log_fn(f"  ✔ Fallback çevirisi alındı (${fix['cost']:.5f})")

        result2 = _validate_and_check(
            oracle_sql, current_sql, client, schema_ctx, budget,
            do_semantic, "Val-C", log_fn, out
        )
        if result2 == "SUCCESS":
            out["status"] = "SUCCESS"
            out["pg_sql"] = current_sql

    return out

def _do_translate(oracle_sql: str, llm_name: str, client,
                  schema_ctx: str, budget: Budget, log_fn, out: dict
                  ) -> tuple[str | None, str]:
    if llm_name == "openai":
        if client is None:
            log_fn("  ✗ OpenAI client yok")
            return None, "OpenAI client yok"
        est = estimate_cost(
            SystemPrompts.TRANSLATE_PROMPT.format(schema_context=schema_ctx, sql=oracle_sql)
        )
        log_fn(f"  🤖 OpenAI çevirisi (~${est:.5f})...")
        r = gpt_translate(client, oracle_sql, schema_ctx, budget)
        out["cost_translate"] += r["cost"]
        if not r["ok"]:
            log_fn(f"  ✗ OpenAI hata: {r['error'][:60]}")
            return None, r["error"]
        log_fn(f"  ✔ OpenAI çevirisi alındı (${r['cost']:.5f})")
        return r["sql"], ""
    else:
        log_fn(f"  🤖 {llm_name} çevirisi...")
        pg_sql, err = translate_local(oracle_sql, llm_name)
        if pg_sql is None:
            log_fn(f"  ✗ {llm_name} başarısız: {err}")
            if client is not None:
                log_fn(f"  → OpenAI fallback deneniyor...")
                est = estimate_cost(
                    SystemPrompts.TRANSLATE_PROMPT.format(schema_context=schema_ctx, sql=oracle_sql)
                )
                r = gpt_translate(client, oracle_sql, schema_ctx, budget)
                out["cost_translate"] += r["cost"]
                if r["ok"]:
                    out["source"] = f"{llm_name}→openai"
                    log_fn(f"  ✔ OpenAI fallback alındı (${r['cost']:.5f})")
                    return r["sql"], ""
                return None, r["error"]
            return None, err
        log_fn(f"  ✔ {llm_name} çevirisi alındı")
        return pg_sql, ""

def _validate_and_check(oracle_sql: str, pg_sql: str, client, schema_ctx: str,
                        budget: Budget, do_semantic: bool, label: str,
                        log_fn, out: dict) -> str:
    ok, err = pglast_validate(pg_sql)
    out["syntax_ok"] = ok
    out["parse_error"] = err
    out["pg_sql"] = pg_sql

    if not ok:
        log_fn(f"  ✗ Syntax [{label}]: {err[:70]}")
        out["status"] = "HUMAN_REVIEW"
        return "HUMAN_REVIEW"

    log_fn(f"  ✔ Syntax [{label}] OK")

    sem = run_semantic(client, oracle_sql, pg_sql, schema_ctx, budget, do_semantic, label, log_fn)
    out["cost_semantic"] += sem["cost"]
    out["semantic_ok"] = sem["valid"]
    out["semantic_issues"] = sem.get("issues", "")

    if sem["valid"]:
        out["status"] = "SUCCESS"
        return "SUCCESS"
    else:
        out["status"] = "HUMAN_REVIEW"
        return "HUMAN_REVIEW"

def process_query(
    oracle_sql: str,
    client,
    ml_model,
    feature_cols,
    schema_store: SchemaStore,
    budget: Budget,
    do_semantic: bool,
    log_fn,
) -> dict:
    t_start = time.time()

    result = {
        "oracle_sql": oracle_sql,
        "pg_sql": None,
        "status": "HUMAN_REVIEW",
        "track": "unknown",
        "source": "failed",
        "syntax_ok": False,
        "semantic_ok": None,
        "parse_error": "",
        "semantic_issues": "",
        "cost_translate": 0.0,
        "cost_semantic": 0.0,
        "total_cost": 0.0,
        "fallback_used": False,
        "duration_s": 0.0,
    }

    schema_ctx = schema_store.context_for_query(oracle_sql)

    fast = _fast_track(oracle_sql, log_fn)

    if fast["ok"]:
        sem_a = run_semantic(
            client, oracle_sql, fast["pg_sql"], schema_ctx, budget,
            do_semantic, "Val-A", log_fn
        )
        result["cost_semantic"] += sem_a["cost"]

        if sem_a["valid"]:
            result.update({
                "pg_sql": fast["pg_sql"],
                "status": "SUCCESS",
                "track": "fast",
                "source": "rules",
                "syntax_ok": True,
                "semantic_ok": True if not sem_a.get("skipped") else None,
            })
            result["total_cost"] = result["cost_translate"] + result["cost_semantic"]
            result["duration_s"] = round(time.time() - t_start, 2)
            log_fn(f"✅ Fast Track SUCCESS — ${result['total_cost']:.5f} | {result['duration_s']}s")
            return result
        else:
            log_fn(f"  → Val-A başarısız → Smart Router'a geçiliyor")
            result["semantic_issues"] = sem_a.get("issues", "")
            result["track"] = "fast_to_deep"
    else:
        result["parse_error"] = fast["error"]
        result["track"] = "deep_direct" if fast["error"] == "LLM_NEEDED" else "fast_fallback_deep"

    llm_name = predict_llm(oracle_sql, ml_model, feature_cols)
    log_fn(f"🧭 Smart Router → {llm_name.upper()}")

    deep = _deep_track(
        oracle_sql=oracle_sql,
        llm_name=llm_name,
        client=client,
        schema_ctx=schema_ctx,
        budget=budget,
        do_semantic=do_semantic,
        log_fn=log_fn,
    )

    result.update({
        "pg_sql": deep["pg_sql"],
        "status": deep["status"],
        "source": deep["source"],
        "syntax_ok": deep["syntax_ok"],
        "semantic_ok": deep["semantic_ok"],
        "parse_error": deep["parse_error"],
        "semantic_issues": deep["semantic_issues"],
        "cost_translate": result["cost_translate"] + deep["cost_translate"],
        "cost_semantic": result["cost_semantic"] + deep["cost_semantic"],
        "fallback_used": deep["fallback_used"],
    })

    result["total_cost"] = result["cost_translate"] + result["cost_semantic"]
    result["duration_s"] = round(time.time() - t_start, 2)

    icon = "✅" if result["status"] == "SUCCESS" else "❌"
    log_fn(
        f"{icon} Deep Track {result['status']} via {result['source']} — "
        f"${result['total_cost']:.5f} | {result['duration_s']}s"
    )
    return result