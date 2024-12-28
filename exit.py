#complet pass
import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

# Initialize MetaTrader 5
mt5.initialize()

# Global cache to store SL levels to avoid recalculations
sl_cache = {}

def calculate_sl_levels():
    """
    Automatically calculates stop-loss levels for open positions
    based on the previous completed 1-minute candle's high or low.
    Returns a dictionary of SL levels with position tickets as keys.
    """
    positions = mt5.positions_get()
    sl_levels = {}

    if positions is None or len(positions) == 0:
        print("No open positions.")
        return sl_levels  # Return empty if no positions

    for position in positions:
        symbol = position.symbol
        ticket = position.ticket

        # Skip recalculating SL for positions that already have it cached
        if ticket in sl_cache:
            print(f"Using cached SL for position {ticket} ({symbol}): {sl_cache[ticket]}")
            sl_levels[ticket] = sl_cache[ticket]
            continue

        # Fetch the last two completed M1 candles (timeframe M1)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, 2)  # Fetch last 2 completed candles

        if rates is None or len(rates) < 2:
            print(f"Failed to retrieve candle data for {symbol}")
            continue

        # Convert rates to DataFrame for easier processing
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')

        # Get the low/high of the previous completed candle (the one before the last completed one)
        prev_candle = df.iloc[-1]  # The second to last completed candle
        prev_candle_low = prev_candle['low']
        prev_candle_high = prev_candle['high']

        # Set stop-loss based on position type (long or short)
        if position.type == mt5.ORDER_TYPE_BUY:  # Long position
            sl_price = prev_candle_low  # SL at the low of the previous completed candle
        elif position.type == mt5.ORDER_TYPE_SELL:  # Short position
            sl_price = prev_candle_high  # SL at the high of the previous completed candle

        # Log details for debugging
        print(f"Previous completed candle for {symbol}:")
        print(f"Time: {prev_candle['time']}, Low: {prev_candle_low}, High: {prev_candle_high}")
        print(f"Calculated SL for position {ticket} ({symbol}): {sl_price}")

        # Store the calculated SL in the cache to avoid recalculating next time
        sl_cache[ticket] = sl_price
        sl_levels[ticket] = sl_price

    return sl_levels

def calculate_sleep_duration():
    """
    Calculates the remaining time until the next candle closes based on the server time.
    """
    # Get the current server time from a symbol's tick
    symbol_info = mt5.symbol_info_tick("EURUSD")  # Replace "EURUSD" with any active symbol you are monitoring
    if symbol_info is None:
        print("Failed to retrieve server time from MetaTrader 5.")
        return 60  # Default to 60 seconds if the server time is unavailable

    server_time = datetime.fromtimestamp(symbol_info.time, timezone.utc)
    next_candle_time = (server_time + timedelta(minutes=1)).replace(second=0, microsecond=0)
    sleep_duration = (next_candle_time - server_time).total_seconds()

    return max(sleep_duration, 1)  # Ensure at least 1 second sleep to avoid immediate looping

def monitor_exit_conditions():
    """
    Monitors open positions and exits based on Stop-Loss conditions
    for each position.
    """
    while True:
        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            print("No open positions.")
        else:
            for position in positions:
                ticket = position.ticket
                symbol = position.symbol
                tick = mt5.symbol_info_tick(symbol)

                if tick is None:
                    print(f"Failed to retrieve tick data for {symbol}.")
                    continue

                close_price = tick.ask if position.type == mt5.ORDER_TYPE_BUY else tick.bid

                # Check if position's SL is cached
                if ticket not in sl_cache:
                    print(f"No SL cached for position {ticket} ({symbol}). Calculating SL...")
                    sl_levels = calculate_sl_levels()
                    if ticket not in sl_levels:
                        continue
                sl_price = sl_cache[ticket]  # Use cached SL price

                # Exit logic: Close if the current price is below (for long) or above (for short) SL
                if position.type == mt5.ORDER_TYPE_BUY and close_price < sl_price:  # Long position
                    print(f"Exiting long position {ticket} as close price {close_price} < SL {sl_price}")
                    close_position(position)
                elif position.type == mt5.ORDER_TYPE_SELL and close_price > sl_price:  # Short position
                    print(f"Exiting short position {ticket} as close price {close_price} > SL {sl_price}")
                    close_position(position)

        # Calculate remaining time until the next candle close
        sleep_duration = calculate_sleep_duration()
        print(f"Sleeping for {sleep_duration:.2f} seconds until the next candle closes.")
        time.sleep(sleep_duration)

def close_position(position):
    """
    Closes the position using a market order (buy/sell).
    """
    symbol = position.symbol
    ticket = position.ticket

    tick = mt5.symbol_info_tick(symbol)

    if tick is None:
        print(f"Failed to retrieve tick data for {symbol}. Cannot close position {ticket}.")
        return

    if position.type == mt5.ORDER_TYPE_BUY:  # Closing long position
        action_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    elif position.type == mt5.ORDER_TYPE_SELL:  # Closing short position
        action_type = mt5.ORDER_TYPE_BUY
        price = tick.ask

    # Prepare order request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": ticket,
        "symbol": symbol,
        "volume": position.volume,
        "type": action_type,
        "price": price,
        "deviation": 20,
        "magic": 100,
        "comment": "Python script close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Failed to close position {ticket}. Error code: {result.retcode}")
    else:
        print(f"Position {ticket} closed successfully.")

# Run the monitoring function
monitor_exit_conditions()

# Shutdown MetaTrader 5 after execution #piyush
mt5.shutdown()
