import pandas as pd
from datetime import date
from jugaad_data.nse import stock_df, bhavcopy_save, bhavcopy_fo_save
import time

def main():
    # Download bhavcopy for reference (optional)
    # bhavcopy_save(date(2020,1,1), ".")
    # bhavcopy_fo_save(date(2020,1,1), ".")

    # List of sample stock symbols; you can extend this list or fetch from a file
    stock_symbols = [
        "INFY", "HDFC","RELIANCE", "TCS", "SBIN", "ICICIBANK", "HINDUNILVR", "ITC", "KOTAKBANK", "BHARTIARTL", "AXISBANK", "LT", "BAJFINANCE", "HCLTECH", "ASIANPAINT", "ADANIENT", "TATAMOTORS", "WIPRO", "MARUTI", "ONGC", "ULTRACEMCO", "TATASTEEL", "SUNPHARMA", "HDFCLIFE", "JSWSTEEL", "NTPC", "POWERGRID", "TECHM", "NESTLEIND", "DIVISLAB", "INDUSINDBK", "HDFCBANK", "BRITANNIA", "COALINDIA", "GRASIM", "HEROMOTOCO", "APOLLOHOSP", "M&M", "BAJAJFINSV", "CIPLA", "DRREDDY", "BPCL", "EICHERMOT", "TITAN", "TATACONSUM", "UPL", "SBILIFE", "ADANIPORTS", "SHREECEM", "DABUR", "HAVELLS", "VOLTAS", "PIDILITIND", "TATAELXSI", "NYKAA", "ZOMATO", "IRCTC", "DMART", "BAJAJ-AUTO", "SIEMENS", "LUPIN", "BOSCHLTD", "COLPAL", "MINDTREE", "ICICIPRULI", "LICI", "GODREJCP", "INDIGO", "HINDZINC", "AMBUJACEM", "IOC", "GLENMARK", "BHEL", "CANBK", "PEL", "BEL", "MANAPPURAM", "ASHOKLEY", "IDFCFIRSTB", "TATACOMM", "MOTHERSON", "MRF", "SUNTV", "ESCORTS", "JUBLFOOD", "PNB", "SAIL", "IDEA", "TRENT", "GUJGASLTD", "IRFC", "YESBANK", "TATAPOWER", "GAIL", "ADANIGREEN", "NHPC", "ADANITRANS", "SRF", "ALKEM", "HDFCAMC", "CHOLAFIN", "NAUKRI", "MUTHOOTFIN", "INDHOTEL", "TORNTPHARM",
        # Add more stock symbols here
    ]

    # Define the date range for 5 years
    start_date = date(2019, 9, 23)  # Adjust as needed
    end_date = date.today()

    all_data = {}

    for symbol in stock_symbols:
        try:
            print(f"Downloading data for {symbol}...")
            data = stock_df(symbol=symbol, from_date=start_date, to_date=end_date, series="EQ")
            all_data[symbol] = data
            time.sleep(1)  # Sleep to avoid rate limiting
        except Exception as e:
            print(f"Could not download data for {symbol}: {e}")

    # Save data to Excel
    with pd.ExcelWriter('market_data.xlsx', engine='openpyxl') as writer:
        for symbol, data in all_data.items():
            data.to_excel(writer, sheet_name=symbol[:30])  # Limit sheet name to 30 characters

    print("Data download complete. Saved to market_data.xlsx.")

if __name__ == "__main__":
    main()
