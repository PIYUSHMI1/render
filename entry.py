#COMPLET PASS
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from ta.momentum import StochRSIIndicator
import logging
import time

# Configure logging
logging.basicConfig(
    filename='eurusd_trade_log.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Login credentials
ACCOUNT = 24440252  # Replace with your MT5 account number
PASSWORD = "ajtuZEIH~_06"  # Replace with your MT5 account password
SERVER = "FivePercentOnline-Real"  # Replace with your broker's server name

# Connect to MT5
if not mt5.initialize():
    logging.error(f"MetaTrader5 initialization failed: {mt5.last_error()}")
    print("MetaTrader5 initialization failed.")
    quit()

# Login to account
if not mt5.login(ACCOUNT, password=PASSWORD, server=SERVER):
    logging.error(f"Login failed: {mt5.last_error()}")
    print("Login failed. Check your credentials.")
    mt5.shutdown()
    quit()

print(f"Logged in to account #{ACCOUNT}")
logging.info(f"Logged in to account #{ACCOUNT}")

# Constants
SYMBOL = "EURUSD"
TIMEFRAME = mt5.TIMEFRAME_M1  # 1-minute timeframe
RISK_PERCENT = 0.0003  # Risk 0.25% of balance
TP_MULTIPLIER = 20  # Take-profit multiplier
WINDOW = 20  # Bollinger Bands window
STD_DEV = 2  # Bollinger Bands standard deviation

# Helper functions
def fetch_data(symbol, timeframe, n_candles):
    """Fetches historical data."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_candles)
    if rates is None:
        logging.error(f"Failed to fetch data for {symbol}")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def calculate_indicators(data):
    """Calculates Bollinger Bands and Stochastic RSI."""
    # Bollinger Bands
    data['SMA'] = data['close'].rolling(WINDOW).mean()
    data['UpperBB'] = data['SMA'] + (data['close'].rolling(WINDOW).std() * STD_DEV)
    data['LowerBB'] = data['SMA'] - (data['close'].rolling(WINDOW).std() * STD_DEV)

    # Stochastic RSI
    stoch_rsi = StochRSIIndicator(data['close'], window=14, smooth1=3, smooth2=3)
    data['StochRSI_K'] = stoch_rsi.stochrsi_k()
    data['StochRSI_D'] = stoch_rsi.stochrsi_d()

    return data

def get_valid_volume(symbol, calculated_volume):
    """Adjusts the volume to meet the symbol's trading specifications."""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        logging.error(f"Symbol info not found for {symbol}")
        return None

    volume_min = symbol_info.volume_min
    volume_max = symbol_info.volume_max
    volume_step = symbol_info.volume_step

    valid_volume = max(volume_min, min(volume_max, calculated_volume))
    valid_volume = round(valid_volume / volume_step) * volume_step  # Adjust to nearest step

    return valid_volume

def place_order(symbol, trade_type, lot, entry_price, primary_sl, secondary_sl, tp):
    """Places a market order with a protective stop-loss."""
    valid_lot = get_valid_volume(symbol, lot)
    if valid_lot is None:
        print(f"Invalid volume for {symbol}.")
        return

    # Retrieve symbol info for price precision
    symbol_info = mt5.symbol_info(symbol)
    digits = symbol_info.digits
    point = symbol_info.point

    sl_price = round(primary_sl, digits)
    tp_price = round(tp, digits)
    secondary_sl_price = round(secondary_sl, digits)

    order_type = mt5.ORDER_TYPE_BUY if trade_type == "Long" else mt5.ORDER_TYPE_SELL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": valid_lot,
        "type": order_type,
        "price": entry_price,
        "sl": secondary_sl_price,
        "tp": tp_price,
        "deviation": 10,  # Price deviation allowed
        "magic": 234000,  # Unique ID for the order
        "comment": f"{trade_type} trade",
    }

    print(f"Order Request: {request}")  # Debugging
    result = mt5.order_send(request)

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order failed: {result.retcode}, {result}")
        logging.error(f"Order failed: {result.retcode}, {result}")
    else:
        print(f"Order placed: {trade_type}, Entry={entry_price}, SL={primary_sl}, TP={tp}, Volume={valid_lot}")
        logging.info(f"Order placed: {trade_type}, Entry={entry_price}, SL={primary_sl}, TP={tp}, Volume={valid_lot}")

# Add a dictionary to track the last executed trade
last_trade = {
    "timestamp": None,  # Timestamp of the last executed trade
    "type": None        # Type of the trade ("Long" or "Short")
}

# Trading loop
while True:
    # Fetch the latest data
    data = fetch_data(SYMBOL, TIMEFRAME, 100)
    if data is None or len(data) < WINDOW:
        continue
    data = calculate_indicators(data)

    # Current balance
    account_info = mt5.account_info()
    if account_info is None:
        logging.error("Failed to fetch account info.")
        break
    balance = account_info.balance

    # Analyze the last complete candle (second to last row in the data)
    last_candle = data.iloc[-2]
    next_candle = data.iloc[-1]

    entry_price = next_candle['open']
    trade_type, primary_sl, secondary_sl, take_profit = None, None, None, None

    # Long condition
    if (
        last_candle['low'] <= last_candle['LowerBB'] and
        last_candle['StochRSI_K'] > last_candle['StochRSI_D'] and
        last_candle['close'] > last_candle['open']  # Bullish close
    ):
        trade_type = "Long"
        primary_sl = last_candle['low']
        secondary_sl = entry_price - 10 * (entry_price - primary_sl)
        take_profit = entry_price + TP_MULTIPLIER * (entry_price - primary_sl)

    # Short condition
    elif (
        last_candle['high'] >= last_candle['UpperBB'] and
        last_candle['StochRSI_K'] < last_candle['StochRSI_D'] and
        last_candle['close'] < last_candle['open']  # Bearish close
    ):
        trade_type = "Short"
        primary_sl = last_candle['high']
        secondary_sl = entry_price + 10 * (primary_sl - entry_price)
        take_profit = entry_price - TP_MULTIPLIER * (primary_sl - entry_price)

    # Ensure no duplicate trades are placed
    if trade_type and primary_sl is not None and secondary_sl is not None:
        # Check if the same trade has already been executed
        if (
            last_trade["timestamp"] != last_candle['time'] or
            last_trade["type"] != trade_type
        ):
            risk_amount = balance * RISK_PERCENT
            stop_loss_pct = abs(entry_price - primary_sl) / entry_price
            position_size = risk_amount / (stop_loss_pct * 100000)  # Position size in lots
            position_size = get_valid_volume(SYMBOL, position_size)

            if position_size > 0:
                # Place the trade
                place_order(SYMBOL, trade_type, position_size, entry_price, primary_sl, secondary_sl, take_profit)

                # Update last trade tracker
                last_trade["timestamp"] = last_candle['time']
                last_trade["type"] = trade_type

    time.sleep(0.10)  # Wait for the next update


