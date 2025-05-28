import os
import time
import threading
import requests
import io
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from flask import Flask
from ta.momentum import RSIIndicator
from ta.trend import MACD
from scipy.signal import argrelextrema

# --- Cấu hình ---
TELEGRAM_TOKEN = "7264977373:AAEZcqW5XL2LqLoQKbLUOKW1N0pdiGE2kFs"
TELEGRAM_CHANNEL_ID = "@botauto123"

# --- Flask server nhỏ để Render detect port mở ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Crypto Alert Bot is running"

def run_flask():
    app.run(host='0.0.0.0', port=8000)

# --- Gửi tin nhắn Telegram ---
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=payload)
        if r.status_code != 200:
            print("Telegram message failed:", r.text)
    except Exception as e:
        print("Error sending Telegram message:", e)

# --- Gửi ảnh Telegram ---
def send_telegram_photo(photo_bytes, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", photo_bytes)}
    data = {"chat_id": TELEGRAM_CHANNEL_ID, "caption": caption, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, files=files, data=data)
        if r.status_code != 200:
            print("Telegram send photo failed:", r.text)
    except Exception as e:
        print("Error sending Telegram photo:", e)

# --- Lấy dữ liệu giả định (Thay bằng API thật, ví dụ Binance) ---
def fetch_ohlcv(symbol="BTCUSDT", interval="1h", limit=200):
    """
    Lấy dữ liệu OHLCV từ Binance public API
    """
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        resp = requests.get(url)
        data = resp.json()
        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "number_of_trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ])
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit='ms')
        df.set_index("open_time", inplace=True)
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        print("Error fetching OHLCV:", e)
        return None

# --- Tính RSI và MACD ---
def add_indicators(df):
    df["rsi"] = RSIIndicator(close=df["close"], window=14).rsi()
    macd_obj = MACD(close=df["close"])
    df["macd"] = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    return df

# --- Phát hiện mô hình nêm (wedge) ---
def detect_wedge(df):
    """
    Mô hình nêm gồm 2 đường trendline dốc (xuống hoặc lên) hội tụ.
    Ở đây dùng simple approximation qua local min/max của high và low.
    """
    highs = df["high"].values
    lows = df["low"].values
    idx = np.arange(len(df))

    # Tìm local maxima và minima để lấy điểm trendline
    local_max_idx = argrelextrema(highs, np.greater, order=5)[0]
    local_min_idx = argrelextrema(lows, np.less, order=5)[0]

    if len(local_max_idx) < 2 or len(local_min_idx) < 2:
        return None  # Không đủ điểm vẽ nêm

    # Lấy 2 điểm đầu và cuối của max và min để làm trendlines
    max_points = np.array([(local_max_idx[0], highs[local_max_idx[0]]),
                           (local_max_idx[-1], highs[local_max_idx[-1]])])
    min_points = np.array([(local_min_idx[0], lows[local_min_idx[0]]),
                           (local_min_idx[-1], lows[local_min_idx[-1]])])

    # Tính hệ số góc và intercept
    def line_params(p1, p2):
        x1, y1 = p1
        x2, y2 = p2
        m = (y2 - y1) / (x2 - x1 + 1e-9)
        c = y1 - m * x1
        return m, c

    m1, c1 = line_params(max_points[0], max_points[1])  # Trendline trên
    m2, c2 = line_params(min_points[0], min_points[1])  # Trendline dưới

    # Kiểm tra nêm dốc lên hay xuống
    wedge_type = None
    if m1 < 0 and m2 < 0:
        wedge_type = "Falling Wedge"
    elif m1 > 0 and m2 > 0:
        wedge_type = "Rising Wedge"

    if wedge_type is None:
        return None

    # Kiểm tra giá đóng cửa gần break trendline trên hoặc dưới (phá nêm)
    last_idx = len(df) - 1
    last_close = df["close"].iloc[-1]

    # Giá phá lên nếu vượt trendline trên
    trendline_upper = m1 * last_idx + c1
    # Giá phá xuống nếu dưới trendline dưới
    trendline_lower = m2 * last_idx + c2

    breakout = None
    if last_close > trendline_upper:
        breakout = "breakout up"
    elif last_close < trendline_lower:
        breakout = "breakout down"

    if breakout is None:
        return None

    return {
        "type": wedge_type,
        "breakout": breakout,
        "max_points": max_points,
        "min_points": min_points,
        "trendline_upper": (m1, c1),
        "trendline_lower": (m2, c2)
    }

# --- Vẽ biểu đồ có vẽ mô hình nêm và RSI, MACD ---
def plot_chart_with_alerts(df, wedge_info=None, symbol="BTCUSDT", timeframe="1h"):
    # Vẽ biểu đồ nến
    mc = mpf.make_marketcolors(up='g', down='r', wick='i', edge='i', volume='in')
    s = mpf.make_mpf_style(marketcolors=mc)

    addplots = []

    # Vẽ RSI dưới biểu đồ chính
    rsi_plot = mpf.make_addplot(df["rsi"], panel=1, ylabel="RSI", color='blue')
    addplots.append(rsi_plot)

    # Vẽ MACD và signal dưới biểu đồ chính
    macd_plot = mpf.make_addplot(df["macd"], panel=2, color='fuchsia', ylabel="MACD")
    signal_plot = mpf.make_addplot(df["macd_signal"], panel=2, color='b')
    addplots.append(macd_plot)
    addplots.append(signal_plot)

    # Vẽ trendline nêm nếu có
    if wedge_info:
        max_pts = wedge_info["max_points"]
        min_pts = wedge_info["min_points"]

        # Tạo danh sách điểm trendline trên/dưới
        x_vals = list(range(len(df)))

        # Trendline trên (max_points)
        m1, c1 = wedge_info["trendline_upper"]
        y_upper = [m1*x + c1 for x in x_vals]
        # Trendline dưới (min_points)
        m2, c2 = wedge_info["trendline_lower"]
        y_lower = [m2*x + c2 for x in x_vals]

        # Vẽ trendlines lên biểu đồ candlestick
        # mplfinance không hỗ trợ trực tiếp vẽ trendline nên dùng annotation

        # Dùng plt vẽ lại biểu đồ với mplfinance trong figure
        fig, axes = mpf.plot(df, type='candle', style=s, addplot=addplots,
                             volume=True, returnfig=True,
                             figsize=(12,8), title=f"{symbol} {timeframe} Chart with Wedge")

        ax_main = axes[0]

        ax_main.plot(x_vals, y_upper, linestyle='--', color='orange', label='Trendline Upper')
        ax_main.plot(x_vals, y_lower, linestyle='--', color='cyan', label='Trendline Lower')

        ax_main.legend()
    else:
        # Nếu không có wedge, vẽ chart bình thường
        fig, axes = mpf.plot(df, type='candle', style=s, addplot=addplots,
                             volume=True, returnfig=True,
                             figsize=(12,8), title=f"{symbol} {timeframe} Chart")

    # Lưu ảnh vào bộ nhớ
    buf = io.BytesIO()
    fig.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return buf

# --- Kiểm tra RSI ngưỡng ---
def check_rsi_alert(df):
    alerts = []
    rsi_last = df["rsi"].iloc[-1]
    if rsi_last < 20:
        alerts.append(f"RSI oversold low: {rsi_last:.2f}")
    elif rsi_last > 80:
        alerts.append(f"RSI overbought high: {rsi_last:.2f}")
    return alerts

# --- Kiểm tra MACD cắt nhau ---
def check_macd_alert(df):
    alerts = []
    macd = df["macd"]
    signal = df["macd_signal"]
    if len(macd) < 2 or len(signal) < 2:
        return alerts

    # Xác định cắt nhau ở 2 cây nến cuối
    if macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1]:
        alerts.append("MACD bullish crossover")
    elif macd.iloc[-2] > signal.iloc[-2] and macd.iloc[-1] < signal.iloc[-1]:
        alerts.append("MACD bearish crossover")
    return alerts

# --- Hàm chính chạy bot ---
def run_bot():
    symbol = "BTCUSDT"
    intervals = ["1h", "4h"]  # Kiểm tra khung giờ 1h và 4h

    while True:
        alerts_all = []
        for interval in intervals:
            df = fetch_ohlcv(symbol, interval)
            if df is None or len(df) < 50:
                continue
            df = add_indicators(df)

            # Kiểm tra RSI alert
            alerts_all += check_rsi_alert(df)

            # Kiểm tra MACD alert (chỉ khung 4h theo yêu cầu)
            if interval == "4h":
                alerts_all += check_macd_alert(df)

            # Kiểm tra mô hình nêm trên khung 1h và 4h
            wedge = detect_wedge(df)
            if wedge:
                alerts_all.append(f"Wedge detected ({wedge['type']}) with {wedge['breakout']} at {interval}")

                # Vẽ ảnh gửi Telegram
                photo = plot_chart_with_alerts(df, wedge, symbol=symbol, timeframe=interval)
                caption = f"*{symbol}* {interval} Wedge Alert:\n" + "\n".join(alerts_all)
                send_telegram_photo(photo.read(), caption)
                # Sau khi gửi hình ảnh, xóa alerts_all để tránh gửi lại nhiều lần
                alerts_all = []

        # Nếu có alert mà chưa gửi ảnh (ví dụ RSI, MACD đơn thuần)
        if alerts_all:
            msg = f"*{symbol}* Alerts:\n" + "\n".join(alerts_all)
            send_telegram_message(msg)

        time.sleep(300)  # Chạy lại mỗi 5 phút

# --- Hàm main ---
def main():
    # Chạy Flask server trong thread để mở port 8000 cho Render
    threading.Thread(target=run_flask).start()

    # Chạy bot chính
    run_bot()

if __name__ == "__main__":
    main()
