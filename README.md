# Equity Screening Lab

An interactive Streamlit coursework app for staged financial-ratio screening, adjustable universe filters, portfolio construction, and portfolio-linked BUY / HOLD / SELL signals.

## Real company data without uploading a dataset

The app discovers real listed-company tickers from Yahoo Finance at runtime and requests available annual income statements, balance sheets, cash-flow statements, market capitalization, sector and industry data through the `yfinance` Python library. There is no bundled SEC company-facts file and no company CSV is required. No company-data upload is required.

On the first visit, the app automatically attempts to load up to **1,000 companies**. The sidebar includes a refresh button and lets you lower the target count if the provider rate-limits requests. The app caches successfully loaded results for 12 hours. Large live pulls can take several minutes or fail temporarily because Yahoo Finance is an unofficial source accessed through `yfinance`; no app can guarantee that Yahoo will serve 1,000 full statements on every run.

**Real-data caveat:** the ticker universe is real, but financial statement coverage varies by company. Missing ratios are left blank rather than invented. Yahoo often supplies fewer than eight annual gross-margin observations, so the app displays `Margin_Years_Available`; MS/MG should only be described as a full seven-year calculation when eight annual observations are present. The standard Altman Z-score is not equally appropriate for every industry, especially financial firms.

## Main features

- Target universe of 25–1,000 live-discovered public companies.
- Filters by sector, industry, company/ticker search and minimum market capitalization; filters are applied **before** ranking.
- Stage 1: STA, SNOA and Altman Z-score.
- Stage 2: seven-year MS, geometric MG and MM = max(percentile(MS), percentile(MG)), using available actual history and clearly indicating coverage.
- Stage 3: GPA, BTM and CFOA.
- Adjustable elimination rates at each stage, industry demeaning and ratio weights.
- Re-ranking of the surviving population as screening proceeds.
- Industry-based portfolio allocation, initially equally weighted across industries, with adjustable industry targets.
- Portfolio-linked BUY / HOLD / SELL labels with adjustable bucket sizes, risk flags and downloadable results.
- CSV exports for stage rankings, company universe, final portfolio and trade signals.

## Run locally

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Upload `app.py`, `requirements.txt`, and `README.md` to the root of your GitHub repository.
2. Create or redeploy the app at https://share.streamlit.io/.
3. Set the main file path to `app.py`.
4. Open the deployed app; it automatically attempts the live data load.
5. If a 1,000-company request fails or times out, lower the target count in the sidebar and click refresh.

## Metric definitions used by this app

- **STA:** `(net income − operating cash flow) / average total assets`.
- **SNOA:** `(operating assets − operating liabilities) / total assets`, using total assets less cash for operating assets and total liabilities less current and long-term debt for operating liabilities. If required debt inputs are missing, SNOA remains missing.
- **Altman Z:** `1.2 × working capital/assets + 1.4 × retained earnings/assets + 3.3 × EBIT/assets + 0.6 × market equity/total liabilities + sales/assets`, calculated only when all inputs exist.
- **GPA:** gross profit / total assets.
- **BTM:** book equity / market capitalization.
- **CFOA:** operating cash flow / total assets.
- **Margin observation:** gross profit / revenue for each available fiscal year.
- **MS:** arithmetic average of annual gross-margin growth rates divided by their sample standard deviation.
- **MG:** annualized geometric growth in margin using first and last available positive margins and the actual number of fiscal-year intervals between them.
- **MM:** `max(percentile(MS), percentile(MG))`.

The requested seven-year method needs eight annual margin observations. The app does not invent earlier years if the provider lacks them. Confirm exact formula definitions and metric directions against your professor's instructions, especially the BTM direction and the use of Altman Z across industries.

## Screening and portfolio logic

- Rank 1 is best. Lower STA/SNOA is preferred; higher Z-score, MS, MG, GPA, BTM and CFOA are the current defaults.
- The bottom of each stage is removed using the adjustable percentage, and rankings are recalculated on the surviving population for later stages.
- Portfolio industry targets default to equal weights across represented industries. Each industry's target is divided equally among its surviving companies.
- BUY / HOLD / SELL labels are relative classifications among final survivors, influenced by cumulative final rank and portfolio weight. Optional risk flags prioritize companies with weak Z-score, GPA or BTM for SELL. These are coursework signals, not investment advice or guarantees of future performance.

## Source and licensing note

`yfinance` is an unofficial open-source client and is not affiliated with or endorsed by Yahoo Finance. Review the applicable source terms and use the data only as permitted for your educational project. See https://ranaroussi.github.io/yfinance/ and https://pypi.org/project/yfinance/.
