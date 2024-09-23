import pandas as pd
import yfinance as yf
from newsapi import NewsApiClient
from alpha_vantage.timeseries import TimeSeries
import finnhub
from iexfinance.stocks import Stock
from tiingo import TiingoClient
import pandas_datareader.data as web
import datetime
import time

# ============================
# Replace the placeholders below with your actual API keys
# ============================

ALPHA_VANTAGE_API_KEY = 'YOUR_ALPHA_VANTAGE_API_KEY'
NEWSAPI_API_KEY = 'YOUR_NEWSAPI_API_KEY'
FINNHUB_API_KEY = 'YOUR_FINNHUB_API_KEY'
IEX_CLOUD_API_KEY = 'YOUR_IEX_CLOUD_API_KEY'
TIINGO_API_KEY = 'YOUR_TIINGO_API_KEY'
NASDAQ_DATA_LINK_API_KEY = 'YOUR_NASDAQ_DATA_LINK_API_KEY'

# ============================
# Functions to Fetch Data from Various APIs
# ============================

def get_yahoo_finance_data(tickers):
    """
    Fetch historical stock data using yfinance.
    """
    print("Fetching data from Yahoo Finance...")
    data = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="max")
            if df.empty:
                print(f"No data found for {ticker}.")
                continue
            df.reset_index(inplace=True)
            # Remove timezone info from 'Date' column
            if 'Date' in df.columns:
                df['Date'] = df['Date'].dt.tz_localize(None)
            df['Ticker'] = ticker
            data[ticker] = df
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
    return data

def get_alpha_vantage_data(tickers):
    """
    Fetch historical stock data using Alpha Vantage.
    """
    print("Fetching data from Alpha Vantage...")
    ts = TimeSeries(key=ALPHA_VANTAGE_API_KEY, output_format='pandas')
    data = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        try:
            df, meta_data = ts.get_daily(symbol=ticker, outputsize='full')
            df.reset_index(inplace=True)
            # Remove timezone info from 'date' column
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            df['Ticker'] = ticker
            data[ticker] = df
            time.sleep(12)  # Respect API rate limits
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
    return data

def get_finnhub_data(tickers):
    """
    Fetch stock data using Finnhub API.
    """
    print("Fetching data from Finnhub...")
    finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
    data = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        try:
            # Finnhub expects the stock symbol without exchange suffix
            # Example: 'RELIANCE.NS' remains the same
            res = finnhub_client.stock_candles(ticker, 'D', 0, int(time.time()))
            if res['s'] != 'ok':
                print(f"No data found for {ticker}.")
                continue
            df = pd.DataFrame(res)
            df['t'] = pd.to_datetime(df['t'], unit='s')
            df.rename(columns={'t': 'Date'}, inplace=True)
            df['Ticker'] = ticker
            data[ticker] = df
            time.sleep(1)  # Respect API rate limits
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
    return data

def get_iex_cloud_data(tickers):
    """
    Fetch stock data using IEX Cloud API.
    Note: IEX Cloud primarily supports US stocks.
    """
    print("Fetching data from IEX Cloud...")
    data = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        try:
            stock = Stock(ticker, token=IEX_CLOUD_API_KEY)
            df = stock.get_chart(range='max')
            if df.empty:
                print(f"No data found for {ticker}.")
                continue
            df.reset_index(inplace=True)
            # Remove timezone info from 'date' column
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            df['Ticker'] = ticker
            data[ticker] = df
            time.sleep(0.1)  # Respect API rate limits
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
    return data

def get_tiingo_data(tickers):
    """
    Fetch historical stock data using Tiingo API.
    """
    print("Fetching data from Tiingo...")
    config = {'session': True, 'api_key': TIINGO_API_KEY}
    client = TiingoClient(config)
    data = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        try:
            df = client.get_dataframe(ticker,
                                      frequency='daily',
                                      metric_name='adjClose',
                                      startDate='2000-01-01',
                                      endDate=datetime.datetime.now().strftime('%Y-%m-%d'))
            df.reset_index(inplace=True)
            # Remove timezone info from 'date' column
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            df['Ticker'] = ticker
            data[ticker] = df
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
    return data

def get_nasdaq_data(tickers):
    """
    Fetch historical stock data using Nasdaq Data Link (formerly Quandl).
    """
    print("Fetching data from Nasdaq Data Link...")
    data = {}
    for ticker in tickers:
        print(f"Fetching data for {ticker}...")
        try:
            # The ticker format for Nasdaq Data Link may vary; adjust accordingly
            # Example: 'BSE/BOM500325' for Reliance Industries
            df = web.DataReader(ticker, 'quandl', start='2000-01-01', api_key=NASDAQ_DATA_LINK_API_KEY)
            df.reset_index(inplace=True)
            # Remove timezone info from 'Date' column
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date']).dt.tz_localize(None)
            df['Ticker'] = ticker
            data[ticker] = df
        except Exception as e:
            print(f"Error fetching data for {ticker}: {e}")
    return data

def get_market_news(keywords, from_date=None, to_date=None, language='en', page_size=100):
    """
    Fetch market news using NewsAPI.org.
    """
    print("Fetching market news...")
    try:
        newsapi = NewsApiClient(api_key=NEWSAPI_API_KEY)
    except Exception as e:
        print(f"Error initializing NewsAPI client: {e}")
        return pd.DataFrame()

    all_articles = []
    for keyword in keywords:
        print(f"Fetching news for keyword: {keyword}...")
        try:
            articles = newsapi.get_everything(q=keyword,
                                              from_param=from_date,
                                              to=to_date,
                                              language=language,
                                              sort_by='publishedAt',
                                              page_size=page_size)
            if articles['status'] != 'ok':
                print(f"Error fetching news for {keyword}: {articles.get('message', 'Unknown error')}")
                continue
            for article in articles['articles']:
                article['Keyword'] = keyword
                all_articles.append(article)
            time.sleep(1)  # Respect API rate limits
        except Exception as e:
            print(f"Error fetching news for {keyword}: {e}")
    df = pd.DataFrame(all_articles)
    return df

# ============================
# Main Function
# ============================

def main():
    # Define the tickers and keywords you are interested in
    tickers_yahoo = ['RELIANCE.NS', 'TCS.NS', '^NSEI']  # Yahoo Finance tickers for Indian stocks and index
    tickers_alpha = ['RELIANCE.BSE', 'TCS.BSE']         # Alpha Vantage tickers for Indian stocks
    tickers_finnhub = ['RELIANCE.NS', 'TCS.NS']        # Finnhub uses Yahoo Finance symbols
    tickers_iex = ['AAPL', 'MSFT']                      # IEX Cloud primarily supports US stocks
    tickers_tiingo = ['AAPL', 'MSFT']                   # Tiingo primarily supports US stocks
    tickers_nasdaq = ['BSE/BOM500325', 'BSE/BOM532540']  # Nasdaq Data Link tickers for Indian stocks (example)

    keywords = ['Stock Market', 'NSE India', 'Sensex', 'Nifty 50']

    # Create a Pandas Excel writer using OpenPyXL as the engine within a context manager
    with pd.ExcelWriter('Market_Data.xlsx', engine='openpyxl') as writer:
        # Fetch data from Yahoo Finance
        yahoo_data = get_yahoo_finance_data(tickers_yahoo)
        for ticker, df in yahoo_data.items():
            sheet_name = f'Yahoo_{ticker.replace(".NS", "").replace("^", "")}'
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Data for {ticker} written to sheet '{sheet_name}'.")

        # Fetch data from Alpha Vantage
        alpha_data = get_alpha_vantage_data(tickers_alpha)
        for ticker, df in alpha_data.items():
            sheet_name = f'AlphaVantage_{ticker.replace(".BSE", "")}'
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Data for {ticker} written to sheet '{sheet_name}'.")

        # Fetch data from Finnhub
        finnhub_data = get_finnhub_data(tickers_finnhub)
        for ticker, df in finnhub_data.items():
            sheet_name = f'Finnhub_{ticker.replace(".NS", "")}'
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Data for {ticker} written to sheet '{sheet_name}'.")

        # Fetch data from IEX Cloud (if applicable)
        iex_data = get_iex_cloud_data(tickers_iex)
        for ticker, df in iex_data.items():
            sheet_name = f'IEX_{ticker}'
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Data for {ticker} written to sheet '{sheet_name}'.")

        # Fetch data from Tiingo (if applicable)
        tiingo_data = get_tiingo_data(tickers_tiingo)
        for ticker, df in tiingo_data.items():
            sheet_name = f'Tiingo_{ticker}'
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Data for {ticker} written to sheet '{sheet_name}'.")

        # Fetch data from Nasdaq Data Link (formerly Quandl) (if applicable)
        nasdaq_data = get_nasdaq_data(tickers_nasdaq)
        for ticker, df in nasdaq_data.items():
            sheet_name = f'Nasdaq_{ticker.replace("BSE/", "")}'
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"Data for {ticker} written to sheet '{sheet_name}'.")

        # Fetch market news
        news_df = get_market_news(keywords)
        if not news_df.empty:
            # Remove timezone info from 'publishedAt' column
            if 'publishedAt' in news_df.columns:
                news_df['publishedAt'] = pd.to_datetime(news_df['publishedAt']).dt.tz_localize(None)
            news_df.to_excel(writer, sheet_name='Market_News', index=False)
            print("Market news written to sheet 'Market_News'.")
        else:
            print("No market news data fetched.")

    print("All data has been written to 'Market_Data.xlsx'.")

# ============================
# Entry Point
# ============================

if __name__ == "__main__":
    main()
