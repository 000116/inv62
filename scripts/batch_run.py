import os
import sys
import pandas as pd
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

from core.pipeline import process_query, build_azure_client, load_ml_router, Budget, DEFAULT_SCHEMA
from core.schema_store import SchemaStore

INPUT_FILE = "dataset.xlsx"
OUTPUT_FILE = "results_627.xlsx"
SQL_COLUMN = "sql_query"

def dummy_logger(msg: str):
    pass

def run_batch_evaluation():
    print(f"🚀 Veri seti yükleniyor: {INPUT_FILE}")
    try:
        if INPUT_FILE.endswith(".csv"):
            df = pd.read_csv(INPUT_FILE)
        else:
            df = pd.read_excel(INPUT_FILE)
    except Exception as e:
        print(f"❌ Dosya okuma hatası: {e}")
        return

    print("🧠 Yapay Zeka ve ML modelleri ayağa kaldırılıyor...")
    client = build_azure_client()
    ml_model, feature_cols = load_ml_router()
    schema_store = SchemaStore(DEFAULT_SCHEMA)
    
    results_list = []
    total_queries = len(df)
    
    print(f"⚡ Toplam {total_queries} sorgu işlenmeye başlıyor...\n" + "="*50)
    
    start_time_global = time.time()
    
    for index, row in df.iterrows():
        oracle_sql = str(row[SQL_COLUMN])
        
        print(f"[{index + 1}/{total_queries}] Sorgu işleniyor...")
        
        budget_obj = Budget(limit=5.0, initial_spent=0.0) 
        
        try:
            result = process_query(
                oracle_sql=oracle_sql,
                client=client,
                ml_model=ml_model,
                feature_cols=feature_cols,
                schema_store=schema_store,
                budget=budget_obj,
                do_semantic=True,
                log_fn=dummy_logger
            )
            
            results_list.append({
                "ID": row.get("id", index + 1),
                "Oracle_SQL": oracle_sql,
                "PostgreSQL": result.get("pg_sql", ""),
                "Status": result.get("status", "FAILED"),
                "Track": result.get("track", ""),
                "Source_LLM": result.get("source", ""),
                "Syntax_OK": result.get("syntax_ok", False),
                "Semantic_OK": result.get("semantic_ok", False),
                "Fallback_Used": result.get("fallback_used", False),
                "Cost_USD": result.get("total_cost", 0.0),
                "Duration_sec": result.get("duration_s", 0.0),
                "Parse_Error": result.get("parse_error", ""),
                "Semantic_Issues": result.get("semantic_issues", "")
            })
            
            icon = "✅" if result.get("status") == "SUCCESS" else "❌"
            print(f"   {icon} Sonuç: {result.get('status')} | Track: {result.get('track')} | Süre: {result.get('duration_s')}s")
            
        except Exception as e:
            print(f"   🚨 KRİTİK HATA: Bu sorgu sistemi çökertti: {e}")
            results_list.append({
                "ID": row.get("id", index + 1),
                "Oracle_SQL": oracle_sql,
                "Status": "SYSTEM_CRASH",
                "Parse_Error": str(e)
            })
            
        time.sleep(0.5)
        
        if (index + 1) % 50 == 0:
            temp_df = pd.DataFrame(results_list)
            temp_df.to_excel("backup_results.xlsx", index=False)
            print(f"💾 [BACKUP] {index + 1} sorgu yedeklendi.")

    total_time_mins = (time.time() - start_time_global) / 60
    
    final_df = pd.DataFrame(results_list)
    final_df.to_excel(OUTPUT_FILE, index=False)
    
    print("="*50)
    print(f"🎉 İŞLEM TAMAMLANDI!")
    print(f"📂 Sonuçlar '{OUTPUT_FILE}' dosyasına kaydedildi.")
    print(f"⏱️ Toplam Geçen Süre: {total_time_mins:.2f} dakika")
    print(f"💰 Toplam Harcanan Maliyet: ${final_df['Cost_USD'].sum():.4f}")
    print(f"✅ Başarılı Çeviri Sayısı: {len(final_df[final_df['Status'] == 'SUCCESS'])}")

if __name__ == "__main__":
    run_batch_evaluation()