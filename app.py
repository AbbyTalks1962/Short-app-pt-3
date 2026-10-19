import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(page_title="Equity Screening Lab", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.block-container {padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1700px;}
[data-testid="stMetric"] {background: #f6f8fb; border: 1px solid #e3e8ef; padding: 13px 15px; border-radius: 12px;}
h1,h2,h3 {letter-spacing:-0.025em;}
[data-testid="stSidebar"] {border-right: 1px solid #e8ebf0;}
[data-testid="stTabs"] button {font-weight: 600;}
</style>
""", unsafe_allow_html=True)

st.title("Equity Screening Lab")
st.caption("Fundamental stock screening · staged ranking · portfolio construction · buy / hold / sell signals")
st.markdown("**Live company universe**  ·  1,000-company target  ·  Adjustable filters  ·  Rank 1 = best")
MARGIN_COLS = [f"Margin_Tminus{i}" for i in range(7, 0, -1)] + ["Margin_T"]
BASE_REQUIRED = ["Company", "Ticker", "Sector", "Industry", "STA", "SNOA", "Z_Score", "GPA", "BTM", "CFOA"]

YAHOO_SOURCE = "Yahoo Finance via yfinance (unofficial research/education client)"


def _safe_div(a, b):
    return a / b if pd.notna(a) and pd.notna(b) and b != 0 else np.nan


def _statement_value(statement, row_names, fiscal_year=None):
    """Return a statement value for a fiscal year using tolerant Yahoo row-name matching."""
    if statement is None or getattr(statement, "empty", True):
        return np.nan
    lookup = {str(idx).strip().lower(): idx for idx in statement.index}
    actual_row = None
    for name in row_names:
        if name.lower() in lookup:
            actual_row = lookup[name.lower()]
            break
    if actual_row is None:
        # Tolerant match for small Yahoo line-item wording changes.
        for name in row_names:
            match = next((idx for idx in statement.index if name.lower() in str(idx).lower()), None)
            if match is not None:
                actual_row = match
                break
    if actual_row is None:
        return np.nan
    series = pd.to_numeric(statement.loc[actual_row], errors="coerce")
    if isinstance(series, pd.DataFrame):
        series = series.iloc[0]
    if fiscal_year is not None:
        for col in series.index:
            try:
                if pd.Timestamp(col).year == int(fiscal_year) and pd.notna(series[col]):
                    return float(series[col])
            except Exception:
                continue
        return np.nan
    series = series.dropna()
    return float(series.iloc[0]) if len(series) else np.nan


def _statement_years(*statements):
    years = set()
    for frame in statements:
        if frame is None or getattr(frame, "empty", True):
            continue
        for col in frame.columns:
            try:
                years.add(pd.Timestamp(col).year)
            except Exception:
                pass
    return sorted(years)


def _get_yahoo_universe(target_count, use_local_list=False):
    """Return real ticker symbols from the bundled company directory or Yahoo's screener."""
    if use_local_list:
        local_path = __import__("pathlib").Path(__file__).with_name("companies.csv")
        if not local_path.exists():
            raise RuntimeError("The bundled companies.csv file is missing. Keep it in the same folder as app.py.")
        local = pd.read_csv(local_path).dropna(subset=["Ticker"])
        local = local.drop_duplicates(subset=["Ticker"]).head(int(target_count))
        return [{"symbol": str(r["Ticker"]).strip(), "longName": str(r["Company"]),
                 "shortName": str(r["Company"]), "quoteType": "EQUITY",
                 "sector": str(r["Sector"]), "industry": str(r["Industry"])}
                for _, r in local.iterrows()]

    import yfinance as yf
    from yfinance import EquityQuery

    query = EquityQuery("and", [
        EquityQuery("eq", ["region", "us"]),
        EquityQuery("gt", ["intradaymarketcap", 500_000_000]),
    ])
    quotes = []
    offset = 0
    while len(quotes) < int(target_count):
        page_size = min(250, int(target_count) - len(quotes))
        response = yf.screen(query, offset=offset, size=page_size,
                             sortField="intradaymarketcap", sortAsc=False)
        page = response.get("quotes", []) if isinstance(response, dict) else []
        if not page:
            break
        quotes.extend(page)
        offset += len(page)
        if len(page) < page_size:
            break
    seen = set()
    clean = []
    for q in quotes:
        ticker = str(q.get("symbol", "")).strip().replace("$", "")
        if ticker and ticker not in seen and q.get("quoteType", "EQUITY") == "EQUITY":
            seen.add(ticker)
            q["symbol"] = ticker
            clean.append(q)
        if len(clean) >= int(target_count):
            break
    if not clean:
        raise RuntimeError("Yahoo Finance did not return any company symbols. Try again later; Yahoo may be rate-limiting requests.")
    return clean


def _load_one_yahoo_company(quote):
    """Download actual Yahoo annual statements and calculate the screen's available ratios."""
    import yfinance as yf
    ticker_symbol = quote["symbol"]
    stock = yf.Ticker(ticker_symbol)
    info = {}
    try:
        info = stock.get_info()
    except Exception:
        try:
            info = stock.info
        except Exception:
            info = {}
    info = info or {}
    try: income = stock.income_stmt
    except Exception: income = pd.DataFrame()
    try: balance = stock.balance_sheet
    except Exception: balance = pd.DataFrame()
    try: cashflow = stock.cashflow
    except Exception: cashflow = pd.DataFrame()

    years = _statement_years(income, balance, cashflow)
    if not years:
        return None
    # Yahoo often exposes only around four annual statement periods. Keep actual periods only.
    years = years[-8:]
    latest_year = max(years)
    values_by_year = {}
    for year in years:
        values_by_year[year] = {
            "assets": _statement_value(balance, ["Total Assets"], year),
            "liabilities": _statement_value(balance, ["Total Liabilities Net Minority Interest", "Total Liabilities"], year),
            "current_assets": _statement_value(balance, ["Current Assets", "Total Current Assets"], year),
            "current_liabilities": _statement_value(balance, ["Current Liabilities", "Total Current Liabilities"], year),
            "cash": _statement_value(balance, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash"], year),
            "current_debt": _statement_value(balance, ["Current Debt", "Current Debt And Capital Lease Obligation", "Current Debt And Lease Obligation"], year),
            "long_debt": _statement_value(balance, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt And Lease Obligation"], year),
            "equity": _statement_value(balance, ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"], year),
            "retained_earnings": _statement_value(balance, ["Retained Earnings"], year),
            "gross_profit": _statement_value(income, ["Gross Profit"], year),
            "revenue": _statement_value(income, ["Total Revenue", "Operating Revenue", "Revenue"], year),
            "net_income": _statement_value(income, ["Net Income", "Net Income Common Stockholders"], year),
            "ebit": _statement_value(income, ["EBIT", "Operating Income"], year),
            "ocf": _statement_value(cashflow, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Operating Cash Flow Continuing Operations"], year),
        }
    latest = values_by_year[latest_year]
    prev = values_by_year.get(latest_year - 1, {})
    assets = latest["assets"]
    avg_assets = np.nanmean([assets, prev.get("assets", np.nan)]) if pd.notna(assets) and pd.notna(prev.get("assets", np.nan)) else np.nan
    market_cap = info.get("marketCap", quote.get("marketCap", np.nan))
    if pd.isna(market_cap):
        market_cap = quote.get("intradaymarketcap", np.nan)
    liabilities = latest["liabilities"]
    wc = latest["current_assets"] - latest["current_liabilities"] if pd.notna(latest["current_assets"]) and pd.notna(latest["current_liabilities"]) else np.nan
    z_parts = [
        _safe_div(1.2 * wc, assets) if pd.notna(wc) else np.nan,
        _safe_div(1.4 * latest["retained_earnings"], assets),
        _safe_div(3.3 * latest["ebit"], assets),
        _safe_div(0.6 * market_cap, liabilities),
        _safe_div(latest["revenue"], assets),
    ]
    z_score = sum(z_parts) if all(pd.notna(x) for x in z_parts) else np.nan
    # SNOA needs both current and long-term debt figures; do not silently treat missing debt as zero.
    debt_fields = [latest["current_debt"], latest["long_debt"]]
    snoa = np.nan
    if pd.notna(assets) and assets != 0 and pd.notna(latest["cash"]) and pd.notna(liabilities) and all(pd.notna(x) for x in debt_fields):
        debt = sum(debt_fields)
        snoa = ((assets - latest["cash"]) - (liabilities - debt)) / assets
    row = {
        "Company": info.get("longName") or info.get("shortName") or quote.get("longName") or quote.get("shortName") or ticker_symbol,
        "Ticker": ticker_symbol,
        "Sector": info.get("sector") or quote.get("sector") or "Unknown",
        "Industry": info.get("industry") or quote.get("industry") or "Unknown",
        "STA": _safe_div(latest["net_income"] - latest["ocf"], avg_assets) if pd.notna(latest["net_income"]) and pd.notna(latest["ocf"]) else np.nan,
        "SNOA": snoa,
        "Z_Score": z_score,
        "GPA": _safe_div(latest["gross_profit"], assets),
        "BTM": _safe_div(latest["equity"], market_cap),
        "CFOA": _safe_div(latest["ocf"], assets),
        "MarketCap": market_cap,
        "FiscalYear": latest_year,
        "DataSource": "Yahoo Finance via yfinance",
        "DataDate": str(latest_year),
    }
    # Preserve eight fiscal-year slots for compatibility with the existing screening engine.
    for offset in range(7, -1, -1):
        y = latest_year - offset
        yr = values_by_year.get(y, {})
        gross_profit = yr.get("gross_profit", np.nan)
        revenue = yr.get("revenue", np.nan)
        margin = _safe_div(gross_profit, revenue)
        col = f"Margin_Tminus{offset}" if offset > 0 else "Margin_T"
        row[col] = margin
    return row


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def load_yahoo_finance_dataset(target_count=100, use_local_list=False):
    """Retrieve real companies from the bundled directory or Yahoo screener and calculate metrics from Yahoo annual statements."""
    quotes = _get_yahoo_universe(int(target_count), use_local_list=use_local_list)
    rows = []
    failures = []
    progress = st.progress(0, text="Loading Yahoo Finance statements…")
    total = len(quotes)
    for i, quote in enumerate(quotes, start=1):
        try:
            row = _load_one_yahoo_company(quote)
            if row is not None and row.get("Ticker"):
                rows.append(row)
            else:
                failures.append(quote.get("symbol", "unknown"))
        except Exception:
            failures.append(quote.get("symbol", "unknown"))
        if i % 5 == 0 or i == total:
            progress.progress(i / total, text=f"Retrieved statements for {i:,} of {total:,} companies…")
    progress.empty()
    if not rows:
        raise RuntimeError("Yahoo Finance returned tickers, but no annual statements could be read. Try fewer companies or retry later.")
    result = pd.DataFrame(rows).drop_duplicates("Ticker").reset_index(drop=True)
    result.attrs["requested_count"] = int(target_count)
    result.attrs["loaded_count"] = len(result)
    result.attrs["failed_tickers"] = failures
    result.attrs["dataset_note"] = (
        f"Yahoo Finance returned {len(result)} companies with readable annual statements; "
        f"{len(failures)} ticker(s) had missing/unavailable data. Yahoo's annual statement history is often limited, "
        "so MS/MG use only available annual gross-margin observations and should not be described as a full seven-year test unless eight fiscal years are present."
    )
    return result

def calculate_ms_mg(d):
    d = d.copy()
    cols = MARGIN_COLS
    if all(c in d.columns for c in cols):
        vals = d[cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        ms_values, mg_values, years_values = [], [], []
        for row in vals:
            valid_positions = np.flatnonzero(np.isfinite(row))
            years_values.append(len(valid_positions))
            growth = []
            for j in range(1, len(row)):
                # Only compare adjacent fiscal-year slots, and avoid division by zero.
                if np.isfinite(row[j-1]) and np.isfinite(row[j]) and row[j-1] > 0 and row[j] > 0:
                    growth.append(row[j] / row[j-1] - 1)
            if len(growth) >= 2:
                sd = float(np.std(growth, ddof=1))
                ms_values.append(float(np.mean(growth) / sd) if sd > 0 else np.nan)
            else:
                ms_values.append(np.nan)
            if len(valid_positions) >= 2:
                first, last = int(valid_positions[0]), int(valid_positions[-1])
                start, end = row[first], row[last]
                periods = last - first
                mg_values.append(float((end / start) ** (1 / periods) - 1) if start > 0 and end > 0 and periods > 0 else np.nan)
            else:
                mg_values.append(np.nan)
        d["MS"] = ms_values
        d["MG"] = mg_values
        d["Margin_Years_Available"] = years_values
    else:
        for c in ["MS", "MG"]:
            if c not in d: d[c] = np.nan
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d

def rank_series(s, high_good=False):
    # rank 1 = best; missing values are placed after valid observations
    return s.rank(method="average", ascending=high_good is False, na_option="bottom")

def safe_demean(frame, cols, enabled):
    frame = frame.copy()
    for col in cols:
        if col not in frame: continue
        adj = f"{col}_Adjusted"
        if enabled:
            frame[adj] = frame[col] - frame.groupby("Industry")[col].transform("mean")
        else:
            frame[adj] = frame[col]
    return frame

def weighted_rank_score(frame, rank_cols, weights):
    score = pd.Series(0.0, index=frame.index)
    total_weight = 0.0
    for col in rank_cols:
        w = float(weights.get(col.replace("R_", ""), 1.0))
        if w > 0:
            score += frame[col].fillna(frame[col].max() if frame[col].notna().any() else 0) * w
            total_weight += w
    return score / total_weight if total_weight else score

def run_screen(data, cuts, demean_flags, weights):
    d = calculate_ms_mg(data.copy())
    missing = [c for c in BASE_REQUIRED if c not in d.columns]
    if missing: raise ValueError("Missing required columns: " + ", ".join(missing))
    d = d.dropna(subset=["Company", "Ticker", "Sector", "Industry"]).drop_duplicates("Ticker").reset_index(drop=True)
    numeric = ["STA", "SNOA", "Z_Score", "MS", "MG", "GPA", "BTM", "CFOA"]
    for c in numeric: d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in MARGIN_COLS:
        if c in d: d[c] = pd.to_numeric(d[c], errors="coerce")
    d["Disposition"] = "Survived all stages"
    stage_snapshots = {}
    removed_by_stage = {}

    def stage_rank(frame, metric_defs, demean, stage_num):
        x = safe_demean(frame, [m for m, _ in metric_defs], demean)
        rank_cols, metric_weights = [], {}
        for metric, high_good in metric_defs:
            source = f"{metric}_Adjusted" if demean else metric
            rcol = f"R_{metric}"
            x[rcol] = rank_series(x[source], high_good=high_good)
            rank_cols.append(rcol)
            metric_weights[metric] = weights.get(metric, 1.0)
        # Display an independent score/rank for the current stage.
        x[f"Stage{stage_num}_WeightedScore"] = weighted_rank_score(x, rank_cols, metric_weights)
        x[f"Stage{stage_num}_Rank"] = x[f"Stage{stage_num}_WeightedScore"].rank(method="min", ascending=True, na_option="bottom")
        return x, rank_cols

    def eliminate(frame, pct, score_col, stage_label):
        n = int(np.ceil(len(frame) * pct / 100)) if pct > 0 else 0
        order = frame.sort_values([score_col, "Ticker"], ascending=[False, True], na_position="first")
        removed = order.head(n)["Ticker"].tolist()
        kept = frame[~frame["Ticker"].isin(removed)].copy()
        return kept, removed

    # Stage 1: financial safety
    x1, r1 = stage_rank(d, [("STA", False), ("SNOA", False), ("Z_Score", True)], demean_flags[1], 1)
    x1["Stage1_CombinedScore"] = x1["Stage1_WeightedScore"]
    s1, removed1 = eliminate(x1, cuts[1], "Stage1_CombinedScore", "Stage 1")
    stage_snapshots["Stage 1"] = x1.copy(); removed_by_stage["Stage 1"] = removed1

    # Refresh all earlier ranks on the current survivor population before Stage 2.
    s1, r1 = stage_rank(s1, [("STA", False), ("SNOA", False), ("Z_Score", True)], demean_flags[1], 1)
    # Stage 2: show MS and MG ranks separately; MM is max of their within-population percentiles.
    x2 = safe_demean(s1, ["MS", "MG"], demean_flags[2])
    x2["R_MS"] = rank_series(x2["MS_Adjusted"] if demean_flags[2] else x2["MS"], high_good=True)
    x2["R_MG"] = rank_series(x2["MG_Adjusted"] if demean_flags[2] else x2["MG"], high_good=True)
    x2["MS_Percentile"] = (x2["R_MS"].max() - x2["R_MS"] + 1) / max(1, len(x2))
    x2["MG_Percentile"] = (x2["R_MG"].max() - x2["R_MG"] + 1) / max(1, len(x2))
    x2["MM"] = x2[["MS_Percentile", "MG_Percentile"]].max(axis=1, skipna=True)
    x2["R_MM"] = rank_series(x2["MM"], high_good=True)
    # weighted stage score uses the component ranks; MM is retained as the specified summary metric.
    wms, wmg = weights.get("MS", 1.0), weights.get("MG", 1.0)
    denom = wms + wmg
    x2["Stage2_MarginScore"] = ((x2["R_MS"] * wms + x2["R_MG"] * wmg) / denom) if denom else x2["R_MM"]
    x2["Stage2_CombinedScore"] = x2["Stage1_Rank"] + x2["Stage2_MarginScore"]
    x2["Stage2_Rank"] = x2["Stage2_CombinedScore"].rank(method="min", ascending=True, na_option="bottom")
    s2, removed2 = eliminate(x2, cuts[2], "Stage2_CombinedScore", "Stage 2")
    stage_snapshots["Stage 2"] = x2.copy(); removed_by_stage["Stage 2"] = removed2

    # Recalculate stages 1 and 2 ranks for the current population before Stage 3.
    s2, _ = stage_rank(s2, [("STA", False), ("SNOA", False), ("Z_Score", True)], demean_flags[1], 1)
    s2 = safe_demean(s2, ["MS", "MG"], demean_flags[2])
    s2["R_MS"] = rank_series(s2["MS_Adjusted"] if demean_flags[2] else s2["MS"], high_good=True)
    s2["R_MG"] = rank_series(s2["MG_Adjusted"] if demean_flags[2] else s2["MG"], high_good=True)
    s2["MS_Percentile"] = (s2["R_MS"].max() - s2["R_MS"] + 1) / max(1, len(s2))
    s2["MG_Percentile"] = (s2["R_MG"].max() - s2["R_MG"] + 1) / max(1, len(s2))
    s2["MM"] = s2[["MS_Percentile", "MG_Percentile"]].max(axis=1, skipna=True)
    s2["R_MM"] = rank_series(s2["MM"], high_good=True)
    denom = weights.get("MS", 1.0) + weights.get("MG", 1.0)
    s2["Stage2_MarginScore"] = ((s2["R_MS"] * weights.get("MS", 1.0) + s2["R_MG"] * weights.get("MG", 1.0)) / denom) if denom else s2["R_MM"]
    s2["Stage2_CombinedScore"] = s2["Stage1_Rank"] + s2["Stage2_MarginScore"]
    s2["Stage2_Rank"] = s2["Stage2_CombinedScore"].rank(method="min", ascending=True, na_option="bottom")

    # Stage 3: profitability/valuation metrics
    x3, r3 = stage_rank(s2, [("GPA", True), ("BTM", True), ("CFOA", True)], demean_flags[3], 3)
    x3["Stage3_CombinedScore"] = x3["Stage2_CombinedScore"] + x3["Stage3_WeightedScore"]
    x3["Stage3_Rank"] = x3["Stage3_CombinedScore"].rank(method="min", ascending=True, na_option="bottom")
    s3, removed3 = eliminate(x3, cuts[3], "Stage3_CombinedScore", "Stage 3")
    stage_snapshots["Stage 3"] = x3.copy(); removed_by_stage["Stage 3"] = removed3

    # Build complete audit/disposition.
    audit = d.copy()
    for stage, ids in removed_by_stage.items():
        audit.loc[audit["Ticker"].isin(ids), "Disposition"] = f"Eliminated at {stage}"
    # Final survivor ranks are refreshed on the final population for presentation.
    if len(s3):
        s3, _ = stage_rank(s3, [("STA", False), ("SNOA", False), ("Z_Score", True)], demean_flags[1], 1)
        s3 = safe_demean(s3, ["MS", "MG"], demean_flags[2])
        s3["R_MS"] = rank_series(s3["MS_Adjusted"] if demean_flags[2] else s3["MS"], high_good=True)
        s3["R_MG"] = rank_series(s3["MG_Adjusted"] if demean_flags[2] else s3["MG"], high_good=True)
        s3["MS_Percentile"] = (s3["R_MS"].max() - s3["R_MS"] + 1) / max(1, len(s3))
        s3["MG_Percentile"] = (s3["R_MG"].max() - s3["R_MG"] + 1) / max(1, len(s3))
        s3["MM"] = s3[["MS_Percentile", "MG_Percentile"]].max(axis=1, skipna=True)
        s3["R_MM"] = rank_series(s3["MM"], high_good=True)
        denom = weights.get("MS", 1.0) + weights.get("MG", 1.0)
        s3["Stage2_MarginScore"] = ((s3["R_MS"] * weights.get("MS", 1.0) + s3["R_MG"] * weights.get("MG", 1.0)) / denom) if denom else s3["R_MM"]
        s3["Stage2_CombinedScore"] = s3["Stage1_Rank"] + s3["Stage2_MarginScore"]
        s3["Stage2_Rank"] = s3["Stage2_CombinedScore"].rank(method="min", ascending=True, na_option="bottom")
        s3, _ = stage_rank(s3, [("GPA", True), ("BTM", True), ("CFOA", True)], demean_flags[3], 3)
        s3["Stage3_CombinedScore"] = s3["Stage2_CombinedScore"] + s3["Stage3_WeightedScore"]
        s3["Final_Rank"] = s3["Stage3_CombinedScore"].rank(method="min", ascending=True, na_option="bottom")
        s3 = s3.sort_values(["Final_Rank", "Ticker"])
    return d, stage_snapshots, s1, s2, s3, audit, removed_by_stage

with st.sidebar:
    st.header("Screen settings")
    st.caption("Elimination percentages apply sequentially to the surviving population.")
    cuts = {1: st.slider("Stage 1 elimination (%)", 0, 50, 10, 5), 2: st.slider("Stage 2 elimination (%)", 0, 50, 10, 5), 3: st.slider("Stage 3 elimination (%)", 0, 50, 10, 5)}
    st.divider()
    st.subheader("Industry demeaning")
    demean_flags = {
        1: st.checkbox("Demean Stage 1 ratios by industry", True),
        2: st.checkbox("Demean Stage 2 ratios by industry", False),
        3: st.checkbox("Demean Stage 3 ratios by industry", False),
    }
    st.caption("Demeaning subtracts the current population's industry mean from each selected ratio before ranking.")
    st.divider()
    st.subheader("Ratio weights")
    st.caption("Set each ratio's relative importance. A weight of 0 excludes it from the weighted score.")
    weights = {}
    for metric, default in [("STA",1.0),("SNOA",1.0),("Z_Score",1.0),("MS",1.0),("MG",1.0),("GPA",1.0),("BTM",1.0),("CFOA",1.0)]:
        weights[metric] = st.slider(f"{metric} weight", 0.0, 5.0, default, 0.25, key=f"weight_{metric}")
    st.divider()
    st.subheader("Live company data")
    st.caption("Company names and reported financial statements are retrieved online when the app opens. No large SEC file or company CSV needs to be uploaded.")
    target_count = st.number_input("Target number of companies", min_value=25, max_value=1000, value=1000, step=25)
    st.session_state["target_count"] = int(target_count)
    fetch_yahoo = st.button("↻ Refresh live company data", type="primary", use_container_width=True)
    st.caption("The first visit may take several minutes. Yahoo Finance can rate-limit requests, and some companies may not report every required item. Successful data is cached for 12 hours when the app process remains available.")

# Load automatically on the first visit. The refresh button is only needed to request a new dataset.
should_load = fetch_yahoo or ("real_company_data" not in st.session_state)
if should_load:
    try:
        with st.spinner(f"Loading real company statements for up to {int(target_count):,} companies. The first load can take several minutes…"):
            data = load_yahoo_finance_dataset(int(target_count), use_local_list=False)
        data_source = "Yahoo Finance / yfinance annual statements (retrieved at runtime)"
        st.session_state["real_company_data"] = data
        st.session_state["real_company_source"] = data_source
        st.session_state["real_company_note"] = data.attrs.get("dataset_note", "")
        st.session_state["real_company_failures"] = data.attrs.get("failed_tickers", [])
    except Exception as e:
        st.error(f"Could not load live company data: {e}")
        st.warning("This app does not use simulated financial figures. If the provider is temporarily rate-limiting requests, wait and refresh, or temporarily lower the target count in the sidebar.")
        st.stop()
else:
    data = st.session_state["real_company_data"].copy()
    data_source = st.session_state.get("real_company_source", "Yahoo Finance data")

# Interactive filters are applied BEFORE the ranking process so all rankings and elimination cutoffs
# are recalculated on the selected universe, rather than merely hiding rows after ranking.
st.subheader("Filter the company universe")
st.caption("Choose filters before screening. All three stages rerun on the filtered population.")
filt_cols = st.columns([1.15, 1.15, 1.25, 1.45])
filter_data = data.copy()
sector_values = sorted(filter_data["Sector"].dropna().astype(str).unique().tolist()) if "Sector" in filter_data else []
industry_values = sorted(filter_data["Industry"].dropna().astype(str).unique().tolist()) if "Industry" in filter_data else []
selected_sectors = filt_cols[0].multiselect("Sector", sector_values, default=sector_values, key="universe_sector_filter")
industry_options = sorted(filter_data[filter_data["Sector"].astype(str).isin(selected_sectors)]["Industry"].dropna().astype(str).unique().tolist()) if selected_sectors and "Industry" in filter_data else industry_values
selected_industries = filt_cols[1].multiselect("Industry", industry_options, default=industry_options, key="universe_industry_filter")
search_term = filt_cols[2].text_input("Company / ticker search", placeholder="e.g., Adobe or ADBE", key="universe_search_filter")
market_cap_min = 0.0
if "MarketCap" in filter_data and pd.to_numeric(filter_data["MarketCap"], errors="coerce").notna().any():
    cap_options = {"Any market cap": 0.0, "$500M+": 500_000_000.0, "$1B+": 1_000_000_000.0, "$5B+": 5_000_000_000.0, "$10B+": 10_000_000_000.0}
    selected_cap = filt_cols[3].selectbox("Minimum market cap", list(cap_options), index=0, key="universe_cap_filter")
    market_cap_min = cap_options[selected_cap]
else:
    filt_cols[3].selectbox("Minimum market cap", ["Unavailable in source data"], disabled=True, key="universe_cap_filter_disabled")
if selected_sectors:
    filter_data = filter_data[filter_data["Sector"].astype(str).isin(selected_sectors)]
else:
    filter_data = filter_data.iloc[0:0]
if selected_industries:
    filter_data = filter_data[filter_data["Industry"].astype(str).isin(selected_industries)]
else:
    filter_data = filter_data.iloc[0:0]
if search_term.strip():
    mask = filter_data["Company"].astype(str).str.contains(search_term.strip(), case=False, na=False) | filter_data["Ticker"].astype(str).str.contains(search_term.strip(), case=False, na=False)
    filter_data = filter_data[mask]
if market_cap_min and "MarketCap" in filter_data:
    filter_data = filter_data[pd.to_numeric(filter_data["MarketCap"], errors="coerce") >= market_cap_min]
st.caption(f"Universe filter: **{len(filter_data):,} of {len(data):,}** loaded companies selected for ranking.")
if filter_data.empty:
    st.warning("No companies match the selected filters. Widen the filters to continue.")
    st.stop()
data = filter_data.copy()

try:
    original, snapshots, s1, s2, final_stage, audit, removed = run_screen(data, cuts, demean_flags, weights)
except Exception as e:
    st.error(f"Could not run the screen: {e}")
    st.info("Required columns: Company, Ticker, Sector, Industry, STA, SNOA, Z_Score, GPA, BTM, CFOA, plus eight annual margin columns (Margin_Tminus7 through Margin_T) or pre-calculated MS and MG.")
    st.stop()

n0 = len(original); n1 = n0 - len(removed["Stage 1"]); n2 = n1 - len(removed["Stage 2"]); n3 = len(final_stage)
a,b,c,dcol = st.columns(4)
a.metric("Starting companies", f"{n0:,}")
b.metric("After Stage 1", f"{n1:,}", delta=f"-{len(removed['Stage 1'])} removed")
c.metric("After Stage 2", f"{n2:,}", delta=f"-{len(removed['Stage 2'])} removed")
dcol.metric("Final survivors", f"{n3:,}", delta=f"-{len(removed['Stage 3'])} removed")
st.caption(f"Data: {data_source} · Rank 1 is best · All ratios are displayed individually in the stage tables.")
if "Yahoo Finance" in data_source:
    st.warning("Yahoo's annual statement history is often shorter than the requested seven-year margin window. MS/MG are calculated from available consecutive positive gross-margin observations; check Margin_Years_Available before describing them as seven-year metrics. Missing financial values are left blank, not invented.")
    note = st.session_state.get("real_company_note", "")
    if note:
        st.caption(note)
    failures = st.session_state.get("real_company_failures", [])
    if failures:
        with st.expander(f"Tickers with unavailable statements ({len(failures)})"):
            st.write(", ".join(failures[:200]))

# Portfolio allocation targets by industry, equal weights by default.
st.header("Portfolio construction")
st.caption("Industry targets start equally weighted. Edit the target weights to tilt toward or away from particular industries; weights are normalized to 100%.")
if n3:
    industries = sorted(final_stage["Industry"].dropna().unique().tolist())
    default_weight = 100.0 / max(1, len(industries))
    target_df = pd.DataFrame({"Industry": industries, "Target_Weight_%": [default_weight] * len(industries)})
    edited_targets = st.data_editor(target_df, use_container_width=True, hide_index=True, key="industry_targets", column_config={"Industry": st.column_config.TextColumn(disabled=True), "Target_Weight_%": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=1.0, format="%.2f%%")})
    total_target = edited_targets["Target_Weight_%"].sum()
    if total_target <= 0:
        st.warning("Set at least one industry target above zero to calculate portfolio weights.")
        final_stage["Portfolio_Weight"] = 0.0
    else:
        target_map = (edited_targets.set_index("Industry")["Target_Weight_%"] / total_target).to_dict()
        counts = final_stage.groupby("Industry")["Ticker"].transform("count")
        final_stage["Industry_Target_Weight"] = final_stage["Industry"].map(target_map).fillna(0.0)
        final_stage["Portfolio_Weight"] = final_stage["Industry_Target_Weight"] / counts
    alloc = final_stage.groupby("Industry", as_index=False).agg(Companies=("Ticker", "count"), Target_Weight=("Industry_Target_Weight", "first"), Actual_Weight=("Portfolio_Weight", "sum"))
    alloc["Target_Weight"] = (alloc["Target_Weight"] * 100).round(2)
    alloc["Actual_Weight"] = (alloc["Actual_Weight"] * 100).round(2)
    left,right = st.columns([1,1])
    with left: st.dataframe(alloc.sort_values("Actual_Weight", ascending=False), use_container_width=True, hide_index=True)
    with right:
        fig = px.bar(alloc, x="Industry", y="Actual_Weight", title="Final portfolio weight by industry", hover_data=["Companies", "Target_Weight"])
        fig.update_layout(xaxis_title="", yaxis_title="Portfolio weight (%)")
        st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("No companies survived. Reduce one or more elimination percentages.")

tabs = st.tabs(["Overview", "Stage 1 — Safety", "Stage 2 — Margins", "Stage 3 — Profitability", "Final portfolio", "Buy / Sell", "Company database", "Methodology & data"])
with tabs[0]:
    l,r = st.columns(2)
    with l:
        st.subheader("Survivors by sector")
        if n3:
            sc = final_stage["Sector"].value_counts().rename_axis("Sector").reset_index(name="Companies")
            st.plotly_chart(px.bar(sc, x="Sector", y="Companies", color="Sector"), use_container_width=True)
    with r:
        funnel = pd.DataFrame({"Stage":["Starting universe","After Stage 1","After Stage 2","Final survivors"],"Companies":[n0,n1,n2,n3]})
        st.plotly_chart(px.funnel(funnel, x="Companies", y="Stage"), use_container_width=True)
    st.subheader("Top final survivors")
    if n3:
        showcols = [c for c in ["Final_Rank","Company","Ticker","Sector","Industry","R_STA","R_SNOA","R_Z_Score","R_MS","R_MG","MM","R_GPA","R_BTM","R_CFOA","Stage3_CombinedScore","Portfolio_Weight"] if c in final_stage]
        st.dataframe(final_stage[showcols].head(25), use_container_width=True, hide_index=True)

with tabs[1]:
    st.subheader("Stage 1 — Financial safety")
    st.markdown("STA and SNOA: lower is better. Z-score: higher is better. Toggle industry demeaning and ratio weights in the sidebar.")
    t = snapshots["Stage 1"]
    cols = [c for c in ["Company","Ticker","Sector","Industry","STA","STA_Adjusted","R_STA","SNOA","SNOA_Adjusted","R_SNOA","Z_Score","Z_Score_Adjusted","R_Z_Score","Stage1_WeightedScore","Stage1_Rank"] if c in t]
    st.dataframe(t[cols].sort_values("Stage1_Rank"), use_container_width=True, hide_index=True)
    st.download_button("Download Stage 1 table", t[cols].to_csv(index=False).encode(), "stage1_safety.csv", "text/csv")
    st.subheader("Stage 1 eliminated")
    st.dataframe(t[t["Ticker"].isin(removed["Stage 1"])][cols], use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("Stage 2 — Margin of safety and growth")
    st.markdown("MS = average annual growth in margin divided by the sample standard deviation of annual margin growth. MG = seven-year geometric annualized margin growth. MM = max(percentile(MS), percentile(MG)). Higher is treated as better.")
    t = snapshots["Stage 2"]
    cols = [c for c in ["Company","Ticker","Sector","Industry","MS","MS_Adjusted","R_MS","MS_Percentile","MG","MG_Adjusted","R_MG","MG_Percentile","MM","R_MM","Stage1_Rank","Stage2_MarginScore","Stage2_CombinedScore","Stage2_Rank"] if c in t]
    st.dataframe(t[cols].sort_values("Stage2_Rank"), use_container_width=True, hide_index=True)
    st.download_button("Download Stage 2 table", t[cols].to_csv(index=False).encode(), "stage2_margins.csv", "text/csv")
    st.subheader("Stage 2 eliminated")
    st.dataframe(t[t["Ticker"].isin(removed["Stage 2"])][cols], use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("Stage 3 — Profitability and valuation")
    st.markdown("GPA, BTM and CFOA are shown separately. Current default: higher values rank better for all three; confirm the BTM direction against your course methodology.")
    t = snapshots["Stage 3"]
    cols = [c for c in ["Company","Ticker","Sector","Industry","GPA","GPA_Adjusted","R_GPA","BTM","BTM_Adjusted","R_BTM","CFOA","CFOA_Adjusted","R_CFOA","Stage2_CombinedScore","Stage3_WeightedScore","Stage3_CombinedScore","Stage3_Rank"] if c in t]
    st.dataframe(t[cols].sort_values("Stage3_Rank"), use_container_width=True, hide_index=True)
    st.download_button("Download Stage 3 table", t[cols].to_csv(index=False).encode(), "stage3_profitability.csv", "text/csv")
    st.subheader("Stage 3 eliminated")
    st.dataframe(t[t["Ticker"].isin(removed["Stage 3"])][cols], use_container_width=True, hide_index=True)

with tabs[4]:
    st.subheader("Final portfolio")
    if n3:
        st.metric("Total portfolio weight", f"{final_stage['Portfolio_Weight'].sum()*100:.2f}%")
        cols = [c for c in ["Final_Rank","Company","Ticker","Sector","Industry","STA","SNOA","Z_Score","MS","MG","MM","GPA","BTM","CFOA","R_STA","R_SNOA","R_Z_Score","R_MS","R_MG","R_GPA","R_BTM","R_CFOA","Portfolio_Weight"] if c in final_stage]
        st.dataframe(final_stage[cols], use_container_width=True, hide_index=True)
        st.download_button("Download final portfolio CSV", final_stage[cols].to_csv(index=False).encode(), "final_portfolio.csv", "text/csv")
    else: st.info("No survivors under the current settings.")
    st.caption("Portfolio weights are mathematical allocations for coursework, not investment advice.")

with tabs[5]:
    st.subheader("Portfolio-linked buy / hold / sell signals")
    st.markdown("Signals are calculated **from the companies that survive all three screening stages**. The score combines final cumulative rank, the portfolio allocation weight, and optional risk flags. This is a coursework classification, not investment advice.")
    buy_col, sell_col, risk_col = st.columns(3)
    buy_pct = buy_col.slider("BUY: top % of survivors", 1, 50, 20, 1, key="trade_buy_pct")
    sell_pct = sell_col.slider("SELL: bottom % of survivors", 1, 50, 20, 1, key="trade_sell_pct")
    risk_guard = risk_col.checkbox("Flag weak Z-score / GPA / BTM", value=True, key="trade_risk_guard")
    if buy_pct + sell_pct > 90:
        st.warning("BUY and SELL percentages total more than 90%; HOLD will be a small or empty group.")
    if n3:
        trade = final_stage.copy()
        trade["Portfolio_Weight_Pct"] = pd.to_numeric(trade.get("Portfolio_Weight", 0), errors="coerce").fillna(0) * 100
        # Final_Rank is already the cumulative rank across all three stages (rank 1 = best).
        trade["Overall_Rank_Percentile"] = trade["Final_Rank"].rank(pct=True, ascending=False)
        # Normalize portfolio allocation within the surviving population for display and score.
        max_weight = trade["Portfolio_Weight_Pct"].max()
        trade["Portfolio_Weight_Score"] = trade["Portfolio_Weight_Pct"] / max_weight if pd.notna(max_weight) and max_weight > 0 else 0.0
        trade["Buy_Quality_Score"] = (0.70 * (1 - trade["Final_Rank"].rank(pct=True, ascending=True)) + 0.30 * trade["Portfolio_Weight_Score"])
        trade["Sell_Risk_Score"] = 0.0
        risk_cols = []
        for metric, high_good in [("Z_Score", True), ("GPA", True), ("BTM", True)]:
            if metric in trade and pd.to_numeric(trade[metric], errors="coerce").notna().any():
                q20 = pd.to_numeric(trade[metric], errors="coerce").quantile(0.20)
                flag = f"Weak_{metric}"
                trade[flag] = pd.to_numeric(trade[metric], errors="coerce").isna() | (pd.to_numeric(trade[metric], errors="coerce") <= q20)
                risk_cols.append(flag)
        trade["Risk_Flag"] = trade[risk_cols].any(axis=1) if risk_cols else False
        n_buy = max(1, int(np.ceil(len(trade) * buy_pct / 100)))
        n_sell = max(1, int(np.ceil(len(trade) * sell_pct / 100)))
        buy_set = set(trade.nlargest(n_buy, "Buy_Quality_Score")["Ticker"])
        sell_candidates = trade[~trade["Ticker"].isin(buy_set)].copy()
        if risk_guard and "Risk_Flag" in sell_candidates and sell_candidates["Risk_Flag"].any():
            # Risk-flagged names are prioritized for SELL, but preserve the adjustable sell bucket size.
            risk_first = sell_candidates.sort_values(["Risk_Flag", "Final_Rank"], ascending=[False, False])
        else:
            risk_first = sell_candidates.sort_values("Final_Rank", ascending=False)
        sell_set = set(risk_first.head(min(n_sell, len(sell_candidates)))["Ticker"])
        trade["Signal"] = np.select([trade["Ticker"].isin(buy_set), trade["Ticker"].isin(sell_set)], ["BUY", "SELL"], default="HOLD")
        trade["Signal_Reason"] = np.select(
            [trade["Signal"].eq("BUY"), trade["Signal"].eq("SELL") & trade["Risk_Flag"], trade["Signal"].eq("SELL")],
            ["Strong cumulative rank / portfolio fit", "Weak risk or profitability metric", "Lower cumulative rank within survivors"],
            default="Middle-ranked survivor")
        buy_count = int((trade["Signal"] == "BUY").sum())
        hold_count = int((trade["Signal"] == "HOLD").sum())
        sell_count = int((trade["Signal"] == "SELL").sum())
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("BUY", f"{buy_count:,}")
        m2.metric("HOLD", f"{hold_count:,}")
        m3.metric("SELL", f"{sell_count:,}")
        m4.metric("Portfolio weight in BUY names", f"{trade.loc[trade['Signal'].eq('BUY'), 'Portfolio_Weight_Pct'].sum():.1f}%")
        signal_filter = st.radio("Show signals", ["All", "BUY", "HOLD", "SELL"], horizontal=True, key="signal_view")
        shown = trade if signal_filter == "All" else trade[trade["Signal"] == signal_filter]
        show = ["Signal", "Final_Rank", "Company", "Ticker", "Sector", "Industry", "Portfolio_Weight_Pct", "Buy_Quality_Score", "Risk_Flag", "Signal_Reason", "STA", "SNOA", "Z_Score", "MS", "MG", "MM", "GPA", "BTM", "CFOA"]
        show = [c for c in show if c in trade.columns]
        st.dataframe(shown[show].sort_values("Final_Rank"), use_container_width=True, hide_index=True)
        st.download_button("Download buy / hold / sell signals", trade[show].to_csv(index=False).encode(), "buy_hold_sell_signals.csv", "text/csv")
        st.subheader("Signal distribution")
        signal_counts = trade["Signal"].value_counts().reindex(["BUY", "HOLD", "SELL"], fill_value=0).rename_axis("Signal").reset_index(name="Companies")
        st.plotly_chart(px.bar(signal_counts, x="Signal", y="Companies", color="Signal", title="Signals among final portfolio candidates"), use_container_width=True)
        st.caption("The signal is a relative screen within the final survivors. A BUY label does not guarantee positive returns; a SELL label is not a prediction of a price decline.")
    else:
        st.info("No final portfolio companies are available to evaluate.")

with tabs[6]:
    st.subheader("Filtered company database")
    st.caption("This table shows the universe currently selected by the filters above, before stage eliminations.")
    f1,f2 = st.columns(2)
    sectors = sorted(original["Sector"].dropna().unique().tolist())
    selected = f1.selectbox("Filter sector", ["All sectors"] + sectors)
    search = f2.text_input("Search company or ticker")
    view = original.copy()
    if selected != "All sectors": view = view[view["Sector"] == selected]
    if search: view = view[view["Company"].astype(str).str.contains(search, case=False, na=False) | view["Ticker"].astype(str).str.contains(search, case=False, na=False)]
    st.write(f"{len(view):,} companies shown")
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.download_button("Download company database CSV", original.to_csv(index=False).encode(), "company_universe.csv", "text/csv")

with tabs[7]:
    st.subheader("Methodology and data requirements")
    st.markdown("""
**Data source:** Yahoo Finance company screener and annual financial statements accessed at runtime through the unofficial `yfinance` Python library. The project does not bundle a large SEC/company-facts file, does not require a company dataset upload, and does not create demo companies. `yfinance` is an independent open-source client, not an official Yahoo Finance API. Check provider terms and use only as permitted for coursework.

**Important source limitations:** Yahoo statement coverage varies by ticker and often exposes only a few annual periods. The app calculates Altman Z and BTM only when the required actual inputs are available, and SNOA only when both current and long-term debt are available. Missing values are left blank rather than invented. Financial firms may not be comparable under the standard Altman Z formula.

**Industry demeaning:** optional independently for each stage. When enabled, each ratio is adjusted by subtracting its industry mean among the population being ranked at that stage.

**Seven-year window:** the original method requires eight annual margin observations (T−7 through T). Yahoo may not supply eight years. The app retains eight fiscal-year slots but calculates MS/MG only from available consecutive positive gross-margin observations; check `Margin_Years_Available` and do not call a shorter history a full seven-year result.

**MS:** arithmetic average of annual margin growth rates divided by their sample standard deviation.

**MG:** annualized geometric growth in margin using the first and last available positive margin and the actual number of fiscal-year intervals between them. This is only a seven-year rate when eight annual observations are present.

**MM:** `max(percentile(MS), percentile(MG))`. MS and MG are also displayed and weighted separately so the analyst can control their contribution.

**Portfolio allocation:** initial target weights are equal across the industries represented among final survivors. Edit the target percentage by industry; the app normalizes all nonzero targets to 100%, then allocates each industry's target equally among that industry's surviving companies.

**Runtime data:** The Yahoo connector discovers tickers and calculates available metrics from retrieved annual statements. An optional CSV upload is supported, but it is not required. Missing data are left blank; the app does not fabricate values to force every company to pass.

**Ratio direction defaults:** STA and SNOA lower is better; Z-score higher is better; MS/MG/MM higher is better; GPA, BTM, and CFOA higher is better for the screening stage. The trade decision stage separately treats lower Z-score, GPA, and BTM as sell signals. Confirm course definitions. The standard Altman Z formula is not equally suitable for every sector, particularly financial firms.
""")
    template = pd.DataFrame(columns=BASE_REQUIRED + MARGIN_COLS)
    st.download_button("Download real-data CSV template", template.to_csv(index=False).encode(), "company_data_template.csv", "text/csv")
    st.warning("No demo-company data is included. Only actual Yahoo Finance statement data or uploaded real-company data are screened.")

st.divider()
st.caption("Educational analysis tool only. Check formula definitions, fiscal-year alignment, missing data and data-provider licensing before relying on results.")
