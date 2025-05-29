import telebot

# --- Thông tin của bạn (đã điền sẵn) ---
BOT_TOKEN = "6998091887:AAGSOlC-XXXXXXXXXXXXXXXXXXXXXXX"
CHANNEL_ID = -1002123456789  # Thay bằng ID thật của bạn nếu khác

# --- Khởi tạo bot ---
bot = telebot.TeleBot(BOT_TOKEN)

# --- Xử lý lệnh /start ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🤖 Bot Telegram cảnh báo AI đã hoạt động thành công trên Render!")

# --- Phản hồi mọi tin nhắn ---
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"Bạn vừa gửi: {message.text}")

# --- Hàm gửi cảnh báo đến kênh ---
def send_channel_alert(text):
    try:
        bot.send_message(CHANNEL_ID, text)
    except Exception as e:
        print(f"Lỗi khi gửi tin nhắn: {e}")

# --- Điểm bắt đầu bot ---
if __name__ == '__main__':
    print("🚀 Bot đang chạy polling...")
    bot.polling(non_stop=True)
