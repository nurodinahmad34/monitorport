#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}   Telegram Bot Monitor Port 80/443    ${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Pastikan script dijalankan sebagai root (atau dengan sudo)
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Harap jalankan script ini dengan sudo atau sebagai root.${NC}"
    echo "Contoh: sudo bash install.sh"
    exit 1
fi

# Update package list
echo -e "${YELLOW}[1/6] Memperbarui daftar paket...${NC}"
apt update -y

# Install Python3 dan pip jika belum ada
echo -e "${YELLOW}[2/6] Menginstal Python3 dan pip...${NC}"
apt install -y python3 python3-pip wget

# Install Python dependencies
echo -e "${YELLOW}[3/6] Menginstal dependensi Python...${NC}"
pip3 install python-telegram-bot apscheduler

# Download script monitorport.py
echo -e "${YELLOW}[4/6] Mengunduh monitorport.py...${NC}"
wget -O /root/monitorport.py https://raw.githubusercontent.com/username/repo/main/monitorport.py

# Minta konfigurasi
echo -e "${YELLOW}[5/6] Konfigurasi bot Telegram${NC}"
echo -e "${YELLOW}Masukkan Token Bot (dari @BotFather):${NC}"
read -r BOT_TOKEN
echo -e "${YELLOW}Masukkan Chat ID grup (contoh: -1001922430335):${NC}"
read -r GROUP_CHAT_ID
echo -e "${YELLOW}Masukkan Message Thread ID (ID topik, dari link https://t.me/grup/1780 = 1780):${NC}"
read -r MESSAGE_THREAD_ID

# Buat config.json
cat <<EOF > /root/config.json
{
    "BOT_TOKEN": "$BOT_TOKEN",
    "GROUP_CHAT_ID": $GROUP_CHAT_ID,
    "MESSAGE_THREAD_ID": $MESSAGE_THREAD_ID
}
EOF

# Buat servers.json kosong jika belum ada
if [ ! -f /root/servers.json ]; then
    echo "[]" > /root/servers.json
fi

# Buat systemd service
echo -e "${YELLOW}[6/6] Membuat dan menjalankan systemd service...${NC}"
cat <<EOF > /etc/systemd/system/monitorport.service
[Unit]
Description=Telegram Bot Monitor Multiple Servers (Port 80/443)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root
ExecStart=/usr/bin/python3 /root/monitorport.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable monitorport
systemctl start monitorport

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Instalasi selesai!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Bot sedang berjalan sebagai systemd service."
echo -e "Perintah untuk mengelola:"
echo -e "  • Lihat status:  ${YELLOW}sudo systemctl status monitorport${NC}"
echo -e "  • Lihat log:     ${YELLOW}sudo journalctl -u monitorport -f${NC}"
echo -e "  • Hentikan:      ${YELLOW}sudo systemctl stop monitorport${NC}"
echo -e "  • Mulai ulang:   ${YELLOW}sudo systemctl restart monitorport${NC}"
echo ""
echo -e "Sekarang Anda bisa menambahkan server dengan perintah di grup Telegram:"
echo -e "  ${YELLOW}/addserver NamaServer 123.45.67.89${NC}"
echo -e "  ${YELLOW}/status${NC}"
echo -e "  ${YELLOW}/monitor${NC}"
echo ""
echo -e "Jika ingin mengubah konfigurasi, edit file: ${YELLOW}/root/config.json${NC}"