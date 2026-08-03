import os, re, pickle, warnings
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.model_selection import cross_val_score, StratifiedKFold, train_test_split
from sklearn.metrics import classification_report, confusion_matrix

warnings.filterwarnings("ignore")
def try_import(pkg, install_name=None):
    import importlib
    try:
        return importlib.import_module(pkg)
    except ImportError:
        print(f"! '{pkg}' is not installed → pip install {install_name or pkg}")
        return None

shap_lib     = try_import("shap")
catboost_lib = try_import("catboost")
lgbm_lib     = try_import("lightgbm")
xgb_lib      = try_import("xgboost")
mpl_lib      = try_import("matplotlib.pyplot", "matplotlib")

DATASET_FILE = "sondataset.xlsx"
REPORTS_DIR  = "reports"
MODEL_OUTPUT = "smart_router_model_v5.pkl"
REPORT_CSV   = "training_report_v5.csv"

BATCH1_FAIL_MAP = {
    4:4, 12:4, 22:2, 33:2,       
    23:2, 25:2, 28:2, 36:2, 37:2, 
    38:2, 40:2, 42:2, 43:2, 44:2, 45:2,
}

LABEL_NAMES = {0:"Rule", 1:"Llama", 2:"SQLCoder", 3:"Gemini", 4:"Human Review"}

RULE_P = [r'\bNVL\s*\(',r'\bSYSDATE\b',r'\bROWNUM\b',r'\bDECODE\s*\(',
          r'\bVARCHAR2\b',r'\bFROM\s+DUAL\b',r':[a-zA-Z_]\w*']
SQLCODER_P = [r'\bROW_NUMBER\s*\(\)',r'\bRANK\s*\(\)',r'\bDENSE_RANK\s*\(\)',
              r'\bLEAD\s*\(',r'\bLAG\s*\(',r'\bLISTAGG\s*\(',r'\bTO_DATE\s*\(',
              r'\bTO_CHAR\s*\(',r'\bCONNECT\s+BY\b',r'\(\+\)']
GEMINI_P = [r'\bPIVOT\b',r'\bUNPIVOT\b',r'\bCONNECT_BY_ROOT\b',r'\bFLASHBACK\b',
            r'\bAS\s+OF\s+TIMESTAMP\b',r'\bBITMAP\b',r'\bSYNONYM\b',
            r'\bMATCH_RECOGNIZE\b',r'\bSUBPARTITION\b',r'\bINSERT\s+ALL\b',
            r'\bORDER\s+SIBLINGS\s+BY\b', r'\bMODEL\s+PARTITION\b',r'\bMERGE\s+INTO\b'] 
HUMAN_P = [r'\bDECLARE\b',r'\bBEGIN\b',r'\bDBMS_\w+',
           r'\bXMLELEMENT\b',r'\bCURSOR\s*\(',r'\bBULK\s+COLLECT\b']

def get_group(sql):
    s = str(sql).upper()
    for p in HUMAN_P:
        if re.search(p, s, re.DOTALL): return 3
    for p in GEMINI_P:
        if re.search(p, s, re.DOTALL): return 2
    for p in SQLCODER_P:
        if re.search(p, s, re.DOTALL): return 1
    return 0

def complexity_score(sql):
    s = str(sql).upper()
    score = len(sql)*0.1 + len(sql.split())*2
    score += len(re.findall(r'\bJOIN\b',s))*15
    score += len(re.findall(r'\bSELECT\b',s))*20
    score += sum(10 for p in GEMINI_P if re.search(p,s,re.DOTALL))
    score += sum(20 for p in HUMAN_P if re.search(p,s,re.DOTALL))
    score += len(re.findall(r'\bWHERE\b',s))*5
    score += len(re.findall(r'\bOVER\s*\(',s))*15
    return score

def extract_features(sql):
    if not sql or not isinstance(sql,str): sql=""
    s = sql.upper()
    first = s.lstrip().split()[0] if s.strip() else ''
    return {
        'sql_length'                : len(sql),
        'token_count'               : len(sql.split()),
        'is_select'                 : int(first=='SELECT'),
        'is_create'                 : int(first=='CREATE'),
        'is_insert'                 : int(first=='INSERT'),
        'is_merge'                  : int(first=='MERGE'),
        'is_plsql'                  : int(bool(re.search(r'\bDECLARE\b|\bBEGIN\b',s))),
        'has_join'                  : int(bool(re.search(r'\bJOIN\b',s))),
        'join_count'                : len(re.findall(r'\bJOIN\b',s)),
        'has_subquery'              : int(s.count('SELECT')>1),
        'subquery_count'            : max(0,s.count('SELECT')-1),
        'has_group_by'              : int(bool(re.search(r'\bGROUP\s+BY\b',s))),
        'has_order_by'              : int(bool(re.search(r'\bORDER\s+BY\b',s))),
        'has_case'                  : int(bool(re.search(r'\bCASE\b',s))),
        'has_distinct'              : int(bool(re.search(r'\bDISTINCT\b',s))),
        'has_union'                 : int(bool(re.search(r'\bUNION\b',s))),
        'has_exists'                : int(bool(re.search(r'\bEXISTS\b',s))),
        'has_aggregate'             : int(bool(re.search(r'\b(SUM|COUNT|AVG|MAX|MIN)\s*\(',s))),
        'has_window_func'           : int(bool(re.search(r'\bOVER\s*\(',s))),
        'has_partition'             : int(bool(re.search(r'\bPARTITION\s+BY\b',s))),
        'has_cte'                   : int(bool(re.search(r'\bWITH\b',s))),
        'where_count'               : len(re.findall(r'\bWHERE\b',s)),
        'has_rownum'                : int(bool(re.search(r'\bROWNUM\b',s))),
        'has_nvl'                   : int(bool(re.search(r'\bNVL\s*\(',s))),
        'has_decode'                : int(bool(re.search(r'\bDECODE\s*\(',s))),
        'has_connect_by'            : int(bool(re.search(r'\bCONNECT\s+BY\b',s))),
        'has_pivot'                 : int(bool(re.search(r'\bPIVOT\b|\bUNPIVOT\b',s))),
        'has_match_recognize'       : int(bool(re.search(r'\bMATCH_RECOGNIZE\b',s))),
        'has_subpartition'          : int(bool(re.search(r'\bSUBPARTITION\b',s))),
        'has_insert_all'            : int(bool(re.search(r'\bINSERT\s+ALL\b',s))),
        'has_siblings'              : int(bool(re.search(r'\bORDER\s+SIBLINGS\s+BY\b',s))),
        'has_sysdate'               : int(bool(re.search(r'\bSYSDATE\b',s))),
        'has_oracle_join'           : int(bool(re.search(r'\(\+\)',s))),
        'has_dbms'                  : int(bool(re.search(r'\bDBMS_\w+',s))),
        'has_xml'                   : int(bool(re.search(r'\bXML\w+\b',s))),
        'has_dual'                  : int(bool(re.search(r'\bFROM\s+DUAL\b',s))),
        'has_merge'                 : int(bool(re.search(r'\bMERGE\s+INTO\b',s))),
        'rule_pattern_count'        : sum(1 for p in RULE_P if re.search(p,s,re.DOTALL)),
        'sqlcoder_pattern_count'    : sum(1 for p in SQLCODER_P if re.search(p,s,re.DOTALL)),
        'gemini_pattern_count'      : sum(1 for p in GEMINI_P if re.search(p,s,re.DOTALL)),
        'human_review_pattern_count': sum(1 for p in HUMAN_P if re.search(p,s,re.DOTALL)),
    }

def label_from_result(parsed, llm_retry, sql, model_name="sqlcoder"):
    MODEL_LABEL = {"llama": 1, "sqlcoder": 2, "gemini": 3}
    if not llm_retry and parsed:  return 0
    if llm_retry and parsed:      return MODEL_LABEL.get(model_name, 2)
    su = str(sql).upper()
    if any(re.search(p,su,re.DOTALL) for p in HUMAN_P): return 4
    return 3 if any(re.search(p,su,re.DOTALL) for p in GEMINI_P) else 2

def load_csv(path):
    df = pd.read_csv(path)
    df['parsed']    = df['parsed'].astype(str).str.lower().isin(['true','1'])
    df['llm_retry'] = df['llm_retry'].astype(str).str.lower().isin(['true','1'])
    return df

def load_batches(df):
    llama_sampled_ids = set()
    p0 = os.path.join(REPORTS_DIR, "analysis_report_llama.csv")
    if not os.path.exists(p0):
        p0 = os.path.join(REPORTS_DIR, "analysis_report_llama_full.csv")
    if os.path.exists(p0):
        csv0 = load_csv(p0)
        csv0_map = {int(r['query_id']): r for _,r in csv0.iterrows()}
        rows0 = []
        for qid, r in csv0_map.items():
            row_df = df[df['query_id'] == qid]
            if len(row_df) == 0: continue
            sql   = str(row_df['sql_query'].values[0])
            label = label_from_result(r['parsed'], r['llm_retry'], sql, model_name="llama")
            if label == 1:
                rows0.append({'query_id': qid, 'sql_query': sql, 'best_route_label': 1, 'batch': 0})
                llama_sampled_ids.add(qid)
        df_b0 = pd.DataFrame(rows0)
    else:
        df_b0 = pd.DataFrame(columns=['query_id','sql_query','best_route_label','batch'])

    sampled_ids = set(llama_sampled_ids)
    for grp, n in {0:40, 1:30, 2:20, 3:10}.items():
        g = df[~df['query_id'].isin(sampled_ids) & (df['group']==grp)]
        sampled_ids.update(g.sample(min(n,len(g)), random_state=42)['query_id'].tolist())

    p1 = os.path.join(REPORTS_DIR, "analysis_report_gemini.csv")
    csv1 = load_csv(p1) if os.path.exists(p1) else None
    if csv1 is not None:
        csv1_map = {int(r['query_id']): r for _,r in csv1.iterrows()}
    else:
        csv1_map = {}

    rows1 = []
    for qid in sorted(sampled_ids - llama_sampled_ids):
        sql = df[df['query_id']==qid]['sql_query'].values[0]
        if qid in csv1_map:
            r = csv1_map[qid]
            label = label_from_result(r['parsed'], r['llm_retry'], sql, model_name="gemini")
        else:
            label = BATCH1_FAIL_MAP.get(qid, 0)
        rows1.append({'query_id':qid,'sql_query':sql,'best_route_label':label,'batch':1})
    df_b1 = pd.DataFrame(rows1)
    df_b1 = pd.concat([df_b0, df_b1], ignore_index=True).drop_duplicates('query_id')
    df_rem  = df[~df['query_id'].isin(sampled_ids)].copy()
    df_human = df_rem[df_rem['group']==3]
    df_gem   = df_rem[df_rem['group']==2].nlargest(max(0, 40-len(df_human)),'complexity_score')
    df_hard  = pd.concat([df_human, df_gem]).drop_duplicates('query_id').nlargest(40,'complexity_score')
    df_med  = df_rem[df_rem['group']==1].nlargest(30,'complexity_score')
    df_rl   = df_rem[df_rem['group']==0].nlargest(20,'complexity_score')
    sel     = pd.concat([df_hard,df_med,df_rl]).drop_duplicates('query_id').reset_index(drop=True)
    sel['position'] = range(1, len(sel)+1)

    csv2 = None
    for fname in ["analysis_report_sqlcoder.csv"]:
        p = os.path.join(REPORTS_DIR, fname)
        if os.path.exists(p):
            csv2 = load_csv(p)
            break
    if csv2 is None:
        return df_b1

    csv2_map = {int(r['query_id']): r for _,r in csv2.iterrows()}
    rows2 = []
    for _,row in sel.iterrows():
        pos = int(row['position']); sql = str(row['sql_query'])
        r   = csv2_map.get(pos)
        label = label_from_result(r['parsed'], r['llm_retry'], sql, model_name="sqlcoder") if r is not None else 0
        rows2.append({'query_id':int(row['query_id']),'sql_query':sql,
                      'best_route_label':label,'batch':2})
    df_b2 = pd.DataFrame(rows2)
    df_combined = pd.concat([df_b1, df_b2], ignore_index=True).drop_duplicates('query_id')

    MIN_HUMAN_SAMPLES = 8
    existing_ids = set(df_combined['query_id'].tolist())
    current_human = (df_combined['best_route_label'] == 4).sum()

    if current_human < MIN_HUMAN_SAMPLES:
        needed = MIN_HUMAN_SAMPLES - current_human

        df_h3_new = df[
            (df['group'] == 3) & (~df['query_id'].isin(existing_ids))
        ].nlargest(needed * 2, 'complexity_score')
        df_misslabeled = df_combined[
            df_combined['sql_query'].apply(
                lambda s: any(re.search(p, str(s).upper(), re.DOTALL) for p in HUMAN_P)
            ) & (df_combined['best_route_label'] != 4)
        ]

        rows3 = []

        p3 = os.path.join(REPORTS_DIR, "analysis_report_sqlcoder_batch3.csv")
        csv3 = load_csv(p3) if os.path.exists(p3) else None
        csv3_map = {int(r['query_id']): r for _, r in csv3.iterrows()} if csv3 is not None else {}

        for _, row in df_h3_new.head(needed).iterrows():
            qid = int(row['query_id']); sql = str(row['sql_query'])
            if qid in csv3_map:
                r = csv3_map[qid]; label = label_from_result(r['parsed'], r['llm_retry'], sql)
            else:
                su = sql.upper()
                label = 4 if any(re.search(p, su, re.DOTALL) for p in HUMAN_P) else 3
            rows3.append({'query_id': qid, 'sql_query': sql,
                          'best_route_label': label, 'batch': 3})

        if rows3:
            df_b3 = pd.DataFrame(rows3)
            new_human = (df_b3['best_route_label'] == 3).sum()
            df_combined = pd.concat([df_combined, df_b3], ignore_index=True).drop_duplicates('query_id')
        elif len(df_misslabeled) > 0:
            fix_count = min(needed, len(df_misslabeled))
            fix_ids   = df_misslabeled.head(fix_count)['query_id'].tolist()
            df_combined.loc[
                df_combined['query_id'].isin(fix_ids), 'best_route_label'
            ] = 4
        else:
            print(f"Batch 3: No additional Human Review candidates found — dataset group=3 exhausted")
    else:
        print(f"Label 4 is sufficient ({current_human} sample ≥ {MIN_HUMAN_SAMPLES}), Batch 3 skipped")

    return df_combined

def build_models():
    models = {
        "RandomForest"    : RandomForestClassifier(n_estimators=300, max_depth=10,
                             class_weight='balanced', random_state=42),
        "GradientBoosting": GradientBoostingClassifier(n_estimators=150, learning_rate=0.1,
                                                     max_depth=4, max_features='sqrt', random_state=42),
        "DecisionTree"    : DecisionTreeClassifier(max_depth=8, class_weight='balanced',
                                                   random_state=42),
    }
    if xgb_lib:
        models["XGBoost"] = xgb_lib.XGBClassifier(
            n_estimators=200, learning_rate=0.1, max_depth=6,
            use_label_encoder=False, eval_metric='mlogloss',
            random_state=42, verbosity=0)
    if lgbm_lib:
        models["LightGBM"] = lgbm_lib.LGBMClassifier(
            n_estimators=200, learning_rate=0.05, max_depth=6,
            class_weight='balanced', random_state=42, verbose=-1)
    if catboost_lib:
        models["CatBoost"] = catboost_lib.CatBoostClassifier(
            iterations=200, learning_rate=0.05, depth=6,
            auto_class_weights='Balanced', random_seed=42, verbose=0)
    return models

def run_cv(models, X, y):
    counts_main = y[~y.isin([1, 4])].value_counts()
    n_splits = max(2, min(5, int(counts_main.min()))) if len(counts_main) > 0 else 5
    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    print(f"\n{'─'*76}")
    print(f"{'Model':<20} {'CV Acc':>8} {'±Acc':>6} {'CV F1':>8} {'±F1':>6}  Fold F1s")
    print(f"{'─'*76}")

    results = {}
    best_name, best_f1, best_model = None, -1, None

    for name, model in models.items():
        acc_s = cross_val_score(model, X, y, cv=cv, scoring='accuracy')
        f1_s  = cross_val_score(model, X, y, cv=cv, scoring='f1_weighted')
        fold_str = " ".join(f"{s:.3f}" for s in f1_s)
        marker   = "" if f1_s.mean() > best_f1 else ""
        if f1_s.mean() > best_f1:
            best_f1, best_name, best_model = f1_s.mean(), name, model
        print(f"{name:<20} {acc_s.mean():>8.4f} {acc_s.std():>6.4f} "
              f"{f1_s.mean():>8.4f} {f1_s.std():>6.4f}  [{fold_str}]{marker}")
        results[name] = {'cv_acc':acc_s.mean(),'cv_acc_std':acc_s.std(),
                         'cv_f1':f1_s.mean(),'cv_f1_std':f1_s.std(),
                         'fold_f1s':f1_s.tolist()}

    print(f"\nSelected: {best_name}  (CV F1: {best_f1:.4f} ± {results[best_name]['cv_f1_std']:.4f})")
    return best_name, best_model, best_f1, results

def oversample_minority(X, y):
    X_resampled = X.copy()
    y_resampled = y.copy()

    max_class_size = y.value_counts().max()
    target_size = int(max_class_size * 0.8)
    
    for label in y.unique():
        label_idx = y[y == label].index
        if len(label_idx) < target_size:
            diff = target_size - len(label_idx)
            sample_idx = np.random.choice(label_idx, size=diff, replace=True)
            X_resampled = pd.concat([X_resampled, X.loc[sample_idx]], ignore_index=True)
            y_resampled = pd.concat([y_resampled, y.loc[sample_idx]], ignore_index=True)
            
    return X_resampled, y_resampled

def main():
    print(f"\n{'='*60}")
    print(f"  SMART QUERY ROUTER v5")
    print(f"{'='*60}\n")

    if not os.path.exists(DATASET_FILE):
        print(f"ERROR: '{DATASET_FILE}' not found."); return

    df = pd.read_excel(DATASET_FILE)
    df['group']            = df['sql_query'].apply(get_group)
    df['complexity_score'] = df['sql_query'].apply(complexity_score)
    df['query_id']         = range(1, len(df)+1)
    print(f"{len(df)} query loaded.\n")

    df_all = load_batches(df)
    print(f"\n Total: {len(df_all)} query | Label distribution:")
    for lbl, cnt in df_all['best_route_label'].value_counts().sort_index().items():
        print(f"    {lbl} {LABEL_NAMES.get(lbl,'?'):<14}: {cnt} (%{cnt/len(df_all)*100:.1f})")

    def enforce_strict_labels(row):
        s = str(row['sql_query']).upper()
        if any(re.search(p, s, re.DOTALL) for p in HUMAN_P): return 4
        if any(re.search(p, s, re.DOTALL) for p in GEMINI_P): return 3
        if any(re.search(p, s, re.DOTALL) for p in SQLCODER_P): return 2
        return row['best_route_label']

    df_all['best_route_label'] = df_all.apply(enforce_strict_labels, axis=1)

    X = pd.DataFrame(df_all['sql_query'].apply(extract_features).tolist())
    X_original = X.copy()
    y = df_all['best_route_label'].astype(int)
    X, y = oversample_minority(X, y)

    feature_cols = list(X.columns)
    print(f"\n{'='*60}")
    print(f" MODEL COMPARISON — Stratified CV")
    print(f"{'='*60}")
    models = build_models()
    best_name, best_model, best_f1, cv_results = run_cv(models, X, y)

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    best_model.fit(X_tr, y_tr)
    y_pred   = best_model.predict(X_te)
    present  = sorted(y_te.unique())

    print(f"\n{'─'*60}")
    print(f"  Test Set ({len(X_te)} query) — {best_name}")
    print(f"{'─'*60}")
    print(classification_report(y_te, y_pred, labels=present,
          target_names=[LABEL_NAMES[l] for l in present], zero_division=0))

    cm = confusion_matrix(y_te, y_pred, labels=present)
    print("Confusion Matrix:")
    print(f"{'':>16}"+"".join(f"{LABEL_NAMES[l]:>13}" for l in present))
    for i,rl in enumerate(present):
        print(f"{LABEL_NAMES[rl]:>16}"+"".join(f"{cm[i,j]:>13}" for j in range(len(present))))
    best_model.fit(X, y)
    
    model_data = {
        'model':best_model,'feature_cols':feature_cols,
        'model_name':best_name,'cv_f1':best_f1,
        'cv_results':cv_results,'label_map':LABEL_NAMES,
        'note':f'{len(X)} real-labeled + SHAP',
    }
    with open(MODEL_OUTPUT,'wb') as f: pickle.dump(model_data, f)
    df_all['predicted_label'] = best_model.predict(X_original)
    df_all['correct'] = (df_all['best_route_label']==df_all['predicted_label']).astype(int)
    df_all.to_csv(REPORT_CSV, index=False)

    print(f"\n{'='*60}")
    print(f"Model          : {MODEL_OUTPUT}")
    print(f"Training report  : {REPORT_CSV}")
    print(f"{'='*60}")
    
if __name__ == "__main__":
    main()