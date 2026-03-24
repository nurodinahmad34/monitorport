import asyncio
import logging
import socket
import os
import json
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ================= KONFIGURASI DARI FILE =================
CONFIG_FILE = "config.json"

def load_config():
    """Membaca konfigurasi dari file JSON."""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"File {CONFIG_FILE} tidak ditemukan. Pastikan file konfigurasi ada.")
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

config = load_config()
BOT_TOKEN = config.get("BOT_TOKEN")
GROUP_CHAT_ID = config.get("GROUP_CHAT_ID")
MESSAGE_THREAD_ID = config.get("MESSAGE_THREAD_ID")

if not all([BOT_TOKEN, GROUP_CHAT_ID, MESSAGE_THREAD_ID]):
    raise ValueError("BOT_TOKEN, GROUP_CHAT_ID, dan MESSAGE_THREAD_ID harus diisi di config.json")

SERVERS_FILE = "servers.json"
CHECK_INTERVAL_MINUTES = 5
# ========================================================

# Setup logging
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
    """Menyensor IP: menampilkan *.* pada dua oktet pertama."""
    parts = ip.split('.')
    if len(parts) == 4:
        return f"*.*.{parts[2]}.{parts[3]}"
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
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"📡 *Laporan Monitoring VPS* 📡\n🕒 {now}\n"
    for server in servers_status:
        name = server['name']
        ip_masked = mask_ip(server['ip'])
        status = server['status']
        msg += f"\n🔹 *{name}* (`{ip_masked}`)\n"
        for port, ok in status.items():
            icon = "✅" if ok else "❌"
            msg += f"{icon} Port {port}: {'UP' if ok else 'DOWN'}\n"
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=msg,
        parse_mode="Markdown",
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
        servers_status.append({
            'name': server['name'],
            'ip': ip,
            'status': status
        })
    await send_report(context, servers_status)

async def start_monitoring(application: Application, interval: int = CHECK_INTERVAL_MINUTES):
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler(timezone="Asia/Jakarta")
        scheduler.add_job(
            monitoring_job,
            'interval',
            minutes=interval,
            args=[application],
            id='monitor_job'
        )
        scheduler.start()
        logger.info(f"Monitoring dimulai dengan interval {interval} menit")
    else:
        if scheduler.get_job('monitor_job') is None:
            scheduler.add_job(
                monitoring_job,
                'interval',
                minutes=interval,
                args=[application],
                id='monitor_job'
            )
            logger.info(f"Monitoring dimulai kembali dengan interval {interval} menit")
        else:
            scheduler.reschedule_job('monitor_job', trigger='interval', minutes=interval)
            logger.info(f"Interval monitoring diubah menjadi {interval} menit")

async def stop_monitoring():
    global scheduler
    if scheduler and scheduler.get_job('monitor_job'):
        scheduler.remove_job('monitor_job')
        logger.info("Monitoring dihentikan")

# ================= HANDLER COMMAND =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Halo! Saya adalah bot pemantau koneksi VPS.\n"
        "Gunakan perintah berikut:\n"
        "/addserver <nama> <ip> - Tambah server\n"
        "/removeserver <nama> - Hapus server\n"
        "/listservers - Lihat daftar server\n"
        "/status - Cek status semua server sekarang\n"
        "/monitor - Mulai pemantauan otomatis\n"
        "/stop - Hentikan pemantauan otomatis\n"
        "/setinterval <menit> - Ubah interval monitoring\n"
        "/help - Bantuan"
    )

async def addserver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ Gunakan: /addserver <nama_server> <ip_address>")
        return
    name = context.args[0].strip()
    ip = context.args[1].strip()
    try:
        socket.inet_aton(ip)
    except socket.error:
        await update.message.reply_text("❌ Alamat IP tidak valid.")
        return
    servers = load_servers()
    if any(s['name'] == name for s in servers):
        await update.message.reply_text(f"❌ Server dengan nama '{name}' sudah ada. Gunakan nama lain.")
        return
    servers.append({'name': name, 'ip': ip})
    save_servers(servers)
    await update.message.reply_text(f"✅ Server '{name}' dengan IP `{mask_ip(ip)}` berhasil ditambahkan.", parse_mode="Markdown")

async def removeserver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Gunakan: /removeserver <nama_server>")
        return
    name = context.args[0].strip()
    servers = load_servers()
    new_servers = [s for s in servers if s['name'] != name]
    if len(new_servers) == len(servers):
        await update.message.reply_text(f"❌ Server dengan nama '{name}' tidak ditemukan.")
        return
    save_servers(new_servers)
    await update.message.reply_text(f"✅ Server '{name}' berhasil dihapus.")

async def listservers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    servers = load_servers()
    if not servers:
        await update.message.reply_text("Belum ada server yang terdaftar. Gunakan /addserver untuk menambahkan.")
        return
    msg = "📋 *Daftar Server:*\n"
    for s in servers:
        msg += f"🔹 *{s['name']}* – `{mask_ip(s['ip'])}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    servers = load_servers()
    if not servers:
        await update.message.reply_text("Belum ada server yang terdaftar. Gunakan /addserver untuk menambahkan.")
        return
    await update.message.reply_text("🔍 Sedang mengecek status semua server...")
    servers_status = []
    for server in servers:
        ip = server['ip']
        status_dict = await check_all_ports(ip)
        servers_status.append({
            'name': server['name'],
            'ip': ip,
            'status': status_dict
        })
    await send_report(context, servers_status)

async def monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    servers = load_servers()
    if not servers:
        await update.message.reply_text("❌ Belum ada server yang terdaftar. Tambahkan server terlebih dahulu dengan /addserver.")
        return
    await start_monitoring(context.application, CHECK_INTERVAL_MINUTES)
    await update.message.reply_text(f"✅ Monitoring dimulai setiap {CHECK_INTERVAL_MINUTES} menit. Laporan akan dikirim ke topic status server.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await stop_monitoring()
    await update.message.reply_text("⏹️ Monitoring dihentikan.")

async def setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Gunakan: /setinterval <menit>")
        return
    try:
        interval = int(context.args[0])
        if interval <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Interval harus berupa angka positif (menit).")
        return
    global CHECK_INTERVAL_MINUTES
    CHECK_INTERVAL_MINUTES = interval
    if scheduler and scheduler.get_job('monitor_job'):
        scheduler.reschedule_job('monitor_job', trigger='interval', minutes=interval)
        await update.message.reply_text(f"✅ Interval monitoring diubah menjadi {interval} menit.")
    else:
        await update.message.reply_text(f"✅ Interval disimpan. Gunakan /monitor untuk memulai monitoring dengan interval baru.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 *Daftar Perintah:*\n"
        "/start - Memulai bot\n"
        "/addserver <nama> <ip> - Tambah server baru\n"
        "/removeserver <nama> - Hapus server\n"
        "/listservers - Lihat daftar server (IP disensor)\n"
        "/status - Cek status semua server saat ini\n"
        "/monitor - Mulai pemantauan otomatis\n"
        "/stop - Hentikan pemantauan otomatis\n"
        "/setinterval <menit> - Ubah interval monitoring (default 5 menit)\n"
        "/help - Tampilkan bantuan ini",
        parse_mode="Markdown"
    )

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addserver", addserver))
    application.add_handler(CommandHandler("removeserver", removeserver))
    application.add_handler(CommandHandler("listservers", listservers))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("monitor", monitor))
    application.add_handler(CommandHandler("stop", stop))
    application.add_handler(CommandHandler("setinterval", setinterval))
    application.add_handler(CommandHandler("help", help_command))
    application.run_polling()

if __name__ == "__main__":
    main()