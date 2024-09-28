import yfinance as yf
import csv
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple
import argparse
from pathlib import Path
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("stock_data_fetcher.log"),
        logging.StreamHandler()
    ]
)

def get_all_nse_tickers_from_txt(filename: str = 'nse_tickers.txt') -> List[str]:
    """
    Fetches all NSE stock tickers from a text file (one ticker per line).

    Args:
        filename (str): Path to the text file containing tickers.

    Returns:
        List[str]: List of NSE tickers formatted for Yahoo Finance.
    """
    tickers = []
    file_path = Path(filename)
    if not file_path.is_file():
        logging.error(f"File {filename} not found. Please ensure the file exists.")
        return tickers

    # Define a regex pattern to allow uppercase letters, numbers, hyphens, and ampersands
    pattern = re.compile(r'^[A-Z0-9&\-]+$')

    try:
        with file_path.open('r', encoding='utf-8') as file:
            for line in file:
                ticker = line.strip().upper()  # Normalize to uppercase
                if ticker and pattern.match(ticker):
                    formatted_ticker = f"{ticker}.NS"
                    tickers.append(formatted_ticker)
                elif ticker:
                    logging.warning(f"Invalid ticker format skipped: '{ticker}'")
    except Exception as e:
        logging.error(f"Error reading {filename}: {e}")

    logging.info(f"Total tickers fetched from file: {len(tickers)}")
    return tickers

def fetch_single_stock_data(ticker: str, retries: int = 3, timeout: int = 10) -> Tuple[str, float]:
    """
    Fetches the current price for a single ticker with retry mechanism.

    Args:
        ticker (str): The stock ticker symbol.
        retries (int): Number of retries in case of failure.
        timeout (int): Timeout for each request in seconds.

    Returns:
        Tuple[str, float]: Tuple containing ticker and its current price.
                           Returns (ticker, None) if data is invalid.
    """
    for attempt in range(1, retries + 1):
        try:
            logging.debug(f"Attempt {attempt} for ticker {ticker}")
            stock = yf.Ticker(ticker)
            stock_info = stock.history(period="1d", timeout=timeout)

            if not stock_info.empty:
                current_price = stock_info['Close'].iloc[-1]
                logging.info(f"Fetched data for {ticker}: {current_price}")
                return ticker, current_price
            else:
                logging.warning(f"No data found for {ticker}.")
                return ticker, None
        except Exception as e:
            logging.error(f"Error fetching data for {ticker} on attempt {attempt}: {e}")
            if attempt < retries:
                wait_time = 2 ** attempt  # Exponential backoff
                logging.info(f"Retrying after {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logging.error(f"Failed to fetch data for {ticker} after {retries} attempts.")
                return ticker, None

def fetch_stock_data(tickers: List[str], max_workers: int = 10) -> Tuple[List[Tuple[str, float]], List[str]]:
    """
    Fetches stock data (current price) for a list of stock symbols using concurrent threads.

    Args:
        tickers (List[str]): List of stock tickers.
        max_workers (int): Maximum number of threads to use.

    Returns:
        Tuple[List[Tuple[str, float]], List[str]]: 
            - List of tuples containing ticker and current price.
            - List of valid tickers with valid price data.
    """
    stock_data = []
    valid_tickers = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(fetch_single_stock_data, ticker): ticker for ticker in tickers}
        total = len(tickers)
        for i, future in enumerate(as_completed(future_to_ticker), 1):
            ticker = future_to_ticker[future]
            try:
                ticker, price = future.result()
                if price is not None:
                    stock_data.append((ticker, price))
                    valid_tickers.append(ticker)
            except Exception as e:
                logging.error(f"Unhandled exception for {ticker}: {e}")
            if i % 100 == 0 or i == total:
                logging.info(f"Processed {i}/{total} tickers.")

    logging.info(f"Total valid tickers fetched: {len(valid_tickers)}")
    return stock_data, valid_tickers

def save_to_csv(stock_data: List[Tuple[str, float]], filename: str = 'nse_stocks.csv') -> None:
    """
    Saves the stock data into a CSV file.

    Args:
        stock_data (List[Tuple[str, float]]): List of stock data tuples.
        filename (str): Output CSV file name.
    """
    headers = ['SYMBOL', 'CURRENT_PRICE']
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(stock_data)
        logging.info(f"Data saved to {filename}")
    except Exception as e:
        logging.error(f"Error saving data to {filename}: {e}")

def save_valid_tickers_to_txt(valid_tickers: List[str], filename: str = 'valid_nse_tickers.txt') -> None:
    """
    Saves the list of valid tickers to a text file.

    Args:
        valid_tickers (List[str]): List of valid stock tickers.
        filename (str): Output text file name.
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            for ticker in valid_tickers:
                f.write(f"{ticker.replace('.NS', '')}\n")
        logging.info(f"Valid tickers saved to {filename}")
    except Exception as e:
        logging.error(f"Error saving valid tickers to {filename}: {e}")

def parse_arguments() -> argparse.Namespace:
    """
    Parses command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Fetch NSE stock data using Yahoo Finance.")
    parser.add_argument(
        '--input',
        type=str,
        default='nse_tickers.txt',
        help='Input file containing NSE tickers (one per line). Default: nse_tickers.txt'
    )
    parser.add_argument(
        '--output_csv',
        type=str,
        default='nse_stocks.csv',
        help='Output CSV file name. Default: nse_stocks.csv'
    )
    parser.add_argument(
        '--output_valid',
        type=str,
        default='valid_nse_tickers.txt',
        help='Output text file for valid tickers. Default: valid_nse_tickers.txt'
    )
    parser.add_argument(
        '--max_workers',
        type=int,
        default=10,
        help='Maximum number of concurrent threads. Default: 10'
    )
    return parser.parse_args()

def main():
    args = parse_arguments()

    # Get all NSE tickers from a text file
    nse_tickers = get_all_nse_tickers_from_txt(args.input)

    if not nse_tickers:
        logging.error("No valid tickers found. Exiting.")
        return

    # Fetch stock data for all tickers and get the valid tickers
    stock_data, valid_tickers = fetch_stock_data(nse_tickers, max_workers=args.max_workers)

    if stock_data:
        # Save the stock data to a CSV file
        save_to_csv(stock_data, args.output_csv)
    else:
        logging.warning("No stock data fetched to save.")

    if valid_tickers:
        # Save the valid tickers to a new text file
        save_valid_tickers_to_txt(valid_tickers, args.output_valid)
    else:
        logging.warning("No valid tickers to save.")

if __name__ == '__main__':
    main()
