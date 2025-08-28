# Tg-Music-bot
# 🎵 Kawaii Telegram Music Bot

A simple, ready-to-run **Telegram Music Bot** for Termux.  
Plays music in **group voice chats** using `PyTgCalls` and `yt-dlp`.

---

## ✨ Features
- `/play <song name or YouTube link>` → Play music in VC
- `/skip` → Skip current track
- `/stop` → Stop & leave VC
- `/queue` → Show queue
- Supports **YouTube search + direct links**

---

## ⚡ Setup (Termux)

1. Install Termux dependencies:
```bash
pkg update && pkg upgrade -y
pkg install python git ffmpeg -y
pip install --upgrade pip
