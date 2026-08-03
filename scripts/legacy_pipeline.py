import os
import re
import sys
import time
import pickle
import hashlib
import pandas as pd
import importlib

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

try:
    from pglast import parser
    from pglast.parser import ParseError
except ImportError:
    print("ERROR: Library 'pglast' not found. Please install it: pip install pglast")
    exit()

try:
    from core.rules import apply_all_rules
except ImportError:
    print("WARNING: 'core/rules.py' not found. Please ensure the project structure is intact.")
    exit()

RULE_P = [r'\bNVL\s*\(',r'\bSYSDATE\b',r'\bROWNUM\b',r'\bDECODE\s*\(',
          r'\bVARCHAR2\b',r'\bFROM\s+DUAL\b',r':[a-zA-Z_]\w*']
SQLCODER_P = [r'\bROW_NUMBER\s*\(\)',r'\bRANK\s*\(\)',r'\bDENSE_RANK\s*\(\)',
              r'\bLEAD\s*\(',r'\bLAG\s*\(',r'\bLISTAGG\s*\(',r'\bTO_DATE\s*\(',
              r'\bTO_CHAR\s*\(',r'\bCONNECT\s+BY\b',r'\(\+\)',r'\bMERGE\s+INTO\b']
GEMINI_P = [r'\bPIVOT\b',r'\bUNPIVOT\b',r'\bCONNECT_BY_ROOT\b',r'\bFLASHBACK\b',
            r'\bAS\s+OF\s+TIMESTAMP\b',r'\bBITMAP\b',r'\bSYNONYM\b',
            r'\bMATCH_RECOGNIZE\b',r'\bSUBPARTITION\b',r'\bINSERT\s+ALL\b',
            r'\bORDER\s+SIBLINGS\s+BY\b']
HUMAN_P = [r'\bDECLARE\b',r'\bBEGIN\b',r'\bDBMS_\w+',
           r'\bXMLELEMENT\b',r'\bCURSOR\s*\(',r'\bBULK\s+COLLECT\b']

LABEL_TO_MODEL = {1: "llama", 2: "sqlcoder", 3: "gemini"}
LABEL_NAMES = {0: "Rule", 1: "Llama", 2: "SQLCoder", 3: "Gemini", 4: "Human Review"}

def get_sql_hash(sql: str) -> str:
    return hashlib.md5(sql.encode('utf-8')).hexdigest()[:12]

def validate_with_pglast(sql):
    if not sql: return False, "Empty Query"
    clean_sql = str(sql).replace("```sql", "").replace("```", "").strip().rstrip(';')
    try:
        parser.parse_sql(clean_sql)
        return True, None
    except ParseError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unknown Error: {str(e)}"

def load_llm(model_name: str):
    module = importlib.import_module(f"llm.{model_name}")
    return module.get_llm()

def translate_with_llm(oracle_sql: str, llm) -> tuple:
    from core.local_translator import translate
    translated_sql, source_used, _ = translate(oracle_sql, llm)
    return translated_sql, source_used

def extract_features(sql):
    if not sql or not isinstance(sql,str): sql=""
    s = sql.upper()
    tokens = s.lstrip().split()
    first  = tokens[0] if tokens else ''
    return {
        'sql_length': len(sql),
        'token_count': len(sql.split()),
        'is_select': int(first=='SELECT'),
        'is_create': int(first=='CREATE'),
        'is_insert': int(first=='INSERT'),
        'is_merge': int(first=='MERGE'),
        'is_plsql': int(bool(re.search(r'\bDECLARE\b|\bBEGIN\b',s))),
        'has_join': int(bool(re.search(r'\bJOIN\b',s))),
        'join_count': len(re.findall(r'\bJOIN\b',s)),
        'has_subquery': int(s.count('SELECT')>1),
        'subquery_count': max(0,s.count('SELECT')-1),
        'has_group_by': int(bool(re.search(r'\bGROUP\s+BY\b',s))),
        'has_order_by': int(bool(re.search(r'\bORDER\s+BY\b',s))),
        'has_case': int(bool(re.search(r'\bCASE\b',s))),
        'has_distinct': int(bool(re.search(r'\bDISTINCT\b',s))),
        'has_union': int(bool(re.search(r'\bUNION\b',s))),
        'has_exists': int(bool(re.search(r'\bEXISTS\b',s))),
        'has_aggregate': int(bool(re.search(r'\b(SUM|COUNT|AVG|MAX|MIN)\s*\(',s))),
        'has_window_func': int(bool(re.search(r'\bOVER\s*\(',s))),
        'has_partition': int(bool(re.search(r'\bPARTITION\s+BY\b',s))),
        'has_cte': int(bool(re.search(r'\bWITH\b',s))),
        'where_count': len(re.findall(r'\bWHERE\b',s)),
        'has_rownum': int(bool(re.search(r'\bROWNUM\b',s))),
        'has_nvl': int(bool(re.search(r'\bNVL\s*\(',s))),
        'has_decode': int(bool(re.search(r'\bDECODE\s*\(',s))),
        'has_connect_by': int(bool(re.search(r'\bCONNECT\s+BY\b',s))),
        'has_pivot': int(bool(re.search(r'\bPIVOT\b|\bUNPIVOT\b',s))),
        'has_match_recognize': int(bool(re.search(r'\bMATCH_RECOGNIZE\b',s))),
        'has_subpartition': int(bool(re.search(r'\bSUBPARTITION\b',s))),
        'has_insert_all': int(bool(re.search(r'\bINSERT\s+ALL\b',s))),
        'has_siblings': int(bool(re.search(r'\bORDER\s+SIBLINGS\s+BY\b',s))),
        'has_sysdate': int(bool(re.search(r'\bSYSDATE\b',s))),
        'has_oracle_join': int(bool(re.search(r'\(\+\)',s))),
        'has_dbms': int(bool(re.search(r'\bDBMS_\w+',s))),
        'has_xml': int(bool(re.search(r'\bXML\w+\b',s))),
        'has_dual': int(bool(re.search(r'\bFROM\s+DUAL\b',s))),
        'has_merge': int(bool(re.search(r'\bMERGE\s+INTO\b',s))),
        'rule_pattern_count': sum(1 for p in RULE_P if re.search(p,s,re.DOTALL)),
        'sqlcoder_pattern_count': sum(1 for p in SQLCODER_P if re.search(p,s,re.DOTALL)),
        'gemini_pattern_count': sum(1 for p in GEMINI_P if re.search(p,s,re.DOTALL)),
        'human_review_pattern_count': sum(1 for p in HUMAN_P if re.search(p,s,re.DOTALL)),
    }

def main():
    print(f"\n{'='*60}")
    print(f"  SMART QUERY ROUTER - HYBRID PIPELINE")
    print(f"{'='*60}\n")

    model_path = "smart_router_model_v5.pkl"
    if not os.path.exists(model_path):
        print(f"[ERROR] ML Model not found: {model_path}. train_router_v5.py must be run first.")
        return
        
    with open(model_path, 'rb') as f:
        model_data = pickle.load(f)
        ml_model = model_data['model']
        feature_cols = model_data['feature_cols']
        model_name = model_data.get('model_name', 'Unknown')
        print(f"Smart Router ML Model ({model_name}) has been successfully installed.")

    dataset_path = 'sondataset.xlsx'
    if not os.path.exists(dataset_path):
        print(f"[ERROR] Dataset not found: {dataset_path}")
        return
        
    df = pd.read_excel(dataset_path)
    print(f"A total of {len(df)} queries have been loaded for processing.\n")

    loaded_llms = {}
    results = []
    
    start_time = time.time()

    for idx, row in df.iterrows():
        oracle_sql = row.get('SQL') if pd.notna(row.get('SQL')) else row.get('sql_query')
        if pd.isna(oracle_sql) or not str(oracle_sql).strip(): continue
        
        query_id = idx + 1
        print(f"[{query_id}/{len(df)}] Processing...")

        query_start = time.time()
        final_pg_sql = ""
        is_valid = False
        parse_error = ""
        solved_by = "failed"
        try:
            pg_sql_candidate = apply_all_rules(str(oracle_sql))
            is_valid, parse_error = validate_with_pglast(pg_sql_candidate)
            if is_valid:
                final_pg_sql = pg_sql_candidate
                solved_by = "rules"
        except Exception as e:
            is_valid = False
            parse_error = f"Rules Crash: {str(e)}"

        if not is_valid:
            print(f"  └ Rule-based failure. Going to ML Router...")
            
            features_dict = extract_features(oracle_sql)
            features_df = pd.DataFrame([features_dict])[feature_cols] 
            
            predicted_label = int(ml_model.predict(features_df).item())
            predicted_model_name = LABEL_NAMES.get(predicted_label, "Unknown")
            print(f"  └ Router Decision: {predicted_model_name} (Label {predicted_label})")

            if predicted_label in LABEL_TO_MODEL:
                target_llm_name = LABEL_TO_MODEL[predicted_label]

                if target_llm_name not in loaded_llms:
                    try:
                        loaded_llms[target_llm_name] = load_llm(target_llm_name)
                    except Exception as e:
                        print(f"[ERROR] Could not load model {target_llm_name}: {e}")
                
                llm_instance = loaded_llms.get(target_llm_name)
                
                if llm_instance:
                    try:
                        pg_sql_candidate, _ = translate_with_llm(str(oracle_sql), llm_instance)
                        is_valid, parse_error = validate_with_pglast(pg_sql_candidate)
                        
                        if is_valid:
                            final_pg_sql = pg_sql_candidate
                            solved_by = f"ml_routed_{target_llm_name}"
                            print("Successfully translated with an LLM.")
                        else:
                            print(f"The LLM translation failed the PGLast validation.: {str(parse_error)[:60]}...")
                    except Exception as e:
                        parse_error = f"LLM Crash: {str(e)}"
            elif predicted_label == 4:
                 print("Router assigned this query directly to the Human Review (GPT Fallback) category.")
                 parse_error = "Routed to Human Review (Label 4) due to complexity."

        query_duration = time.time() - query_start

        results.append({
            'query_id': query_id,
            'original_oracle_sql': str(oracle_sql),
            'translated_pg_sql': final_pg_sql if is_valid else None,
            'status': "SUCCESS" if is_valid else "FAILED",
            'solved_by': solved_by,
            'parse_error': parse_error if not is_valid else "",
            'query_time_seconds': round(query_duration, 2)
        })

    os.makedirs("reports", exist_ok=True)
    
    full_report_df = pd.DataFrame(results)
    full_report_path = "reports/pipeline_full_analysis.csv"
    full_report_df.to_csv(full_report_path, index=False)
    failed_df = full_report_df[full_report_df['status'] == 'FAILED'].copy()
    total_queries = len(results)
    success_count = len(full_report_df[full_report_df['status'] == 'SUCCESS'])
    fail_count = len(failed_df)
    
    print(f"\n{'='*60}")
    print(f"OPERATION SUMMARY")
    print(f"{'='*60}")
    print(f"Total Processed: {total_queries}")
    print(f"Successful Conversion: {success_count} (%{(success_count/total_queries)*100:.1f})")
    print(f"Total Time: {(time.time() - start_time) / 60:.1f} minutes")
    print(f"\nAll analysis report saved: {full_report_path}")

if __name__ == "__main__":
    main()