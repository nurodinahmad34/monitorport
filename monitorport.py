import asyncio
import logging
import socket
import os
import json
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

CONFIG_FILE = 'config.json'

def load_config():
    """Membaca konfigurasi dari file JSON."""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"File {CONFIG_FILE} tidak ditemukan. Pastikan file konfigurasi ada.")
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

config = load_config()
BOT_TOKEN = config.get('BOT_TOKEN')
GROUP_CHAT_ID = config.get('GROUP_CHAT_ID')
MESSAGE_THREAD_ID = config.get('MESSAGE_THREAD_ID')
ADMIN_IDS = config.get('ADMIN_IDS', [])  # Daftar ID Telegram admin, misal [123456789]

if not all([BOT_TOKEN, GROUP_CHAT_ID, MESSAGE_THREAD_ID]):
    raise ValueError("BOT_TOKEN, GROUP_CHAT_ID, dan MESSAGE_THREAD_ID harus diisi di config.json")

SERVERS_FILE = 'servers.json'
CHECK_INTERVAL_MINUTES = 5

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
scheduler = None

def load_servers() -> list:
    """Membaca daftar server dari file JSON."""
    if os.path.exists(SERVERS_FILE):
        with open(SERVERS_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

def save_servers(servers: list):
    """Menyimpan daftar server ke file JSON."""
    with open(SERVERS_FILE, 'w') as f:
        json.dump(servers, f, indent=4)

def mask_ip(ip: str) -> str:
    """Menyensor IP, menampilkan *.* pada dua oktet pertama."""
    parts = ip.split('.')
    if len(parts) == 4:
        return f'*.{parts[2]}.{parts[3]}'
    return ip

async def check_port(ip: str, port: int, timeout: float = 5.0) -> bool:
    try:
        await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        return True
    except Exception:
        return False

async def check_all_ports(ip: str) -> dict:
    status = {}
    for port in [80, 443]:
        status[port] = await check_port(ip, port)
    return status

async def send_report(context: ContextTypes.DEFAULT_TYPE, servers_status: list):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = f"**Laporan Monitoring VPS** ({now})

"
    for server in servers_status:
        name = server['name']
        ip_masked = mask_ip(server['ip'])
        status = server['status']
        msg += f"**{name}** ({ip_masked})
"
        for port, ok in status.items():
            icon = "🟢" if ok else "🔴"
            msg += f"{icon} Port {port}: {'UP' if ok else 'DOWN'}
"
        msg += "
"
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=msg,
        parse_mode='Markdown',
        message_thread_id=MESSAGE_THREAD_ID
    )

async def monitoring_job(context: ContextTypes.DEFAULT_TYPE):
    servers = load_servers()
    if not servers:
        logger.warning("Belum ada server yang terdaftar, monitoring tidak dilakukan.")
        return
    servers_status = []
    for server in servers:
        ip = server['ip']
        status = await check_all_ports(ip)
        servers_status.append({'name': server['name'], 'ip': ip, 'status': status})
    await send_report(context, servers_status)

def is_authorized(update: Update) -> bool:
    """Cek apakah user ID ada di ADMIN_IDS."""
    user_id = update.effective_user.id
    return user_id in ADMIN_IDS

async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cek akses dan balas pesan jika tidak diizinkan."""
    if not is_authorized(update):
        await update.message.reply_text(
            "Maaf seluruh fitur hanya tersedia untuk yang sudah memiliki akses. "
            "Silahkan hubungi admin @adm_tren untuk meminta aksesnya."
        )
        return False
    return True

async def start_monitoring(application: Application, interval: int = CHECK_INTERVAL_MINUTES):
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler(timezone='Asia/Jakarta')
        scheduler.add_job(monitoring_job, 'interval', minutes=interval, args=[application], id='monitor_job')
        scheduler.start()
        logger.info(f"Monitoring dimulai dengan interval {interval} menit")
    else:
        if scheduler.get_job('monitor_job') is None:
            scheduler.add_job(monitoring_job, 'interval', minutes=interval, args=[application], id='monitor_job')
            logger.info(f"Monitoring dimulai kembali dengan interval {interval} menit")
        else:
            scheduler.reschedule_job('monitor_job', trigger='interval', minutes=interval)
            logger.info(f"Interval monitoring diubah menjadi {interval} menit")

async def stop_monitoring():
    global scheduler
    if scheduler and scheduler.get_job('monitor_job'):
        scheduler.remove_job('monitor_job')
        logger.info("Monitoring dihentikan")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    await update.message.reply_text(
        "Halo! Saya adalah bot pemantau koneksi VPS (hanya untuk admin).
"
        "Gunakan perintah berikut:
"
        "/addserver nama ip - Tambah server
"
        "/removeserver nama - Hapus server
"
        "/listservers - Lihat daftar server
"
        "/status - Cek status semua server sekarang
"
        "/monitor - Mulai pemantauan otomatis
"
        "/stop - Hentikan pemantauan otomatis
"
        "/setinterval menit - Ubah interval monitoring
"
        "/help - Bantuan"
    )

async def add_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Gunakan: /addserver namaserver ipaddress")
        return
    name = context.args[0].strip()
    ip = context.args[1].strip()
    try:
        socket.inet_aton(ip)
    except socket.error:
        await update.message.reply_text("Alamat IP tidak valid.")
        return
    servers = load_servers()
    if any(s['name'] == name for s in servers):
        await update.message.reply_text(f"Server dengan nama '{name}' sudah ada. Gunakan nama lain.")
        return
    servers.append({'name': name, 'ip': ip})
    save_servers(servers)
    await update.message.reply_text(
        f"Server '{name}' dengan IP {mask_ip(ip)} berhasil ditambahkan.",
        parse_mode='Markdown'
    )

async def remove_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Gunakan: /removeserver namaserver")
        return
    name = context.args[0].strip()
    servers = load_servers()
    new_servers = [s for s in servers if s['name'] != name]
    if len(new_servers) == len(servers):
        await update.message.reply_text(f"Server dengan nama '{name}' tidak ditemukan.")
        return
    save_servers(new_servers)
    await update.message.reply_text(f"Server '{name}' berhasil dihapus.")

async def list_servers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    servers = load_servers()
    if not servers:
        await update.message.reply_text("Belum ada server yang terdaftar. Gunakan /addserver untuk menambahkan.")
        return
    msg = "**Daftar Server:**

"
    for s in servers:
        msg += f"• {s['name']}: {mask_ip(s['ip'])}
"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    servers = load_servers()
    if not servers:
        await update.message.reply_text("Belum ada server yang terdaftar. Gunakan /addserver untuk menambahkan.")
        return
    await update.message.reply_text("Sedang mengecek status semua server...")
    servers_status = []
    for server in servers:
        ip = server['ip']
        status_dict = await check_all_ports(ip)
        servers_status.append({'name': server['name'], 'ip': ip, 'status': status_dict})
    await send_report(context, servers_status)

async def monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    servers = load_servers()
    if not servers:
        await update.message.reply_text("Belum ada server yang terdaftar. Tambahkan server terlebih dahulu dengan /addserver.")
        return
    await start_monitoring(context.application, CHECK_INTERVAL_MINUTES)
    await update.message.reply_text(f"Monitoring dimulai setiap {CHECK_INTERVAL_MINUTES} menit. Laporan akan dikirim ke topic status server.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    await stop_monitoring()
    await update.message.reply_text("Monitoring dihentikan.")

async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Gunakan: /setinterval menit")
        return
    try:
        interval = int(context.args[0])
        if interval <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Interval harus berupa angka positif (menit).")
        return
    global CHECK_INTERVAL_MINUTES
    CHECK_INTERVAL_MINUTES = interval
    if scheduler and scheduler.get_job('monitor_job'):
        scheduler.reschedule_job('monitor_job', trigger='interval', minutes=interval)
        await update.message.reply_text(f"Interval monitoring diubah menjadi {interval} menit.")
    else:
        await update.message.reply_text(f"Interval disimpan ({interval} menit). Gunakan /monitor untuk memulai monitoring.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    await update.message.reply_text(
        "**Daftar Perintah (Hanya Admin):**
"
        "/start - Memulai bot
"
        "/addserver nama ip - Tambah server baru
"
        "/removeserver nama - Hapus server
"
        "/listservers - Lihat daftar server (IP disensor)
"
        "/status - Cek status semua server saat ini
"
        "/monitor - Mulai pemantauan otomatis
"
        "/stop - Hentikan pemantauan otomatis
"
        "/setinterval menit - Ubah interval monitoring (default 5 menit)
"
        "/help - Tampilkan bantuan ini",
        parse_mode='Markdown'
    )

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addserver", add_server))
    application.add_handler(CommandHandler("removeserver", remove_server))
    application.add_handler(CommandHandler("listservers", list_servers))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("monitor", monitor))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("setinterval", set_interval))
    application.add_handler(CommandHandler("help", help_command))

    application.run_polling()

if __name__ == '__main__':
    main()
