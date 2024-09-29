import requests
import pandas as pd

API_KEY = 'YOUR_API_KEY'

# Read tickers from 'valid_nse_symbols.txt'
with open('valid_nse_tickers.txt', 'r') as file:
    tickers = [line.strip() for line in file if line.strip()]

for ticker in tickers:
    print(f"Fetching data for {ticker}...")
    try:
        # Income Statement
        income_url = f'https://financialmodelingprep.com/api/v3/income-statement/{ticker}?apikey={API_KEY}&limit=120'
        income_response = requests.get(income_url)
        income_data = income_response.json()
        if not isinstance(income_data, list) or 'Error Message' in income_data:
            print(f"No income data found for {ticker}.")
            continue
        income_df = pd.DataFrame(income_data)
        
        # Balance Sheet
        balance_url = f'https://financialmodelingprep.com/api/v3/balance-sheet-statement/{ticker}?apikey={API_KEY}&limit=120'
        balance_response = requests.get(balance_url)
        balance_data = balance_response.json()
        if not isinstance(balance_data, list) or 'Error Message' in balance_data:
            print(f"No balance sheet data found for {ticker}.")
            continue
        balance_df = pd.DataFrame(balance_data)
        
        # Ratios
        ratios_url = f'https://financialmodelingprep.com/api/v3/ratios/{ticker}?apikey={API_KEY}&limit=120'
        ratios_response = requests.get(ratios_url)
        ratios_data = ratios_response.json()
        if not isinstance(ratios_data, list) or 'Error Message' in ratios_data:
            print(f"No ratios data found for {ticker}.")
            continue
        ratios_df = pd.DataFrame(ratios_data)
        
        # Save to Excel
        with pd.ExcelWriter(f'{ticker}_financials.xlsx') as writer:
            income_df.to_excel(writer, sheet_name='Income Statement', index=False)
            balance_df.to_excel(writer, sheet_name='Balance Sheet', index=False)
            ratios_df.to_excel(writer, sheet_name='Financial Ratios', index=False)
        print(f"Data for {ticker} saved successfully.")
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
