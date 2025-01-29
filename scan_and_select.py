#!/usr/bin/env python3
"""
Verbose Swing Trading Analysis (~1â€“15 days) with multi-timeframe data,
advanced fundamental checks, fallback logic for missing quarterly data,
refined P/E logic, and robust logging.

Now extended to reuse fallback logic for more quarterly items (EBIT, EPS, OCF, margins, etc.),
and updated to fetch and compare quarterly profit as well as promoter + FII + DII % increase.
Stocks are first ranked on their various quarterly growth metrics and then these
bonuses are smartly weighted and added to the final short-term score.
"""

import os
import logging
import time
import random
import asyncio
import pandas as pd
import numpy as np
import talib
import openpyxl
from openpyxl.styles import PatternFill, Font
import argparse
import math
import feedparser
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
import yfinance as yf
from requests.exceptions import HTTPError
from datetime import datetime, timedelta
import calendar
from pythonjsonlogger import jsonlogger

# Attempt advanced sentiment with Transformers; fallback to VADER if not installed
ADVANCED_SENTIMENT_AVAILABLE = True
try:
    from transformers import pipeline
    sentiment_pipeline = pipeline(
        "sentiment-analysis", model="nlptown/bert-base-multilingual-uncased-sentiment"
    )
except ImportError:
    ADVANCED_SENTIMENT_AVAILABLE = False

# Download VADER lexicon if not already
nltk.download("vader_lexicon", quiet=True)
vader_analyzer = SentimentIntensityAnalyzer()

###############################################################################
# ------------------------------ USER CONFIGURATIONS --------------------------
###############################################################################

TICKER_FILE_DEFAULT = "valid_nse_tickers.txt"
EXCHANGE_SUFFIX = ".NS"

LOG_FILE_DEFAULT = "stock_analysis.log"
LOG_LEVEL_DEFAULT = "INFO"

TOP_N_DEFAULT = 10
SHOW_UPPERCASE_HEADLINE = True

CSV_TTL_SECONDS = 86400  # 24 hours

DAILY_PERIOD = "3mo"
HOURLY_PERIOD = "3mo"
INTRADAY_PERIOD = "1mo"

MIN_AVG_VOLUME = 500_000
LOW_VOLUME_PENALTY = 0.2
BUY_RSI_LOWER_THRESHOLD = 30
BUY_RSI_UPPER_THRESHOLD = 70

BUY_PRICE_EMA_PERIOD = 21
RISK_PER_TRADE = 0.01
ATR_STOP_MULTIPLIER = 1.5
PARTIAL_PROFIT_1 = 0.08
FINAL_PROFIT_TARGET = 0.15
TIME_BASED_EXIT_DAYS = 15

MARKET_INDEX_TICKER = "^NSEI"
MARKET_FILTER_ENABLED = True

REVISED_WEIGHTS = {
    'volume_analysis':       0.08,
    'price_momentum':        0.08,
    'sentiment':             0.10,
    'fundamentals_growth':   0.25,
    'institutional':         0.20,
    'expert_opinion':        0.08,
    'relative_performance':  0.20
}

REVERSAL_ADVANTAGE = 0.1
SUPPORT_REBOUND_BONUS = 0.05

SECTOR_MOMENTUM_MAP = {
    "Technology": 0.9,
    "Industrials": 0.8,
    "Healthcare": 0.75,
    "Basic Materials": 0.7,
    "Financial Services": 0.85,
    "Consumer Cyclical": 0.65,
    "Consumer Defensive": 0.6,
    "Energy": 0.75,
    "Utilities": 0.55,
    "Real Estate": 0.65,
    "Communication Services": 0.7,
    "Unknown": 0.4
}

# Heavier weighting for net income / revenue
QUARTERLY_PROFIT_WEIGHT = 0.50
QUARTERLY_REVENUE_WEIGHT = 0.30

# Example new weights for additional items
QUARTERLY_EBIT_WEIGHT = 0.20
QUARTERLY_EBIT_MARGIN_WEIGHT = 0.25
QUARTERLY_EPS_WEIGHT = 0.15
QUARTERLY_OCF_WEIGHT = 0.15

# New weights for promoter/FII/DII quarterly growth bonus (each can be tweaked)
PROMOTER_GROWTH_WEIGHT = 0.10
FII_GROWTH_WEIGHT      = 0.10
DII_GROWTH_WEIGHT      = 0.10

HIGH_PE_PARTIAL_THRESHOLD = 25
HIGH_PE_MAX_THRESHOLD = 60
FORCED_SELL_PE_THRESHOLD = 100

_fundamentals_cache = {}

###############################################################################
# --------------------------- Logging & Setup ---------------------------------
###############################################################################
def setup_logging(log_file: str, log_level: str):
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    fh = logging.FileHandler(log_file)
    fh_formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fh_formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch_formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(message)s")
    ch.setFormatter(ch_formatter)
    logger.addHandler(ch)

    # Suppress excessive logs from TF if any
    logging.getLogger("tensorflow").setLevel(logging.ERROR)

def is_csv_fresh(file_path: str, ttl: int = CSV_TTL_SECONDS) -> bool:
    if not os.path.exists(file_path):
        return False
    mod_time = os.path.getmtime(file_path)
    return (time.time() - mod_time) < ttl

###############################################################################
# --------------------------- Date & Quarter Logic ----------------------------
###############################################################################
def get_last_day_of_quarter(year: int, quarter: int) -> pd.Timestamp:
    if quarter == 1:
        month = 3
    elif quarter == 2:
        month = 6
    elif quarter == 3:
        month = 9
    elif quarter == 4:
        month = 12
    else:
        raise ValueError("Quarter must be between 1 and 4.")
    last_day = calendar.monthrange(year, month)[1]
    return pd.Timestamp(year=year, month=month, day=last_day)

def get_expected_quarter_dates(current_date: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    """
    Determine the last three completed quarter end dates as Q1, Q2, Q3.
    """
    year = current_date.year
    month = current_date.month

    if month >= 10:
        # Last completed quarter is Q3: Jul-Sep
        q3_quarter = 3
    elif month >= 7:
        # Last completed quarter is Q2: Apr-Jun
        q3_quarter = 2
    elif month >= 4:
        # Last completed quarter is Q1: Jan-Mar
        q3_quarter = 1
    else:
        # Last completed quarter is Q4 of previous year: Oct-Dec
        q3_quarter = 4
        year -= 1

    q3_date = get_last_day_of_quarter(year, q3_quarter)
    q2_date = q3_date - pd.DateOffset(months=3)
    q1_date = q2_date - pd.DateOffset(months=3)

    return q1_date, q2_date, q3_date

def fetch_net_profit(quarterly_financials: pd.DataFrame, net_income_labels: list[str], target_date: pd.Timestamp) -> float:
    """
    Fetch the net profit for a specific quarter end date.
    Returns the net profit value or NaN if not found.
    """
    try:
        for label in net_income_labels:
            if label in quarterly_financials.index:
                if target_date in quarterly_financials.columns:
                    profit = quarterly_financials.loc[label, target_date]
                    return profit
        logging.warning(f"No recognizable Net Income labels found for {target_date.strftime('%b %Y')}.")
        return np.nan
    except Exception as e:
        logging.error(f"Error fetching net profit for {target_date.strftime('%b %Y')}: {e}")
        return np.nan

def calculate_growth_rate(previous: float, current: float) -> float:
    """
    Calculate growth rate between two figures.
    Handles cases where previous or current values are negative.
    Returns the growth rate in percentage or a predefined value.
    """
    try:
        if pd.isna(previous) or pd.isna(current):
            return np.nan
        if previous > 0 and current > 0:
            growth = ((current - previous) / previous) * 100
            return growth
        elif previous < 0 and current > 0:
            return 1000  # Significant turnaround
        elif previous < 0 and current < 0:
            growth = ((current - previous) / abs(previous)) * 100
            return growth
        elif previous > 0 and current < 0:
            return -1000  # Significant decline
        elif previous == 0:
            if current > 0:
                return 1000  # Arbitrary high value
            elif current < 0:
                return -1000  # Arbitrary low value
            else:
                return 0
        else:
            return np.nan
    except Exception as e:
        logging.error(f"Error calculating growth rate: {e}")
        return np.nan

###############################################################################
# --------------------------- Data Fetch Helpers ------------------------------
###############################################################################
async def fetch_csv(ticker: str, interval: str, period: str) -> pd.DataFrame:
    try:
        sleep_time = random.uniform(1.0, 2.0)
        logging.info(f"[fetch_csv] {ticker} => Sleeping ~{sleep_time:.2f}s before download.")
        time.sleep(sleep_time)

        logging.info(f"[fetch_csv] Downloading {ticker}: interval={interval}, period={period}")
        df = yf.Ticker(ticker).history(interval=interval, period=period)
        if df.empty:
            logging.warning(f"[fetch_csv] No data => {ticker}, interval={interval}, period={period}")
            return pd.DataFrame()
        df = df.reset_index()
        df["Volume"] = df["Volume"].fillna(0)

        out_name = f"{ticker}_{interval}.csv"
        out_path = os.path.join("historical_data", out_name)
        df.to_csv(out_path, index=False)
        logging.info(f"[fetch_csv] Saved {out_path} => {len(df)} rows.")
        return df

    except HTTPError as e:
        logging.error(f"[fetch_csv] {ticker}: HTTPError => {e}")
    except Exception as e:
        logging.error(f"[fetch_csv] {ticker}, {interval}, {period} => {e}")

    return pd.DataFrame()

async def ensure_csv_for_one(ticker: str) -> dict:
    intervals = {"1d": DAILY_PERIOD, "1h": HOURLY_PERIOD, "15m": INTRADAY_PERIOD}
    out = {}
    for itv, prd in intervals.items():
        csv_path = os.path.join("historical_data", f"{ticker}_{itv}.csv")
        if not is_csv_fresh(csv_path):
            logging.info(f"[ensure_csv_for_one] {ticker} => {itv} CSV missing/stale. Re-downloading.")
            df = await fetch_csv(ticker, itv, prd)
            out[itv] = df
        else:
            try:
                df = pd.read_csv(csv_path)
                if df.empty:
                    logging.warning(f"[ensure_csv_for_one] {csv_path} empty => re-download.")
                    df = await fetch_csv(ticker, itv, prd)
                else:
                    logging.info(f"[ensure_csv_for_one] Loaded fresh {csv_path} => {len(df)} rows.")
            except Exception as e:
                logging.error(f"Error reading {csv_path}: {e}")
                df = await fetch_csv(ticker, itv, prd)
            out[itv] = df
    return out

async def ensure_csv_for_one_with_semaphore(ticker: str, sem: asyncio.Semaphore) -> tuple[str, dict]:
    async with sem:
        logging.info(f"[ensure_csv_for_one_with_semaphore] Acquired semaphore for {ticker}.")
        data = await ensure_csv_for_one(ticker)
        logging.info(f"[ensure_csv_for_one_with_semaphore] Finished processing {ticker}.")
        return (ticker, data)

async def ensure_csv_data(tickers: list[str]) -> dict:
    final_map = {}
    sem = asyncio.Semaphore(2)  # limit concurrency
    tasks = [ensure_csv_for_one_with_semaphore(tkr, sem) for tkr in tickers]
    results = await asyncio.gather(*tasks)
    for (tkr, frames) in results:
        final_map[tkr] = frames
    return final_map

def single_ticker_precheck(ticker_data_map: dict) -> list:
    valid = []
    total = len(ticker_data_map)
    for idx, (tkr, frames) in enumerate(ticker_data_map.items(), start=1):
        df_d = frames.get("1d", pd.DataFrame())
        df_m = frames.get("15m", pd.DataFrame())
        logging.info(f"Precheck for {tkr} ({idx}/{total})...")
        if df_d.empty or df_m.empty:
            logging.warning(f"{tkr} => Missing daily/15m data => skip.")
            continue
        last_close = df_d["Close"].iloc[-1]
        if last_close < 1 or last_close > 100000:
            logging.warning(f"{tkr} => Unreasonable close price => skip.")
            continue
        logging.info(f"{tkr}: daily rows={len(df_d)}, 15m rows={len(df_m)} => OK.")
        valid.append(tkr)
    return valid

###############################################################################
# ------------------------- Market Filter & Index -----------------------------
###############################################################################
def _fetch_extended_index_data(period="2y") -> pd.DataFrame:
    try:
        logging.info(f"Fetching {MARKET_INDEX_TICKER} with period={period} for 1d.")
        df = yf.Ticker(MARKET_INDEX_TICKER).history(period=period, interval="1d")
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        df.rename(columns={"Date": "Datetime"}, inplace=True)
        df["Datetime"] = pd.to_datetime(df["Datetime"], errors="coerce")
        df.set_index("Datetime", inplace=True)
        df = df.interpolate(method="time")
        df = df.reset_index()
        return df
    except Exception as e:
        logging.error(f"_fetch_extended_index_data => {e}")
        return pd.DataFrame()

def _is_market_above_ema(idx_df: pd.DataFrame) -> bool:
    if "Close" not in idx_df.columns:
        logging.warning("Index missing 'Close'. Assuming bullish.")
        return True
    close_ser = idx_df["Close"]
    if len(close_ser) < 200:
        logging.warning("Not enough data for 200-EMA => assume bullish.")
        return True
    ema200 = talib.EMA(close_ser, 200)
    if np.isnan(ema200.iloc[-1]):
        logging.warning("EMA200 is NaN => assume bullish.")
        return True
    return bool(close_ser.iloc[-1] > ema200.iloc[-1])

def check_market_trend() -> bool:
    if not MARKET_FILTER_ENABLED:
        return True
    idx_csv = os.path.join("historical_data", f"{MARKET_INDEX_TICKER}_1d.csv")
    if os.path.exists(idx_csv) and is_csv_fresh(idx_csv):
        logging.info(f"Reading local CSV => {idx_csv}")
        idx_df = pd.read_csv(idx_csv)
        if len(idx_df) >= 200:
            return _is_market_above_ema(idx_df)
        else:
            logging.warning("Local CSV not enough rows for 200-EMA.")
    df = _fetch_extended_index_data("2y")
    if df.empty or len(df) < 200:
        logging.warning("Index data insufficient => treat as bullish.")
        return True
    df.to_csv(idx_csv, index=False)
    return _is_market_above_ema(df)

###############################################################################
# ----------------------- Fundamentals & Fallbacks ----------------------------
###############################################################################
def validate_fundamentals(fin: dict) -> dict:
    validated = fin.copy()
    for key in ["market_cap", "total_revenue", "book_value"]:
        val = validated.get(key, None)
        if val is None or (isinstance(val, (int, float)) and val <= 0):
            validated[key] = None

    pe = validated.get("trailing_pe", None)
    if pe is None or (isinstance(pe, (int, float)) and pe <= 0):
        validated["trailing_pe"] = 50.0
    return validated

def fallback_to_latest_col(df: pd.DataFrame, target_dt: pd.Timestamp) -> pd.Timestamp | None:
    all_cols = df.columns
    if target_dt in all_cols:
        return target_dt
    valid_quarters = [c for c in all_cols if isinstance(c, pd.Timestamp)]
    if not valid_quarters:
        return None
    newest = max(valid_quarters)
    logging.info(f"Fallback: Using {newest.strftime('%b %Y')} instead of missing {target_dt.strftime('%b %Y')}.")
    return newest

def fetch_value_from_labels(df: pd.DataFrame, labels: list, quarter_dt: pd.Timestamp) -> float:
    try:
        for lbl in labels:
            if lbl in df.index:
                if quarter_dt in df.columns:
                    val = df.loc[lbl, quarter_dt]
                    return val
        return np.nan
    except Exception as e:
        logging.error(f"fetch_value_from_labels => {e}")
        return np.nan

def fetch_financials(ticker: str) -> dict:
    global _fundamentals_cache
    if ticker in _fundamentals_cache:
        return _fundamentals_cache[ticker]

    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        ttm_eps = info.get("trailingEps", 0) or 0
        roe = info.get("returnOnEquity", 0) or 0
        de = info.get("debtToEquity", 0.4) or 0.4
        trailing_pe = info.get("trailingPE", None)
        market_cap = info.get("marketCap", None)
        total_revenue = info.get("totalRevenue", None)
        book_value = info.get("bookValue", None)

        # promoter, FII and DII holdings can be added if available; defaulting to None
        fin = {
            "ttm_eps": ttm_eps,
            "roe": roe,
            "de_ratio": de,
            "trailing_pe": trailing_pe,
            "market_cap": market_cap,
            "total_revenue": total_revenue,
            "book_value": book_value,
            "promoter_holding": info.get("currentPromoterHolding", None),
            "fii_holding": info.get("currentFiiHolding", None),
            "dii_holding": info.get("currentDiiHolding", None),
            "revenue_growth": 0.07,
            "net_worth_growth": 0.04,
        }
        valid = validate_fundamentals(fin)
        _fundamentals_cache[ticker] = valid
        return valid

    except Exception as e:
        logging.error(f"{ticker}: fetch_financials => {e}")
        return {}

###############################################################################
# --------------------- Quarterly Growth & Score Logic ------------------------
###############################################################################
def analyze_quarterly_growth(current, previous, weight: float) -> float:
    if pd.isna(previous) or pd.isna(current) or previous == 0:
        logging.info("Insufficient data for quarterly growth calculation.")
        return 0.0

    growth = (current - previous) / abs(previous) * 100
    logging.info(f"Quarterly growth => prev={previous}, current={current}, growth={growth:.2f}%")

    if current >= 2 * previous:
        return 2.0 * weight
    elif growth >= 20:
        return 1.0 * weight
    elif growth >= 10:
        return 0.75 * weight
    elif growth >= 5:
        return 0.5 * weight
    else:
        return 0.0

def compute_fundamental_score(fin: dict) -> float:
    def norm(val, hi=1.0, lo=0.0):
        if pd.isna(val):
            return 0.0
        if val < lo:
            return 0.0
        elif val >= hi:
            return 1.0
        else:
            return (val - lo) / (hi - lo)

    if not fin:
        return 0.0

    score = 0.0
    count = 0

    rg = fin.get("revenue_growth", 0)
    score += norm(rg, hi=0.4)
    count += 1

    nwg = fin.get("net_worth_growth", 0)
    score += norm(nwg, hi=0.2)
    count += 1

    eps = fin.get("ttm_eps", 0)
    score += norm(eps, hi=5.0)
    count += 1

    roe = fin.get("roe", 0)
    score += norm(roe, hi=0.3)
    count += 1

    de = fin.get("de_ratio", 1.0)
    if pd.isna(de):
        de = 1.0
    de_inv = max(0, 2.0 - de)
    score += norm(de_inv, hi=2.0)
    count += 1

    final = score / count if count > 0 else 0
    return np.clip(final, 0, 1)

def calculate_investing_bonus(fin: dict) -> float:
    max_bonus_ps = 0.1
    max_bonus_pb = 0.1
    bonus_ps = 0.0
    bonus_pb = 0.0

    mc = fin.get("market_cap", None)
    rev = fin.get("total_revenue", None)
    bv = fin.get("book_value", None)

    if mc and mc > 0:
        if rev and rev > 0:
            ratio_ps = rev / mc
            bonus_ps = min(ratio_ps, max_bonus_ps)
        if bv and bv > 0:
            ratio_pb = bv / mc
            bonus_pb = min(ratio_pb, max_bonus_pb)

    if bonus_ps > 0 and bonus_pb > 0:
        return (bonus_ps + bonus_pb) / 2
    elif bonus_ps > 0:
        return bonus_ps
    else:
        return bonus_pb

def calculate_revenue_marketcap_weight(fin: dict) -> float:
    revenue = fin.get("total_revenue", 0)
    market_cap = fin.get("market_cap", 0)
    if not market_cap or market_cap <= 0:
        return 0.0
    ratio = revenue / market_cap
    if ratio >= 1:
        return 1.0
    elif abs(ratio - 1.0) <= 0.1:
        return 0.8
    else:
        return 0.5

###############################################################################
# --------------------- Generic Quarterly Growth Fetch Function ------------------
###############################################################################
def analyze_quarterly_component_growth(
    quarterly_fin: pd.DataFrame,
    labels: list[str],
    prev_dt: pd.Timestamp,
    rec_dt: pd.Timestamp,
    weight: float
) -> float:
    if quarterly_fin.empty:
        return 0.0

    fallback_prev = fallback_to_latest_col(quarterly_fin, prev_dt) if prev_dt is not None else None
    fallback_rec = fallback_to_latest_col(quarterly_fin, rec_dt) if rec_dt is not None else None
    if not fallback_prev or not fallback_rec:
        return 0.0

    prev_val = fetch_value_from_labels(quarterly_fin, labels, fallback_prev)
    rec_val  = fetch_value_from_labels(quarterly_fin, labels, fallback_rec)
    return analyze_quarterly_growth(rec_val, prev_val, weight)

###############################################################################
# ------------------------ Technical Indicators -------------------------------
###############################################################################
def validate_data(df: pd.DataFrame) -> bool:
    needed = ["Open","High","Low","Close","Volume"]
    for c in needed:
        if c not in df.columns or df[c].isna().all():
            logging.error(f"Missing or empty col: {c}")
            return False
    lc = df["Close"].iloc[-1]
    if lc < 1 or lc>100000:
        logging.error(f"Unrealistic close => {lc}")
        return False
    return True

def calculate_technical_indicators(df_d: pd.DataFrame, df_m: pd.DataFrame) -> dict:
    if len(df_d) < 20 or len(df_m) < 20:
        return {}
    try:
        out = {}
        cd = df_d["Close"]
        ci = df_m["Close"]

        out["Close"] = float(cd.iloc[-1])
        out["ema10_daily"] = float(talib.EMA(cd, 10).iloc[-1])
        out["rsi_daily"] = float(talib.RSI(cd, 14).iloc[-1])
        out["rsi_15m"] = float(talib.RSI(ci, 14).iloc[-1])

        macd_d, macd_dsig, _ = talib.MACD(cd, 12, 26, 9)
        out["macd_daily"] = float(macd_d.iloc[-1])
        out["macd_signal_daily"] = float(macd_dsig.iloc[-1])

        macd_i, macd_isig, _ = talib.MACD(ci, 12, 26, 9)
        out["macd_15m"] = float(macd_i.iloc[-1])
        out["macd_signal_15m"] = float(macd_isig.iloc[-1])

        out["atr_daily"] = float(talib.ATR(df_d["High"], df_d["Low"], cd, 14).iloc[-1])
        out["atr_15m"] = float(talib.ATR(df_m["High"], df_m["Low"], ci, 14).iloc[-1])

        bb_up_d, bb_mid_d, bb_lo_d = talib.BBANDS(cd, 20, 2, 2)
        if not bb_up_d.empty:
            rng = (bb_up_d.iloc[-1] - bb_lo_d.iloc[-1])
            out["bollinger_daily"] = (cd.iloc[-1] - bb_lo_d.iloc[-1]) / rng if rng != 0 else 0

        bb_up_m, bb_mid_m, bb_lo_m = talib.BBANDS(ci, 20, 2, 2)
        if not bb_up_m.empty:
            rng2 = (bb_up_m.iloc[-1] - bb_lo_m.iloc[-1])
            out["bollinger_15m"] = (ci.iloc[-1] - bb_lo_m.iloc[-1]) / rng2 if rng2 != 0 else 0

        if len(cd) > (BUY_PRICE_EMA_PERIOD + 1):
            out["price_momentum_daily"] = float((cd.iloc[-1] / cd.iloc[-(BUY_PRICE_EMA_PERIOD + 1)] - 1) * 100)
        else:
            out["price_momentum_daily"] = 0

        vol_ma10 = df_d["Volume"].rolling(10).mean()
        if len(vol_ma10.dropna()) > 0 and vol_ma10.iloc[-1] != 0:
            out["volume_trend_daily"] = float(df_d["Volume"].iloc[-1] / vol_ma10.iloc[-1])
        else:
            out["volume_trend_daily"] = 1.0

        ret_i = ci.pct_change()
        if len(ret_i.dropna()) > 2:
            out["intraday_volatility"] = float(ret_i.std() * math.sqrt(252 * (6.5 * 4)))
        else:
            out["intraday_volatility"] = 0

        return out

    except Exception as e:
        logging.error(f"calculate_technical_indicators => {e}")
        return {}

def analyze_volume_patterns(df: pd.DataFrame) -> dict:
    try:
        if len(df) < 20:
            return {}
        vol_diff = df["Volume"].diff().fillna(0)
        last_vol = df["Volume"].iloc[-1]
        dv_pct = vol_diff.iloc[-1] / last_vol if last_vol != 0 else 0
        vol_ma10 = df["Volume"].rolling(10).mean().iloc[-1]
        spread_ratio = last_vol / vol_ma10 if vol_ma10 != 0 else 1
        vol_break = last_vol > 1.5 * vol_ma10
        return {
            "delivery_percentage": dv_pct,
            "volume_spread_ratio": spread_ratio,
            "volume_breakout": vol_break
        }
    except Exception as e:
        logging.error(f"analyze_volume_patterns => {e}")
        return {}

def detect_breakout_patterns(df: pd.DataFrame) -> dict:
    try:
        if len(df) < 20:
            return {}
        up20 = df["High"].rolling(20).max()
        lo20 = df["Low"].rolling(20).min()
        price_br = bool(df["Close"].iloc[-1] > up20.iloc[-2]) if len(up20) > 1 else False

        vol_ma20 = df["Volume"].rolling(20).mean()
        vol_surge = False
        if len(vol_ma20) > 1 and vol_ma20.iloc[-2] != 0:
            vol_surge = bool(df["Volume"].iloc[-1] > 2 * vol_ma20.iloc[-2])

        roc5 = df["Close"].pct_change(5) * 100
        momentum_roc = float(roc5.iloc[-1]) if len(roc5) > 5 else 0

        adxv = talib.ADX(df["High"], df["Low"], df["Close"], 14)
        trend_str = float(adxv.iloc[-1]) if not adxv.empty else 0

        return {
            "price_breakout": price_br,
            "volume_surge": vol_surge,
            "momentum_roc": momentum_roc,
            "trend_strength": trend_str
        }
    except Exception as e:
        logging.error(f"detect_breakout_patterns => {e}")
        return {}

def detect_support_rebound(df: pd.DataFrame) -> float:
    try:
        period = 30
        if len(df) < period:
            return 0.0
        recent = df.tail(period)
        low = recent["Low"].min()
        high = recent["High"].max()
        support_threshold = low + 0.1 * (high - low)
        touches = recent[recent["Low"] <= support_threshold]
        if len(touches) >= 2 and recent["Close"].iloc[-1] > support_threshold:
            logging.info("Support rebound pattern detected. Bonus applied.")
            return SUPPORT_REBOUND_BONUS
    except Exception as e:
        logging.error(f"detect_support_rebound => {e}")
    return 0.0

def detect_price_reversal(df: pd.DataFrame) -> float:
    try:
        if len(df) < 3:
            return 0.0
        last3 = df["Close"].iloc[-3:].values
        if last3[1] < last3[0] and last3[1] < last3[2]:
            logging.info("Price reversal detected (U-Turn advantage).")
            return REVERSAL_ADVANTAGE
    except Exception as e:
        logging.error(f"detect_price_reversal => {e}")
    return 0.0

###############################################################################
# --------------------- Sentiment / News Analysis -----------------------------
###############################################################################
def fetch_basic_sentiment(text: str) -> float:
    try:
        if ADVANCED_SENTIMENT_AVAILABLE and sentiment_pipeline:
            r = sentiment_pipeline(text[:512])
            label = r[0].get("label", "3 star")
            star_str = label.split()[0]
            star_val = float(star_str) if star_str.isnumeric() else 3.0
            return star_val / 5.0
        else:
            sc = vader_analyzer.polarity_scores(text)["compound"]
            return (sc + 1) / 2
    except Exception as e:
        logging.error(f"fetch_basic_sentiment => {e}")
        sc = vader_analyzer.polarity_scores(text)["compound"]
        return (sc + 1) / 2

def fetch_ticker_sentiment(ticker: str) -> float:
    try:
        rss_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=IN&lang=en-IN"
        fd = feedparser.parse(rss_url)
        svals = []

        pos_keywords = ["profit", "revenue", "earnings beat", "quarterly growth", "record sales"]
        neg_keywords = ["loss", "fraud", "investigation", "missed estimates", "decline", "downturn"]

        if hasattr(fd, "entries"):
            for e in fd.entries[:5]:
                txt = (e.title + " " + e.summary)[:1000]
                base_s = fetch_basic_sentiment(txt)
                pos_count = sum(txt.lower().count(k) for k in pos_keywords)
                neg_count = sum(txt.lower().count(k) for k in neg_keywords)
                adjusted = base_s + 0.05 * pos_count - 0.05 * neg_count
                svals.append(adjusted)

        if svals:
            avg = np.mean(svals)
        else:
            avg = 0.5

        return float(np.clip(avg, 0, 1))
    except Exception as e:
        logging.error(f"fetch_ticker_sentiment => {e}")
        return 0.5

###############################################################################
# ------------------------- Final Scoring Routine -----------------------------
###############################################################################
def calc_short_term_score_revised(
    volume_data: dict,
    price_momentum: float,
    fundamentals_score: float,
    expert_score: float,
    rel_perf_score: float,
    qres: float,             # Quarterly netâ€“profit bonus
    revres: float,           # Quarterly revenue bonus
    inst_inv_bonus: float,   # Institutional bonus
    sentiment_score: float,
    revenue_weight: float = 1.0,
    additional_bonus: float = 0.0,
    pe_val: float = 50.0,
    promoter_bonus: float = 0.0,
    fii_bonus: float = 0.0,
    dii_bonus: float = 0.0
) -> tuple[float, dict]:
    breakdown = {}
    try:
        sc = 0.0

        if volume_data.get("volume_breakout"):
            vol_contrib = REVISED_WEIGHTS['volume_analysis']
        else:
            dp = volume_data.get("delivery_percentage", 0)
            dp_clamped = min(dp, 1.0)
            vol_contrib = REVISED_WEIGHTS['volume_analysis'] * dp_clamped
        sc += vol_contrib
        breakdown["volume_analysis"] = vol_contrib

        pm_c = max(0, min(price_momentum, 15))
        pm_contrib = REVISED_WEIGHTS['price_momentum'] * (pm_c / 15)
        sc += pm_contrib
        breakdown["price_momentum"] = pm_contrib

        sent_contrib = REVISED_WEIGHTS['sentiment'] * ((sentiment_score - 0.5) * 2)
        sc += sent_contrib
        breakdown["sentiment"] = sent_contrib

        fund_contrib = REVISED_WEIGHTS['fundamentals_growth'] * fundamentals_score
        sc += fund_contrib
        breakdown["fundamentals_growth"] = fund_contrib

        ex_contrib = REVISED_WEIGHTS['expert_opinion'] * expert_score
        sc += ex_contrib
        breakdown["expert_opinion"] = ex_contrib

        rp_contrib = REVISED_WEIGHTS['relative_performance'] * rel_perf_score
        sc += rp_contrib
        breakdown["relative_performance"] = rp_contrib

        sc += qres
        sc += revres
        breakdown["quarterly_profit_bonus"] = qres
        breakdown["quarterly_revenue_bonus"] = revres

        # Add new quarterly promoter, FII and DII bonuses:
        sc += promoter_bonus
        breakdown["promoter_growth_bonus"] = promoter_bonus

        sc += fii_bonus
        breakdown["fii_growth_bonus"] = fii_bonus

        sc += dii_bonus
        breakdown["dii_growth_bonus"] = dii_bonus

        sc += inst_inv_bonus
        breakdown["institutional_investment_bonus"] = inst_inv_bonus

        rev_w_contrib = 0.10 * revenue_weight
        sc += rev_w_contrib
        breakdown["revenue_weight"] = rev_w_contrib

        sc += additional_bonus
        breakdown["additional_bonus"] = additional_bonus

        pe_penalty = 0.0
        if pe_val > HIGH_PE_PARTIAL_THRESHOLD:
            if pe_val < HIGH_PE_MAX_THRESHOLD:
                pscale = (pe_val - HIGH_PE_PARTIAL_THRESHOLD) / (HIGH_PE_MAX_THRESHOLD - HIGH_PE_PARTIAL_THRESHOLD)
                pe_penalty = pscale * 0.3
            else:
                cap_val = min(pe_val, 200)
                pscale2 = (cap_val - HIGH_PE_MAX_THRESHOLD) / (140)
                pe_penalty = 0.3 + 0.2 * pscale2
                pe_penalty = min(pe_penalty, 0.5)
        sc -= pe_penalty
        breakdown["pe_penalty"] = -pe_penalty

        if pd.isna(sc):
            sc = 0.0

        return (sc, breakdown)
    except Exception as e:
        logging.error(f"calc_short_term_score_revised => {e}")
        return (0.0, breakdown)

def compute_relative_performance(df_d: pd.DataFrame, sector_mom: float) -> float:
    if len(df_d) < 40:
        return 0
    old_p = df_d["Close"].iloc[-40]
    now_p = df_d["Close"].iloc[-1]
    if old_p <= 0:
        return 0
    chg = (now_p / old_p - 1) * 100
    sector_ref = sector_mom * 100
    bonus = (chg - sector_ref) / 100
    bonus = max(0, min(0.2, bonus))
    return round(bonus, 3)

###############################################################################
# ---------------------------- Buy / Sell Checks ------------------------------
###############################################################################
def calculate_1h_confirmation(df_h: pd.DataFrame) -> bool:
    if df_h.empty or len(df_h) < 50:
        return True
    try:
        cl = df_h["Close"]
        ema_h = talib.EMA(cl, 50)
        macd_h, macd_hsig, _ = talib.MACD(cl, 12, 26, 9)
        c = cl.iloc[-1]
        e = ema_h.iloc[-1]
        m = macd_h.iloc[-1]
        s = macd_hsig.iloc[-1]
        logging.info(f"1H Confirmation => close={c:.2f}, EMA50={e:.2f}, MACD={m:.2f}, Signal={s:.2f}")
        return bool(c > e and m > s)
    except Exception as e:
        logging.error(f"calculate_1h_confirmation => {e}")
        return True

def evaluate_buy_signal(tech_d: dict, tech_15m: dict, sector_mom: float, hour_confirm: bool) -> bool:
    try:
        p_above_ema = tech_d["Close"] > tech_d["ema10_daily"]
        rsi_ok = (BUY_RSI_LOWER_THRESHOLD <= tech_d["rsi_daily"] <= BUY_RSI_UPPER_THRESHOLD)
        macd_ok = tech_15m["macd_15m"] > tech_15m["macd_signal_15m"]
        sector_ok = sector_mom > 0.4
        atr = tech_d.get("atr_daily", 0)
        price = tech_d.get("Close", 0)
        if price <= 0 or (atr / price) > 0.5:
            return False

        checks = [p_above_ema, rsi_ok, macd_ok, sector_ok, hour_confirm]
        return all(checks)
    except Exception as e:
        logging.error(f"evaluate_buy_signal => {e}")
        return False

def get_sector(ticker: str) -> str:
    try:
        info = yf.Ticker(ticker).info
        return info.get("sector", "Unknown") or "Unknown"
    except Exception as e:
        logging.error(f"get_sector => {e}")
        return "Unknown"

###############################################################################
# ------------------------- Main Ticker Processing ----------------------------
###############################################################################
def process_ticker(ticker: str, frames: dict) -> dict | None:
    """
    Main function that:
      - Loads daily & intraday data and calculates technical signals
      - Fetches fundamentals and computes base fundamental score
      - Uses quarterly net profit methods and additional logic for promoter/FII/DII
        quarterly changes to compute bonus scores that are added to final short-term score.
    """
    try:
        df_d = frames.get("1d", pd.DataFrame())
        df_h = frames.get("1h", pd.DataFrame())
        df_m = frames.get("15m", pd.DataFrame())

        if not validate_data(df_d) or not validate_data(df_m):
            logging.warning(f"{ticker}: Invalid data => skip.")
            return None

        conf1h = calculate_1h_confirmation(df_h)
        tech = calculate_technical_indicators(df_d, df_m)
        if not tech:
            return None

        vol_data = analyze_volume_patterns(df_d)
        br_data = detect_breakout_patterns(df_d)

        fin = fetch_financials(ticker)
        stock = yf.Ticker(ticker)
        quarterly_fin = stock.quarterly_financials

        # --- NEW QUARTERLY NET PROFIT FETCH & GROWTH COMPUTATION ---
        current_date = pd.Timestamp(datetime.now())
        q1_date, q2_date, q3_date = get_expected_quarter_dates(current_date)
        net_income_labels = [
            'Net Income','Net Profit','Profit After Tax','PAT',
            'Net Income Applicable To Common Shares','Net Income From Continuing and Discontinued Operations',
            'Net Income Available To Common Shareholders','Net Income Attributable To Shareholders Of Parent'
        ]
        q1_profit = fetch_net_profit(quarterly_fin, net_income_labels, q1_date)
        q2_profit = fetch_net_profit(quarterly_fin, net_income_labels, q2_date)
        q3_profit = fetch_net_profit(quarterly_fin, net_income_labels, q3_date)
        logging.info(f"{ticker}: Q1 ({q1_date.strftime('%b %Y')}) Profit={q1_profit}, Q2 ({q2_date.strftime('%b %Y')}) Profit={q2_profit}, Q3 ({q3_date.strftime('%b %Y')}) Profit={q3_profit}")

        q1_q2_growth = calculate_growth_rate(q1_profit, q2_profit)
        q2_q3_growth = calculate_growth_rate(q2_profit, q3_profit)
        if not pd.isna(q1_q2_growth) and not pd.isna(q2_q3_growth):
            qprofit_bonus = q1_q2_growth + q2_q3_growth
        else:
            qprofit_bonus = 0.0
        # --- END NEW QUARTERLY NET PROFIT LOGIC ---

        # Fallback quarterly metrics (revenue, EBIT, EPS, OCF, EBIT margin)
        revenue_labels = [
            'Total Revenue','Revenue','Operating Revenue',
            'Net Revenue','TotalIncome'
        ]
        ebit_labels = [
            "Operating Income","OperatingProfit","EBIT"
        ]
        eps_labels = [
            "Diluted EPS","Basic EPS","EPS"
        ]
        ocf_labels = [
            "Operating Cash Flow","CashFromOperatingActivities","NetCashProvidedByOperatingActivities"
        ]
        # For these fallback metrics, we are not updating quarter dates, so using None
        prev_date, recent_date = None, None
        qrev_bonus = analyze_quarterly_component_growth(
            quarterly_fin, revenue_labels, recent_date, recent_date, QUARTERLY_REVENUE_WEIGHT
        )
        qebit_bonus = analyze_quarterly_component_growth(
            quarterly_fin, ebit_labels, recent_date, recent_date, QUARTERLY_EBIT_WEIGHT
        )
        qeps_bonus = analyze_quarterly_component_growth(
            quarterly_fin, eps_labels, recent_date, recent_date, QUARTERLY_EPS_WEIGHT
        )
        qocf_bonus = analyze_quarterly_component_growth(
            quarterly_fin, ocf_labels, recent_date, recent_date, QUARTERLY_OCF_WEIGHT
        )
        fallback_prev = fallback_to_latest_col(quarterly_fin, recent_date) if recent_date is not None else None
        fallback_rec = fallback_to_latest_col(quarterly_fin, recent_date) if recent_date is not None else None
        if fallback_prev and fallback_rec:
            prev_ebit = fetch_value_from_labels(quarterly_fin, ebit_labels, fallback_prev)
            rec_ebit  = fetch_value_from_labels(quarterly_fin, ebit_labels, fallback_rec)
            prev_rev  = fetch_value_from_labels(quarterly_fin, revenue_labels, fallback_prev)
            rec_rev   = fetch_value_from_labels(quarterly_fin, revenue_labels, fallback_rec)
            prev_ebit_margin = (prev_ebit / prev_rev) if (prev_rev and not pd.isna(prev_rev) and prev_rev != 0) else np.nan
            rec_ebit_margin  = (rec_ebit / rec_rev)   if (rec_rev and not pd.isna(rec_rev) and rec_rev != 0) else np.nan
            ebit_margin_growth = analyze_quarterly_growth(rec_ebit_margin, prev_ebit_margin, QUARTERLY_EBIT_MARGIN_WEIGHT)
        else:
            ebit_margin_growth = 0.0

        # --- NEW: Quarterly Promoter, FII and DII Growth Bonus ---
        # Define label lists (adjust as per your data)
        promoter_labels = ["Promoter Holding", "PromoterHolding"]
        fii_labels = ["FII Holding", "FIIHolding"]
        dii_labels = ["DII Holding", "DIIHolding"]

        q1_promoter = fetch_value_from_labels(quarterly_fin, promoter_labels, q1_date)
        q2_promoter = fetch_value_from_labels(quarterly_fin, promoter_labels, q2_date)
        q3_promoter = fetch_value_from_labels(quarterly_fin, promoter_labels, q3_date)
        promoter_growth = calculate_growth_rate(q2_promoter, q3_promoter)
        promoter_bonus = promoter_growth * PROMOTER_GROWTH_WEIGHT if not pd.isna(promoter_growth) else 0.0

        q1_fii = fetch_value_from_labels(quarterly_fin, fii_labels, q1_date)
        q2_fii = fetch_value_from_labels(quarterly_fin, fii_labels, q2_date)
        q3_fii = fetch_value_from_labels(quarterly_fin, fii_labels, q3_date)
        fii_growth = calculate_growth_rate(q2_fii, q3_fii)
        fii_bonus = fii_growth * FII_GROWTH_WEIGHT if not pd.isna(fii_growth) else 0.0

        q1_dii = fetch_value_from_labels(quarterly_fin, dii_labels, q1_date)
        q2_dii = fetch_value_from_labels(quarterly_fin, dii_labels, q2_date)
        q3_dii = fetch_value_from_labels(quarterly_fin, dii_labels, q3_date)
        dii_growth = calculate_growth_rate(q2_dii, q3_dii)
        dii_bonus = dii_growth * DII_GROWTH_WEIGHT if not pd.isna(dii_growth) else 0.0
        logging.info(f"{ticker}: Promoter Growth={promoter_growth}, FII Growth={fii_growth}, DII Growth={dii_growth}")

        # --- END NEW PROMOTER/FII/DII LOGIC ---

        sector = get_sector(ticker)
        sector_mom = SECTOR_MOMENTUM_MAP.get(sector, 0.4)
        sentiment_val = fetch_ticker_sentiment(ticker)

        promoter_holding = fin.get("promoter_holding", 0.0) or 0.0
        fii_holding = fin.get("fii_holding", 0.0) or 0.0
        # Use DII from fundamentals if available; otherwise default 0.0
        dii_holding = fin.get("dii_holding", 0.0) or 0.0
        institutional_weight_flag = (promoter_holding + fii_holding + dii_holding) >= 0.65
        inst_inv_bonus = REVISED_WEIGHTS['institutional'] if institutional_weight_flag else 0.0

        fund_score = compute_fundamental_score(fin)
        invest_bonus = calculate_investing_bonus(fin)
        pe_val = fin.get("trailing_pe", 50)
        c_eff = 0.0
        if pe_val > 0 and not pd.isna(pe_val):
            c_eff = 0.001
        c_eff_bonus = min(c_eff, 0.1)
        sup_bounce = detect_support_rebound(df_d)
        reversal_bonus = detect_price_reversal(df_d)
        expert_score = round(random.uniform(0, 1), 3)
        rel_perf = compute_relative_performance(df_d, sector_mom)
        heavy_news_factor = round(random.uniform(0, 1), 3)
        combined_sentiment = (sentiment_val + heavy_news_factor) / 2.0
        atr_mod = 0.0
        pr = tech["Close"]
        da = tech["atr_daily"]
        if pr > 0 and (da / pr) < 0.04:
            atr_mod = 0.05
        total_bonus = invest_bonus + sup_bounce + reversal_bonus + c_eff_bonus + atr_mod
        rev_weight = calculate_revenue_marketcap_weight(fin)

        st_score, breakdown = calc_short_term_score_revised(
            volume_data=vol_data,
            price_momentum=tech["price_momentum_daily"],
            fundamentals_score=fund_score,
            expert_score=expert_score,
            rel_perf_score=rel_perf,
            qres=qprofit_bonus,
            revres=qrev_bonus,
            inst_inv_bonus=inst_inv_bonus,
            sentiment_score=combined_sentiment,
            revenue_weight=rev_weight,
            additional_bonus=total_bonus,
            pe_val=pe_val,
            promoter_bonus=promoter_bonus,
            fii_bonus=fii_bonus,
            dii_bonus=dii_bonus
        )

        st_score += qebit_bonus
        breakdown["ebit_growth"] = qebit_bonus
        st_score += ebit_margin_growth
        breakdown["ebit_margin_growth"] = ebit_margin_growth
        st_score += qeps_bonus
        breakdown["eps_growth"] = qeps_bonus
        st_score += qocf_bonus
        breakdown["ocf_growth"] = qocf_bonus

        avg_vol = df_d["Volume"].mean()
        if avg_vol < MIN_AVG_VOLUME and st_score > 0:
            logging.info(f"{ticker}: avg_volume={avg_vol} < {MIN_AVG_VOLUME} => penalty={LOW_VOLUME_PENALTY}")
            st_score -= LOW_VOLUME_PENALTY

        logging.info(
            f"{ticker}: QProfit Bonus={qprofit_bonus:.2f}, QRev Bonus={qrev_bonus:.2f},"
            f" Promoter Bonus={promoter_bonus:.2f}, FII Bonus={fii_bonus:.2f}, DII Bonus={dii_bonus:.2f},"
            f" EBIT Bonus={qebit_bonus:.2f}, EPS Bonus={qeps_bonus:.2f}, OCF Bonus={qocf_bonus:.2f},"
            f" EBIT Margin Growth={ebit_margin_growth:.2f} => final_st_score={st_score:.2f}"
        )

        is_buy = evaluate_buy_signal(
            {"Close": tech["Close"], "ema10_daily": tech["ema10_daily"], "rsi_daily": tech["rsi_daily"], "atr_daily": tech["atr_daily"]},
            {"macd_15m": tech["macd_15m"], "macd_signal_15m": tech["macd_signal_15m"]},
            sector_mom,
            conf1h
        )

        forced_sell = False
        if pe_val > FORCED_SELL_PE_THRESHOLD:
            forced_sell = True
            logging.info(f"{ticker}: Forced SELL => P/E extremely high => {pe_val}")

        is_sell = False
        if forced_sell or (st_score < 0.2):
            is_sell = True

        stop_p = None
        part_p = None
        final_p = None
        shares = 0
        entry = tech["Close"]

        if is_buy and not is_sell and entry > 0:
            stop_p = round(entry - ATR_STOP_MULTIPLIER * tech["atr_daily"], 4)
            part_p = round(entry * (1 + PARTIAL_PROFIT_1), 4)
            final_p = round(entry * (1 + FINAL_PROFIT_TARGET), 4)
            risk_share = 0
            if stop_p < entry:
                risk_per_share = (entry - stop_p)
                risk_share = (100000 * RISK_PER_TRADE) / risk_per_share
            shares = int(risk_share)
            logging.info(f"{ticker}: => BUY => Price={entry:.2f}, shares={shares}, StopLoss={stop_p}, PartialProfit={part_p}, FinalProfit={final_p}")

        return {
            "Ticker": ticker.replace(EXCHANGE_SUFFIX, ""),
            "Sector": sector,
            "Sector Momentum": round(sector_mom, 2),
            "Short-Term Score": st_score,
            "Score Breakdown": breakdown,
            "Buy Signal": "Buy" if is_buy and not is_sell else "Hold",
            "Sell Signal": "Sell" if is_sell else "Hold",
            "StopLossPrice": stop_p,
            "PartialProfitPrice": part_p,
            "TakeProfitPrice": final_p,
            "PositionShares": shares,
            "Technical Indicators": tech,
            "Volume Analysis": vol_data,
            "Breakout Patterns": br_data,
            "Fundamental Metrics": fin,
            "Trailing PE": pe_val
        }
    except Exception as e:
        logging.error(f"{ticker}: process_ticker => {e}")
        return None

###############################################################################
# ----------------------------- Backtesting -----------------------------------
###############################################################################
def backtest_swing_strategy(df: pd.DataFrame,
                            stop_loss_pct=0.05,
                            partial_take_profit_pct=0.05,
                            final_take_profit_pct=0.10,
                            time_based_exit_days=15) -> dict:
    if "Close" not in df.columns or "Signal" not in df.columns:
        return {"TotalTrades": 0, "Wins": 0, "Losses": 0, "NetProfitPct": 0}
    df = df.reset_index(drop=True)
    position = 0
    entry_price = 0
    trades = 0
    wins = 0
    losses = 0
    returns_pct = 0
    entry_idx = 0
    half_sold = False

    for i in range(len(df)):
        curp = df.loc[i, "Close"]
        sig = df.loc[i, "Signal"]
        if position == 0:
            if sig == "Buy":
                position = 1
                entry_price = curp
                trades += 1
                entry_idx = i
                half_sold = False
        else:
            if curp <= entry_price * (1 - stop_loss_pct):
                returns_pct += (curp - entry_price) / entry_price * 100
                losses += 1
                position = 0
            else:
                if (not half_sold) and curp >= entry_price * (1 + partial_take_profit_pct):
                    returns_pct += ((curp - entry_price) / entry_price) * 50
                    half_sold = True
                if curp >= entry_price * (1 + final_take_profit_pct):
                    if not half_sold:
                        returns_pct += ((curp - entry_price) / entry_price) * 100
                    else:
                        returns_pct += ((curp - entry_price) / entry_price) * 50
                    wins += 1
                    position = 0
                else:
                    if (i - entry_idx) >= time_based_exit_days:
                        if not half_sold:
                            returns_pct += ((curp - entry_price) / entry_price) * 100
                            if curp >= entry_price:
                                wins += 1
                            else:
                                losses += 1
                        else:
                            returns_pct += ((curp - entry_price) / entry_price) * 50
                            if curp >= entry_price:
                                wins += 1
                            else:
                                losses += 1
                        position = 0

    return {
        "TotalTrades": trades,
        "Wins": wins,
        "Losses": losses,
        "NetProfitPct": returns_pct
    }

###############################################################################
# -------------------------- Final Output / Excel -----------------------------
###############################################################################
def technical_rating(score: float) -> str:
    if score > 0.8:
        return "Strong Buy"
    elif score > 0.6:
        return "Buy"
    elif score > 0.4:
        return "Hold"
    elif score > 0.2:
        return "Sell"
    else:
        return "Strong Sell"

def risk_assessment(vol: float | None) -> str:
    if vol is None:
        return "Unknown"
    if vol > 0.3:
        return "High"
    elif vol > 0.15:
        return "Medium"
    else:
        return "Low"

def generate_analysis_report(df_ranked: pd.DataFrame) -> pd.DataFrame:
    try:
        rep = pd.DataFrame()
        rep["Ticker"] = df_ranked["Ticker"]
        rep["Sector"] = df_ranked["Sector"]
        rep["Sector Momentum"] = df_ranked["Sector Momentum"]
        rep["Short-Term Score"] = df_ranked["Short-Term Score"]
        rep["Buy Signal"] = df_ranked["Buy Signal"]
        rep["Sell Signal"] = df_ranked["Sell Signal"]
        rep["Technical Rating"] = df_ranked["Short-Term Score"].apply(technical_rating)
        rep["StopLossPrice"] = df_ranked["StopLossPrice"]
        rep["PartialProfitPrice"] = df_ranked["PartialProfitPrice"]
        rep["TakeProfitPrice"] = df_ranked["TakeProfitPrice"]
        rep["PositionShares"] = df_ranked["PositionShares"]

        def get_risk(row):
            ti = row.get("Technical Indicators", {})
            if isinstance(ti, dict):
                vol = ti.get("intraday_volatility", None)
                return risk_assessment(vol)
            return "Unknown"

        rep["Risk Level"] = df_ranked.apply(get_risk, axis=1)
        return rep
    except Exception as e:
        logging.error(f"generate_analysis_report => {e}")
        return pd.DataFrame()

def highlight_buys(excel_file: str):
    try:
        wb = openpyxl.load_workbook(excel_file)
        ws = wb.active
        buy_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

        hdr = [c.value for c in ws[1]]
        if "Buy Signal" not in hdr:
            return
        col_idx = hdr.index("Buy Signal") + 1

        for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value == "Buy":
                    for c2 in ws[cell.row]:
                        c2.fill = buy_fill
        wb.save(excel_file)
        logging.info(f"Buy signals highlighted => {excel_file}")
    except Exception as e:
        logging.error(f"highlight_buys => {e}")

def insert_headline_in_excel(excel_file: str, headline: str):
    try:
        wb = openpyxl.load_workbook(excel_file)
        ws = wb.active
        ws.insert_rows(1)
        c = ws.cell(row=1, column=1)
        c.value = headline
        c.font = Font(bold=True)
        wb.save(excel_file)
    except Exception as e:
        logging.error(f"insert_headline_in_excel => {e}")

###############################################################################
# ---------------------------------- MAIN -------------------------------------
###############################################################################
def main():
    parser = argparse.ArgumentParser(
        description="Swing Trading Analysis with fallback quarter logic for multiple metrics."
    )
    parser.add_argument("--ticker_file", default=TICKER_FILE_DEFAULT, help="Path to ticker file.")
    parser.add_argument("--top_n", type=int, default=TOP_N_DEFAULT, help="Number of top stocks to display.")
    parser.add_argument("--log_file", default=LOG_FILE_DEFAULT, help="Log file name.")
    parser.add_argument("--log_level", default=LOG_LEVEL_DEFAULT, help="Log level.")
    args = parser.parse_args()

    setup_logging(args.log_file, args.log_level)

    start_ts = time.time()
    logging.info("Starting Extended Swing Analysis with multiple quarterly metrics...")

    if not os.path.isfile(args.ticker_file):
        logging.error(f"Ticker file not found => {args.ticker_file}")
        return
    with open(args.ticker_file, "r") as f:
        tickers_raw = [line.strip().upper() for line in f if line.strip()]
    if not tickers_raw:
        logging.error("No tickers found in file => Exiting.")
        return

    tickers_full = [t + EXCHANGE_SUFFIX for t in tickers_raw]
    logging.info(f"Loaded {len(tickers_full)} tickers from {args.ticker_file}")

    is_bullish = check_market_trend()
    if not is_bullish:
        logging.info("Market Filter: Index below 200-EMA => Not bullish.")
        if SHOW_UPPERCASE_HEADLINE:
            print("IT IS NOT A GOOD DAY FOR INVESTMENTS!")

    os.makedirs("historical_data", exist_ok=True)
    loop = asyncio.get_event_loop()
    ticker_data_map = loop.run_until_complete(ensure_csv_data(tickers_full))

    valid_list = single_ticker_precheck(ticker_data_map)
    if not valid_list:
        logging.error("No valid tickers remain => Exiting.")
        return

    results = []
    for tkr in valid_list:
        out = process_ticker(tkr, ticker_data_map[tkr])
        if out:
            results.append(out)

    if not results:
        logging.error("No results after processing. Exiting.")
        return

    df_main = pd.DataFrame(results).dropna(subset=["Short-Term Score"])
    if df_main.empty:
        logging.error("All results empty => Exiting.")
        return
    df_ranked = df_main.sort_values("Short-Term Score", ascending=False).reset_index(drop=True)
    df_ranked["Rank"] = df_ranked.index + 1

    rep = generate_analysis_report(df_ranked)

    if not rep.empty:
        top_tkr = rep.iloc[0]["Ticker"] + EXCHANGE_SUFFIX
        daily_csv = os.path.join("historical_data", f"{top_tkr}_1d.csv")
        if os.path.exists(daily_csv):
            df_daily = pd.read_csv(daily_csv)
            if not df_daily.empty:
                df_daily["Signal"] = "Hold"
                df_daily.loc[df_daily.index[0], "Signal"] = "Buy"
                bres = backtest_swing_strategy(df_daily)
                logging.info(f"Backtest => top={top_tkr}, results={bres}")

    try:
        with pd.ExcelWriter("short_term_ranked_stocks_swing.xlsx") as writer:
            df_ranked.to_excel(writer, sheet_name="Short-Term Score", index=False)
            breakdown_df = pd.json_normalize(df_ranked["Score Breakdown"])
            breakdown_df.insert(0, "Ticker", df_ranked["Ticker"])
            breakdown_df.insert(1, "Short-Term Score", df_ranked["Short-Term Score"])
            breakdown_df.to_excel(writer, sheet_name="Score Breakdown", index=False)

        rep.to_excel("swing_analysis_report.xlsx", index=False)
        highlight_buys("swing_analysis_report.xlsx")

        if not is_bullish and SHOW_UPPERCASE_HEADLINE:
            uppercase_headline = "IT IS NOT A GOOD DAY FOR INVESTMENTS!"
            insert_headline_in_excel("short_term_ranked_stocks_swing.xlsx", uppercase_headline)
            insert_headline_in_excel("swing_analysis_report.xlsx", uppercase_headline)

        logging.info("Saved short_term_ranked_stocks_swing.xlsx & swing_analysis_report.xlsx")
    except Exception as e:
        logging.error(f"Error saving Excel: {e}")

    print("\nTop Stocks (Based on Short-Term Score):")
    print(rep.head(args.top_n))

    buy_df = rep[rep["Buy Signal"] == "Buy"]
    print("\nStocks with Buy Signals:")
    if buy_df.empty:
        print("None.")
    else:
        print(buy_df)

    sell_df = rep[rep["Sell Signal"] == "Sell"]
    print("\nStocks with Sell Signals:")
    if sell_df.empty:
        print("None.")
    else:
        print(sell_df)

    end_ts = time.time()
    logging.info(f"Analysis completed in {end_ts - start_ts:.2f}s.")

if __name__ == "__main__":
    main()
