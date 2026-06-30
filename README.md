# PTE/MSE Trading Bot — Python murni (tanpa n8n)

Bot keputusan trading BTC yang menjalankan **MSE** (klasifikasi rezim) + **PTE** (konfluensi 7-lapis)
lewat DeepSeek, menyaring tiap trade dengan **Risk Governor deterministik**, mengeksekusi di **Lighter
testnet**, dan mengirim laporan **modal, PnL, modal+P/L** ke **Telegram**. Satu proses Python, jalan 24 jam
di VPS, di-update lewat `git pull`.

> Bukan nasihat finansial. Mulai dengan `DRY_RUN=true` di testnet sampai expectancy terbukti lewat backtest.
> AI **tidak** memegang otoritas final atas uang — itu tugas Risk Governor (kode deterministik).

---

## 1. Arsitektur

```
main.py (loop tiap LOOP_MINUTES)
  └─ exchange.get_account()      → saldo/PnL dari Lighter (+ baseline harian utk kill switch)
  └─ data.collect + snapshot     → data publik Binance (gratis) + Fear&Greed → snapshot
  └─ llm.classify_regime()       → DeepSeek: MSE → rezim A/B/C/D
  └─ llm.analyze_trade()         → DeepSeek: PTE → sinyal/entry/SL/target (JSON)
  └─ risk.evaluate()             → DETERMINISTIK: hitung ulang R:R, sizing dari stop, gerbang + kill switch
  └─ if approved → exchange.execute()  → order ditandatangani L2 di Lighter (hormati DRY_RUN)
  └─ notify.send()               → Telegram (modal, PnL, keputusan)
```

Tidak ada bridge HTTP terpisah lagi — signing Lighter terjadi di proses yang sama (binary Go native jalan
mulus di Linux/Ubuntu).

## 2. Peta file

| File | Fungsi |
|---|---|
| `main.py` | Loop orkestrator (otak utama). |
| `config.py` | Semua setting dibaca dari `.env`. |
| `prompts.py` | Kecerdasan engine: prompt MSE + PTE. |
| `data.py` | Ambil data Binance publik + Fear&Greed, bangun snapshot + indikator. |
| `llm.py` | Panggil DeepSeek (MSE lalu PTE), parsing JSON tahan-banting. |
| `risk.py` | **Risk Governor deterministik** — gerbang, sizing dari stop, kill switch. |
| `exchange.py` | Lighter: baca akun/PnL + eksekusi order L2. |
| `notify.py` | Notifikasi Telegram. |
| `find_account.py` | Cari account index + decimals (sekali jalan). |
| `deploy/setup.sh` | Pasang venv + dependensi. |
| `deploy/pte-bot.service` | Template service systemd (24 jam). |
| `.env.example` | Contoh konfigurasi (salin ke `.env`). |

## 3. Prasyarat (yang kamu sudah punya ✅)

- VPS Ubuntu terbaru ✅
- Akun Lighter testnet ✅
- API key DeepSeek (`deepseek-v4-pro`) ✅
- Telegram bot token + chat/channel id ✅

## 4. Pasang lewat GitHub → VPS

**A. Taruh di GitHub (dari laptop / langsung di VPS):**
```bash
# di folder repo ini
git init && git add . && git commit -m "init pte bot"
git branch -M main
git remote add origin https://github.com/USERNAME/pte-trading-bot.git
git push -u origin main
```
> `.gitignore` sudah mengecualikan `.env`, `venv/`, dan `bot_state.json` — **rahasiamu tidak akan ter-push.**

**B. Di VPS (lewat SSH):**
```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/USERNAME/pte-trading-bot.git
cd pte-trading-bot
bash deploy/setup.sh          # bikin venv + install dependensi
cp .env.example .env
nano .env                     # isi semua kunci, simpan (Ctrl+O, Enter, Ctrl+X)
```

**C. Cari account index & decimals (sekali):**
```bash
source venv/bin/activate
python find_account.py 0xALAMAT_WALLET_KAMU
```
Masukkan angka yang muncul ke `.env`: `LIGHTER_ACCOUNT_INDEX`, `LIGHTER_MARKET_INDEX` (index pasar BTC),
`LIGHTER_PRICE_DECIMALS`, `LIGHTER_SIZE_DECIMALS`.

**D. Tes sekali (mode aman):**
```bash
source venv/bin/activate
python main.py
```
Pastikan log jalan dan **pesan Telegram masuk** (modal/PnL + keputusan). `Ctrl+C` untuk stop. Karena
`DRY_RUN=true`, tidak ada order nyata dikirim.

## 5. Jalankan 24 jam (systemd)

```bash
# buat service (otomatis isi user & path):
sudo tee /etc/systemd/system/pte-bot.service > /dev/null << EOF
[Unit]
Description=PTE/MSE Trading Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$HOME/pte-trading-bot
EnvironmentFile=$HOME/pte-trading-bot/.env
ExecStart=$HOME/pte-trading-bot/venv/bin/python $HOME/pte-trading-bot/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pte-bot
sudo systemctl status pte-bot          # harus active (running)
sudo journalctl -u pte-bot -f          # log langsung (Ctrl+C keluar)
```
Bot kini auto-restart kalau crash atau VPS reboot.

## 6. Update (alur GitHub yang kamu minta)

Edit kode → push dari laptop → di VPS:
```bash
cd ~/pte-trading-bot
git pull
sudo systemctl restart pte-bot
```
Selesai. Kalau ada dependensi baru: `source venv/bin/activate && pip install -r requirements.txt` dulu.

## 7. Naik ke order sungguhan (TESTNET) — jangan buru-buru

Ubah `DRY_RUN=false` di `.env` lalu `sudo systemctl restart pte-bot` **hanya setelah**:
1. Sudah **backtest** satu aturan entry konkret dan untung out-of-sample (bukan feeling).
2. Sudah pastikan **stop-loss benar-benar mendarat** di Lighter saat testnet (cek log `execute -> ... sl ok`).
3. Tetap di **testnet**. Mainnet keputusan terpisah: ganti `LIGHTER_BASE_URL`, verifikasi ulang decimals.

## 8. Batas jujur (sama seperti versi n8n)

1. **Buta makro/ETF/news.** Data gratis hanya menutup harga + derivatif (PTE Lapis 2–5). Tidak ada Fed/DXY
   (Tier-1), ETF flow (Tier-2), atau berita (Lapis 7) — driver yang justru paling tinggi di MSE. Prompt
   menyuruh AI memberi skor 0 + turunkan confidence di lapis itu. Untuk menutup: tambah fetcher berbayar di
   `data.py` (mis. CoinGlass) lalu masukkan ke `build_snapshot()`.
2. **Stop-loss best-effort.** `exchange.py` mencoba pasang SL reduce-only; param trigger Lighter beda antar
   versi SDK. Kalau gagal, log/Telegram memberi `warning`. **Verifikasi SL mendarat sebelum live.**
3. **Pemetaan field akun** (`*_KEYS` di `exchange.py`) cocok dengan SDK saat ini tapi bisa berubah — blok
   `_raw` membantu menyesuaikan kalau ada nilai `null`.
4. **Kill switch** memakai baseline harian (mark-to-market sejak 00:00 UTC) di `bot_state.json` — cukup untuk
   menghentikan hari buruk, bukan ledger akuntansi.
5. **Satu tesis AI per siklus bukan edge.** Ini kerangka disiplin. Edge baru ada kalau aturan entry lolos backtest.

## 9. Keamanan

- **`.env` jangan pernah di-commit** (sudah di `.gitignore`). Berisi private key + API key.
- Repo GitHub sebaiknya **private** kalau ragu.
- Bot ini hanya melakukan **panggilan keluar** (Binance/DeepSeek/Lighter/Telegram) — tidak membuka port. Tidak
  perlu reverse proxy, tapi firewall dasar tetap dianjurkan: `sudo ufw allow OpenSSH && sudo ufw enable`.

## Troubleshooting

| Gejala | Solusi |
|---|---|
| Binance `451/403` | Beberapa IP VPS diblokir Binance secara geografis. Coba region VPS lain, atau ganti sumber data di `data.py`. |
| DeepSeek `401` | `DEEPSEEK_API_KEY` salah atau saldo belum diisi. |
| `create_order signature mismatch` | Versi SDK beda — cek parameter `create_order` di lighter-python kamu. |
| `/account` nilai `null` | Lihat blok `_raw` (set logging DEBUG), sesuaikan `*_KEYS` di `exchange.py`. |
| Telegram sepi | Token/chat id salah. Cek `https://api.telegram.org/bot<TOKEN>/getUpdates`. |
| `pip` "externally-managed" | Pastikan `source venv/bin/activate` dulu. |
