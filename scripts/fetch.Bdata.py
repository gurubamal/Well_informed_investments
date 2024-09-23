import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import time
from io import StringIO
import warnings

# Suppress warnings
warnings.filterwarnings('ignore')

# Function to get NSE Live Equity Market Data
def get_nse_live_equity_market():
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/market-data/live-equity-market",
    }

    # Get cookies
    session.get("https://www.nseindia.com", headers=headers, timeout=5)
    time.sleep(1)  # Wait for a second

    # Fetch live equity data
    url = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
    response = session.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        print(f"Failed to fetch data. Status code: {response.status_code}")
        print("Response text:", response.text)
        response.raise_for_status()

    try:
        data = response.json()
        # Extract the data
        if 'data' in data:
            df = pd.DataFrame(data['data'])
            return df
        else:
            raise KeyError("Expected key 'data' not found in the JSON response.")
    except Exception as e:
        print("An error occurred while processing the data:", e)
        raise

# Function to get option chain data from NSE India
def get_nse_option_chain(symbol='NIFTY'):
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/option-chain",
    }

    # Get cookies
    session.get("https://www.nseindia.com", headers=headers, timeout=5)
    time.sleep(1)  # Wait for a second

    # Fetch option chain data
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    response = session.get(url, headers=headers, timeout=10)
    if response.status_code != 200:
        print(f"Failed to fetch option chain data. Status code: {response.status_code}")
        response.raise_for_status()
    data = response.json()

    # Process data
    records = data['records']['data']
    options = []
    for record in records:
        ce_data = record.get('CE', {})
        pe_data = record.get('PE', {})
        if ce_data:
            ce_data['Type'] = 'Call'
            options.append(ce_data)
        if pe_data:
            pe_data['Type'] = 'Put'
            options.append(pe_data)
    df = pd.DataFrame(options)
    return df

# Function to get pre-open market data from NSE India
def get_nse_pre_open_market_data():
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge",
    }

    # Get cookies
    session.get("https://www.nseindia.com", headers=headers, timeout=5)
    time.sleep(1)  # Wait for a second

    # Fetch pre-open market data
    url = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"
    response = session.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        print(f"Failed to fetch pre-open market data from NSE India. Status code: {response.status_code}")
        return pd.DataFrame()

    try:
        data = response.json()
        if 'data' in data:
            df = pd.DataFrame(data['data'])
            return df
        else:
            print("No data found in pre-open market response.")
            return pd.DataFrame()
    except Exception as e:
        print("An error occurred while processing pre-open market data:", e)
        return pd.DataFrame()

# Function to get historical data from NSE India
def get_nse_historical_data():
    print("NSE India does not provide historical data via a public API. Please visit the website to download historical data manually.")
    return pd.DataFrame()

# Function to get market headlines from Moneycontrol
def get_moneycontrol_market_headlines():
    url = "https://www.moneycontrol.com/news/business/markets/"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        print(f"Failed to fetch data from Moneycontrol. Status code: {response.status_code}")
        return pd.DataFrame()

    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract market headlines
    headlines = soup.find_all('h2', class_='clearfix')

    data = []
    for headline in headlines:
        title = headline.get_text(strip=True)
        data.append({'Headline': title})

    df = pd.DataFrame(data)
    return df

# Function to get market data from Business Standard
def get_business_standard_markets():
    url = "https://www.business-standard.com/markets"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        print(f"Failed to fetch data from Business Standard. Status code: {response.status_code}")
        return pd.DataFrame()

    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract market headlines
    headlines = soup.find_all('h2', class_='listing-txt')

    data = []
    for headline in headlines:
        title = headline.get_text(strip=True)
        data.append({'Headline': title})

    df = pd.DataFrame(data)
    return df

# Function to get market data from India Infoline
def get_india_infoline_markets():
    url = "https://www.indiainfoline.com/markets"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        print(f"Failed to fetch data from India Infoline. Status code: {response.status_code}")
        return pd.DataFrame()

    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract market news headlines
    news_items = soup.find_all('div', class_='NewsHead')

    data = []
    for item in news_items:
        title = item.get_text(strip=True)
        data.append({'News': title})

    df = pd.DataFrame(data)
    return df

# Function to get market data from Reuters
def get_reuters_markets():
    url = "https://in.reuters.com/finance/markets"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        print(f"Failed to fetch data from Reuters. Status code: {response.status_code}")
        return pd.DataFrame()

    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract market headlines
    headlines = soup.find_all('h2', class_='story-title')

    data = []
    for headline in headlines:
        title = headline.get_text(strip=True)
        data.append({'Headline': title})

    df = pd.DataFrame(data)
    return df

# Function to get market data from BQ Prime
def get_bqprime_markets():
    url = "https://www.bqprime.com/markets"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)

    if response.status_code != 200:
        print(f"Failed to fetch data from BQ Prime. Status code: {response.status_code}")
        return pd.DataFrame()

    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract market news headlines
    news_items = soup.find_all('h3', class_='card-headline')

    data = []
    for item in news_items:
        title = item.get_text(strip=True)
        data.append({'News': title})

    df = pd.DataFrame(data)
    return df

# Main function to compile data
def main():
    writer = pd.ExcelWriter('Market_Data.xlsx', engine='openpyxl')

    # NSE Live Equity Market Data
    try:
        df_nse_live = get_nse_live_equity_market()
        df_nse_live.to_excel(writer, sheet_name='NSE Live Equity', index=False)
        print("NSE Live Equity Market Data fetched successfully.")
    except Exception as e:
        print(f"Failed to fetch NSE Live Equity Market Data: {e}")

    # NSE Option Chain Data
    try:
        df_option_chain = get_nse_option_chain()
        df_option_chain.to_excel(writer, sheet_name='NSE Option Chain', index=False)
        print("NSE Option Chain Data fetched successfully.")
    except Exception as e:
        print(f"Failed to fetch NSE Option Chain Data: {e}")

    # NSE Pre-Open Market Data
    try:
        df_pre_open = get_nse_pre_open_market_data()
        if not df_pre_open.empty:
            df_pre_open.to_excel(writer, sheet_name='NSE Pre-Open Market', index=False)
            print("NSE Pre-Open Market Data fetched successfully.")
        else:
            print("No data fetched from NSE Pre-Open Market.")
    except Exception as e:
        print(f"Failed to fetch NSE Pre-Open Market Data: {e}")

    # Moneycontrol Market Headlines
    try:
        df_moneycontrol = get_moneycontrol_market_headlines()
        if not df_moneycontrol.empty:
            df_moneycontrol.to_excel(writer, sheet_name='Moneycontrol Headlines', index=False)
            print("Moneycontrol Market Headlines fetched successfully.")
        else:
            print("No data fetched from Moneycontrol.")
    except Exception as e:
        print(f"Failed to fetch Moneycontrol Market Headlines: {e}")

    # Business Standard Data
    try:
        df_business_standard = get_business_standard_markets()
        if not df_business_standard.empty:
            df_business_standard.to_excel(writer, sheet_name='Business Standard', index=False)
            print("Business Standard Data fetched successfully.")
        else:
            print("No data fetched from Business Standard.")
    except Exception as e:
        print(f"Failed to fetch Business Standard Data: {e}")

    # India Infoline Data
    try:
        df_india_infoline = get_india_infoline_markets()
        if not df_india_infoline.empty:
            df_india_infoline.to_excel(writer, sheet_name='India Infoline', index=False)
            print("India Infoline Data fetched successfully.")
        else:
            print("No data fetched from India Infoline.")
    except Exception as e:
        print(f"Failed to fetch India Infoline Data: {e}")

    # Reuters Data
    try:
        df_reuters = get_reuters_markets()
        if not df_reuters.empty:
            df_reuters.to_excel(writer, sheet_name='Reuters Markets', index=False)
            print("Reuters Data fetched successfully.")
        else:
            print("No data fetched from Reuters.")
    except Exception as e:
        print(f"Failed to fetch Reuters Data: {e}")

    # BQ Prime Data
    try:
        df_bqprime = get_bqprime_markets()
        if not df_bqprime.empty:
            df_bqprime.to_excel(writer, sheet_name='BQ Prime', index=False)
            print("BQ Prime Data fetched successfully.")
        else:
            print("No data fetched from BQ Prime.")
    except Exception as e:
        print(f"Failed to fetch BQ Prime Data: {e}")

    # Close the writer
    writer.close()
    print("Data saved to Market_Data.xlsx")

if __name__ == "__main__":
    main()
