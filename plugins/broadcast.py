import time
import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, ChatForwardsRestricted

# ── Helpers ────────────────────────────────────────────────────────────────
BAR_LEN = 20
UPDATE_INTERVAL = 0.05  # refresh every 5%

MODE_LABELS = {
    "pin":    "📌 ᴘɪɴ",
    "delete": "🗑 ᴅᴇʟᴇᴛᴇ",
    "silent": "🔕 ꜱɪʟᴇɴᴛ",
    "normal": "📢 ɴᴏʀᴍᴀʟ",
}

def build_bar(pct: float) -> str:
    filled = int(pct * BAR_LEN)
    return "●" * filled + "○" * (BAR_LEN - filled)

def fmt_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    return f"{m}m {s}s"

def build_message(
    header: str,
    icon: str,
    pct: float,
    bar: str,
    elapsed: int,
    eta: int | None,
    total: int,
    successful: int,
    blocked: int,
    deleted: int,
    unsuccessful: int,
    footer: str = "",
) -> str:
    time_line = f"⏱ <code>{fmt_time(elapsed)}</code>"
    if eta is not None:
        time_line += f"  ›  ETA <code>{fmt_time(eta)}</code>"

    stats = (
        f"<code>{total}</code> total  ·  "
        f"<code>{successful}</code> ✅  "
        f"<code>{blocked}</code> 🚫  "
        f"<code>{deleted}</code> 🗑  "
        f"<code>{unsuccessful}</code> ❌"
    )

    msg = (
        f"<b>{header}\n\n"
        f"<blockquote>{icon}:</b> [{bar}] <code>{pct:.0%}</code>\n"
        f"{time_line}</blockquote>\n\n"
        f"<b>{stats}</b>"
    )
    if footer:
        msg += f"\n\n<i>{footer}</i>"
    return msg

async def auto_delete(sent_msg, duration: int):
    await asyncio.sleep(duration)
    try:
        await sent_msg.delete()
    except Exception:
        pass

# Global state for cancellation
cancel_lock = asyncio.Lock()
is_canceled = False

# ── /users ────────────────────────────────────────────────────────────────
@Client.on_message(filters.command('users'))
async def user_count(client, message):
    if not message.from_user.id in client.admins:
        return await client.send_message(message.from_user.id, client.reply_text)
    total_users = await client.mongodb.full_userbase()
    await message.reply(f"**{len(total_users)} Usᴇʀs ᴀʀᴇ ᴜsɪɴɢ ᴛʜɪs ʙᴏᴛ ᴄᴜʀʀᴇɴᴛʟʏ!**")

# ── /cancel ────────────────────────────────────────────────────────────────
@Client.on_message(filters.command("cancel") & filters.private)
async def cancel_broadcast(client, message):
    if not message.from_user.id in client.admins:
        return
    global is_canceled
    async with cancel_lock:
        is_canceled = True
    await message.reply("<b>✅ Bʀᴏᴀᴅᴄᴀsᴛ ᴄᴀɴᴄᴇʟʟᴀᴛɪᴏɴ ʀᴇǫᴜᴇsᴛᴇᴅ. Iᴛ ᴡɪʟʟ sᴛᴏᴘ sʜᴏʀᴛʟʏ.</b>")

# ── Broadcast Engine ───────────────────────────────────────────────────────
async def do_broadcast(client, status_message_or_callback, broadcast_msg, mode_str, do_pin, do_delete, duration, silent, use_copy=False):
    global is_canceled
    async with cancel_lock:
        is_canceled = False

    query = await client.mongodb.full_userbase()
    total = len(query)

    if total == 0:
        msg_text = "<b>⚠️ Nᴏ ᴜsᴇʀs ғᴏᴜɴᴅ ɪɴ ᴛʜᴇ ᴅᴀᴛᴀʙᴀsᴇ.</b>"
        if hasattr(status_message_or_callback, 'message'):
            return await status_message_or_callback.message.edit(msg_text)
        return await status_message_or_callback.reply(msg_text)

    successful = blocked = deleted = unsuccessful = 0

    if hasattr(status_message_or_callback, 'message'):
        pls_wait = status_message_or_callback.message
        await pls_wait.edit(f"<blockquote><b><i>Sᴛᴀʀᴛɪɴɢ ʙʀᴏᴀᴅᴄᴀsᴛ · <b>{mode_str}</b> · {total} ᴜsᴇʀs…</i></b></blockquote>")
    else:
        pls_wait = await status_message_or_callback.reply(f"<blockquote><b><i>Sᴛᴀʀᴛɪɴɢ ʙʀᴏᴀᴅᴄᴀsᴛ · <b>{mode_str}</b> · {total} ᴜsᴇʀs…</i></b></blockquote>")

    bar = build_bar(0)
    last_update_pct = -1.0
    start_time = time.time()

    for idx, chat_id in enumerate(query, start=1):
        async with cancel_lock:
            if is_canceled:
                pct = idx / total
                elapsed = int(time.time() - start_time)
                await pls_wait.edit(
                    build_message(
                        f"<blockquote><b>Bʀᴏᴀᴅᴄᴀsᴛɪɴɢ Sᴛᴏᴘᴇᴅ 🔴  </b></blockquote>\n\n<blockquote><b>{mode_str}</b></blockquote>",
                        "🔴", pct, build_bar(pct),
                        elapsed, None,
                        total, successful, blocked, deleted, unsuccessful,
                    )
                )
                return

        async def _send():
            nonlocal successful
            if use_copy:
                sent = await broadcast_msg.copy(chat_id, disable_notification=silent)
            else:
                sent = await client.forward_messages(chat_id=chat_id, from_chat_id=broadcast_msg.chat.id, message_ids=broadcast_msg.id, disable_notification=silent)
            
            if do_pin:
                await client.pin_chat_message(chat_id, sent.id, both_sides=True)
            if do_delete:
                asyncio.create_task(auto_delete(sent, duration))
            successful += 1

        try:
            await _send()
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                await _send()
            except Exception:
                unsuccessful += 1
        except UserIsBlocked:
            await client.mongodb.del_user(chat_id)
            blocked += 1
        except InputUserDeactivated:
            await client.mongodb.del_user(chat_id)
            deleted += 1
        except Exception:
            unsuccessful += 1

        # ── Progress update ────────────────────────────────────────────────
        pct = idx / total
        if pct - last_update_pct >= UPDATE_INTERVAL:
            bar = build_bar(pct)
            elapsed = int(time.time() - start_time)
            done = successful + blocked + deleted + unsuccessful
            eta = int((total - done) * (elapsed / done)) if done else None
            await pls_wait.edit(
                build_message(
                    f"<blockquote><b>Bʀᴏᴀᴅᴄᴀsᴛɪɴɢ...  </b></blockquote>\n\n<blockquote><b>{mode_str}</b></blockquote>",
                    "⏳", pct, bar,
                    elapsed, eta,
                    total, successful, blocked, deleted, unsuccessful,
                    footer="➪ To stop: /cancel",
                )
            )
            last_update_pct = pct

    # ── Final ──────────────────────────────────────────────────────────────
    elapsed = int(time.time() - start_time)
    await pls_wait.edit(
        build_message(
            f"<blockquote><b>Bʀᴏᴀᴅᴄᴀsᴛ Dᴏɴᴇ ✅  </b></blockquote>\n\n<blockquote><b>{mode_str}</b></blockquote>",
            "✅", 1.0, "●" * BAR_LEN,
            elapsed, 0,
            total, successful, blocked, deleted, unsuccessful,
        )
    )

# ── /broadcast ─────────────────────────────────────────────────────────────
def parse_broadcast_modes(args):
    do_pin = False
    do_delete = False
    duration = 0
    silent = False
    mode_labels = []

    i = 0
    while i < len(args):
        arg = args[i].lower()
        if arg == "pin" or arg == "pbroadcast":
            do_pin = True
            if MODE_LABELS["pin"] not in mode_labels:
                mode_labels.append(MODE_LABELS["pin"])
        elif arg == "delete":
            do_delete = True
            try:
                duration = int(args[i + 1])
                i += 1
            except (IndexError, ValueError):
                return None, "<b>⚠️ Provide a valid duration.</b>\nUsage: <code>/broadcast delete 30</code>"
            mode_labels.append(f"🗑 DELETE({duration}s)")
        elif arg == "silent":
            silent = True
            if MODE_LABELS["silent"] not in mode_labels:
                mode_labels.append(MODE_LABELS["silent"])
        elif arg == "normal":
            if MODE_LABELS["normal"] not in mode_labels:
                mode_labels.append(MODE_LABELS["normal"])
        elif not arg.startswith("http"):
            mode_labels.append(arg.upper())
        i += 1

    if not mode_labels:
        mode_labels.append(MODE_LABELS["normal"])

    mode_str = " + ".join(mode_labels)
    return (do_pin, do_delete, duration, silent, mode_str), None


@Client.on_message(filters.private & filters.command(['broadcast', 'pbroadcast']))
async def broadcast_command(client, message):
    if not message.from_user.id in client.admins:
        return
        
    args = message.text.split()[1:]
    
    if message.command[0].lower() == 'pbroadcast':
        args.insert(0, "pin")

    link = None
    for arg in args:
        if arg.startswith("http"):
            link = arg
            break

    parsed_modes, err = parse_broadcast_modes(args)
    if err:
        return await message.reply(err)
    
    do_pin, do_delete, duration, silent, mode_str = parsed_modes

    if link:
        pattern = r"https://t.me/(?:c/)?(.*)/(\d+)"
        match = re.match(pattern, link)
        if match:
            chat_id = match.group(1)
            if chat_id.isdigit():
                chat_id = int(f"-100{chat_id}")
            msg_id = int(match.group(2))
            
            try:
                broadcast_msg = await client.get_messages(chat_id, msg_id)
                if not broadcast_msg or broadcast_msg.empty:
                    return await message.reply("Could not fetch the message. Make sure I am an admin in that channel.")
                
                try:
                    await client.forward_messages(message.from_user.id, chat_id, msg_id, disable_notification=silent)
                    use_copy = 0
                except ChatForwardsRestricted:
                    await broadcast_msg.copy(message.from_user.id, disable_notification=silent)
                    use_copy = 1
                
                flags = f"{int(do_pin)}_{int(do_delete)}_{duration}_{int(silent)}_{use_copy}"
                
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🟢 𝗬𝗲𝘀 𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁", callback_data=f"bdcst_y_{chat_id}_{msg_id}_{flags}")],
                    [InlineKeyboardButton("🔴 𝗖𝗮𝗻𝗰𝗲𝗹", callback_data="bdcst_n")]
                ])
                await message.reply(f"<blockquote><b>📢 Bʀᴏᴀᴅᴄᴀsᴛ Cᴏɴғɪʀᴍᴀᴛɪᴏɴ</b></blockquote>\n\nMᴏᴅᴇꜱ: **{mode_str}**\n<b>Sʜᴏᴜʟᴅ I ʙʀᴏᴀᴅᴄᴀsᴛ ᴛʜᴇ ᴍᴇssᴀɢᴇ ᴀʙᴏᴠᴇ? Pʟᴇᴀsᴇ ʀᴇᴠɪᴇᴡ ɪᴛ ᴄᴀʀᴇғᴜʟʟʏ.</b>", reply_markup=reply_markup)
            except Exception as e:
                await message.reply(f"Error fetching message: {e}")
        else:
            await message.reply("<blockquote><b>Iɴᴠᴀʟɪᴅ ʟɪɴᴋ ғᴏʀᴍᴀᴛ🔴</b></blockquote>\n <b>Pʟᴇᴀsᴇ ᴜsᴇ ᴀ ᴠᴀʟɪᴅ Tᴇʟᴇɢʀᴀᴍ ᴘᴏsᴛ ʟɪɴᴋ.</b>")
            
    elif message.reply_to_message:
        await do_broadcast(client, message, message.reply_to_message, mode_str, do_pin, do_delete, duration, silent, use_copy=True)
    else:
        msg = await message.reply(
            "<blockquote><b>Rᴇᴘʟʏ ᴛᴏ ᴀɴʏ Tᴇʟᴇɢʀᴀᴍ ᴍᴇssᴀɢᴇ ᴏʀ ᴘᴀss ᴀ Tᴇʟᴇɢʀᴀᴍ ᴘᴏsᴛ ʟɪɴᴋ ᴛᴏ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ 💬</b></blockquote>\n\n"
            "<blockquote><b>Mᴏᴅᴇꜱ:</b></blockquote>\n"
            "› <code>/broadcast</code> — <b>ꜱᴇɴᴅ ɴᴏʀᴍᴀʟʟʏ</b>\n"
            "› <code>/broadcast pin</code> — <b>ꜱᴇɴᴅ & ᴘɪɴ</b>\n"
            "› <code>/broadcast silent</code> — <b>ɴᴏ ɴᴏᴛɪꜰɪᴄᴀᴛɪᴏɴ</b>\n"
            "› <code>/broadcast delete 30</code> — <b>ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ᴀꜰᴛᴇʀ 30ꜱ</b>\n"
            "› <code>/broadcast pin delete 30</code> — <b>ᴘɪɴ, ᴛʜᴇɴ ᴅᴇʟᴇᴛᴇ</b>\n"
            "› <code>/broadcast silent pin delete 60</code> — <b>ᴀʟʟ ᴛʜʀᴇᴇ</b>\n\n"
            "<blockquote><b>Yᴏᴜ ᴄᴀɴ ᴀʟꜱᴏ ᴘᴀꜱꜱ ᴀ ʟɪɴᴋ ᴀʟᴏɴɢꜱɪᴅᴇ ᴍᴏᴅᴇꜱ:</b></blockquote>\n"
            "<code>/broadcast silent https://t.me/Infinix_Adult/123</code>"
        )
        await asyncio.sleep(30)
        await msg.delete()

#===============================================================#

@Client.on_callback_query(filters.regex(r"^bdcst_y_(.+)_(.+)_(\d+)_(\d+)_(\d+)_(\d+)_(\d+)$"))
async def broadcast_yes(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("Only admins can use this.", show_alert=True)
        
    chat_id = query.matches[0].group(1)
    msg_id = int(query.matches[0].group(2))
    
    do_pin = bool(int(query.matches[0].group(3)))
    do_delete = bool(int(query.matches[0].group(4)))
    duration = int(query.matches[0].group(5))
    silent = bool(int(query.matches[0].group(6)))
    use_copy = bool(int(query.matches[0].group(7)))
    
    if chat_id.lstrip('-').isdigit():
        chat_id = int(chat_id)
        
    mode_labels = []
    if do_pin: mode_labels.append(MODE_LABELS["pin"])
    if do_delete: mode_labels.append(f"🗑 DELETE({duration}s)")
    if silent: mode_labels.append(MODE_LABELS["silent"])
    if not mode_labels: mode_labels.append(MODE_LABELS["normal"])
    mode_str = " + ".join(mode_labels)

    try:
        broadcast_msg = await client.get_messages(chat_id, msg_id)
    except Exception as e:
        return await query.answer(f"Failed to fetch message: {e}", show_alert=True)
        
    await do_broadcast(client, query, broadcast_msg, mode_str, do_pin, do_delete, duration, silent, use_copy)

#===============================================================#

@Client.on_callback_query(filters.regex(r"^bdcst_n$"))
async def broadcast_no(client, query):
    if query.from_user.id not in client.admins:
        return await query.answer("𝗙𝘂𝗰𝗸 𝗢𝗳𝗳 𝗚𝗼𝗼𝗻𝗲𝗿", show_alert=True)
        
    await query.message.edit("<blockquote><b>❌ Bʀᴏᴀᴅᴄᴀsᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ</b></blockquote>")