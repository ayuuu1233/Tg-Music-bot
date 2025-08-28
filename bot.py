
import os
import asyncio
import shlex
import subprocess
from functools import wraps
from queue import Queue

from telegram import Update, ChatAction
from telegram.ext import Updater, CommandHandler, CallbackContext

from pyrogram import Client
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioPiped

# ---------------------- CONFIG ----------------------
# Environment variables (recommended) or replace with values directly
BOT_TOKEN = os.environ.get('BOT_TOKEN')  # Bot token from @BotFather
API_ID = int(os.environ.get('API_ID', 0))  # your Telegram API ID (int)
API_HASH = os.environ.get('API_HASH')  # your Telegram API hash
SESSION_NAME = os.environ.get('SESSION_NAME', 'kawaii_session')  # Pyrogram session name/file

# Where to store downloaded audio
DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Basic queue structure per chat (chat_id -> list of dicts)
queues = {}
players = {}  # to hold state if needed

# ---------------------- UTILITIES ----------------------

def ensure_chat(func):
    @wraps(func)
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        chat_id = update.effective_chat.id
        if chat_id not in queues:
            queues[chat_id] = []
        return func(update, context, *args, **kwargs)
    return wrapper

async def run_cmd(cmd: str):
    """Run shell command async and return stdout."""
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return stdout.decode().strip(), stderr.decode().strip()


def download_audio(url: str, out_path: str):
    """Download best audio using yt-dlp to out_path (mp3/m4a).
    Returns path to downloaded file or raises Exception.
    """
    # Make sure yt-dlp is available in system
    safe_out = shlex.quote(out_path)
    # use bestaudio, convert to m4a/mp3 container
    cmd = f"yt-dlp -x --audio-format m4a -o {safe_out} '{url}'"
    ret = subprocess.run(cmd, shell=True)
    if ret.returncode != 0:
        raise Exception('yt-dlp failed')
    # yt-dlp will append extension; find file
    base = out_path
    for ext in ('.m4a', '.mp3', '.webm', '.opus'):
        candidate = base + ext
        if os.path.exists(candidate):
            return candidate
    # fallback: try glob
    raise FileNotFoundError('downloaded file not found')

# ---------------------- PYROGRAM & PYTGCALLS SETUP ----------------------
pyro_app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)
py_calls = PyTgCalls(pyro_app)

async def start_pyrogram():
    await pyro_app.start()
    await py_calls.start()

asyncio.get_event_loop().create_task(start_pyrogram())

# ---------------------- VOICE HELPERS ----------------------
async def _ensure_vc(chat_id: int):
    # Join the chat's voice chat (needs an active group call). We rely on PyTgCalls join
    # The 'chat_id' passed to join may need to be the group id.
    return True

async def play_next(chat_id: int):
    queue = queues.get(chat_id, [])
    if not queue:
        # nothing left => leave
        try:
            await py_calls.leave_group_call(chat_id)
        except Exception:
            pass
        return
    item = queue.pop(0)
    file_path = item['file']
    # create AudioPiped stream using ffmpeg to ensure compatibility
    audio = AudioPiped(file_path)
    try:
        await py_calls.join_group_call(chat_id, audio)
    except Exception:
        # try to change stream instead
        try:
            await py_calls.change_stream(chat_id, audio)
        except Exception as e:
            print('play error', e)
            return

# ---------------------- BOT COMMANDS ----------------------

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Kawaii Music Bot is online! Use /play <yt link or search> to play music.")

@ensure_chat
def play(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args
    if not args:
        update.message.reply_text('Usage: /play <YouTube_URL or search terms>')
        return
    query = ' '.join(args)
    update.message.chat.send_action(ChatAction.UPLOAD_AUDIO)
    msg = update.message.reply_text('Downloading — please wait...')

    # create unique filename base
    safe_base = os.path.join(DOWNLOAD_DIR, f"{chat_id}_{int(update.message.date.timestamp())}")
    try:
        # If it's a plain URL, pass through; else use ytsearch1:
        if query.startswith('http'):
            url = query
        else:
            url = f"ytsearch1:{query}"
        file_path = download_audio(url, safe_base)
    except Exception as e:
        msg.edit_text(f'Failed to download: {e}')
        return

    # add to queue
    queues[chat_id].append({'file': file_path, 'title': os.path.basename(file_path)})
    msg.edit_text('Added to queue — joining VC...')

    # If nothing playing, start playback
    # We schedule play_next
    loop = asyncio.get_event_loop()
    loop.create_task(play_next(chat_id))
    update.message.reply_text('Added to queue ✅')

@ensure_chat
def skip(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    # stop current and play next
    try:
        # leaving voice call then play_next will cause next to start
        loop = asyncio.get_event_loop()
        loop.create_task(py_calls.leave_group_call(chat_id))
        loop.create_task(play_next(chat_id))
        update.message.reply_text('Skipped ✅')
    except Exception as e:
        update.message.reply_text(f'Error skipping: {e}')

@ensure_chat
def stop(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    queues[chat_id].clear()
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(py_calls.leave_group_call(chat_id))
    except Exception:
        pass
    update.message.reply_text('Stopped and left the voice chat.')

@ensure_chat
def pause(update: Update, context: CallbackContext):
    update.message.reply_text('Pause is not implemented in this minimal example.')

@ensure_chat
def resume(update: Update, context: CallbackContext):
    update.message.reply_text('Resume is not implemented in this minimal example.')

@ensure_chat
def queue_cmd(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    q = queues.get(chat_id, [])
    if not q:
        update.message.reply_text('Queue is empty.')
        return
    txt = '\n'.join([f"{i+1}. {os.path.basename(x['file'])}" for i,x in enumerate(q)])
    update.message.reply_text(f'Queue:\n{txt}')

# ---------------------- RUN ----------------------

def main():
    if not BOT_TOKEN or not API_ID or not API_HASH:
        print('ERROR: BOT_TOKEN, API_ID or API_HASH not set in environment.')
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('play', play))
    dp.add_handler(CommandHandler('skip', skip))
    dp.add_handler(CommandHandler('stop', stop))
    dp.add_handler(CommandHandler('pause', pause))
    dp.add_handler(CommandHandler('resume', resume))
    dp.add_handler(CommandHandler('queue', queue_cmd))

    updater.start_polling()
    print('Bot started — polling. Press Ctrl+C to stop.')
    updater.idle()

if __name__ == '__main__':
    main()
