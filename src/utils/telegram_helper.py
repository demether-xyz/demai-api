"""
v1.1
"""

from typing import Optional

from chatgpt_md_converter import telegram_format
from telegram import Bot, Update
from telegram.constants import ParseMode


class TelegramHelper:
    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token)

    async def send_message(self, chat_id: int, text: str) -> None:
        """Send a message using the external telegram_format converter."""
        formatted_text = telegram_format(text)
        await self.bot.send_message(chat_id=chat_id, text=formatted_text, parse_mode=ParseMode.HTML)

    async def process_update(self, update_data: dict, handle: str = "") -> Optional[dict]:
        """Process a Telegram update and return structured data."""
        try:
            update = Update.de_json(update_data, self.bot)
            message = update.effective_message
            if not message:
                return None

            content = message.text or message.caption or ""

            if handle and handle in content:
                content = content.replace(handle, "").strip()

            file_info = None
            if message.document:
                file = await message.document.get_file()
                file_info = {
                    "file_id": message.document.file_id,
                    "file_name": message.document.file_name,
                    "mime_type": message.document.mime_type,
                    "file_size": message.document.file_size,
                    "file_url": file.file_path,
                }
            elif message.photo:
                photo = message.photo[-1]
                file = await photo.get_file()
                file_info = {
                    "file_id": photo.file_id,
                    "file_name": f"{photo.file_id}.jpg",
                    "mime_type": "image/jpeg",
                    "file_size": photo.file_size,
                    "file_url": file.file_path,
                }
            elif message.video:
                file = await message.video.get_file()
                file_info = {
                    "file_id": message.video.file_id,
                    "file_name": message.video.file_name,
                    "mime_type": message.video.mime_type,
                    "file_size": message.video.file_size,
                    "file_url": file.file_path,
                }

            new_members = [member.to_dict() for member in message.new_chat_members] if message.new_chat_members else []

            return {
                "message_id": update.update_id,
                "content": content,
                "file": file_info,
                "user": str(message.from_user.id),
                "is_bot": message.from_user.is_bot,
                "username": message.from_user.username,
                "chat_id": message.chat.id,
                "chat_type": message.chat.type,
                "chat_title": message.chat.title,
                "has_mention": bool(handle and handle in content),
                "has_reply": bool(message.reply_to_message),
                "reply_text": (message.reply_to_message.text if message.reply_to_message else ""),
                "reply_user": (message.reply_to_message.from_user.username if message.reply_to_message else ""),
                "new_members": new_members,
                "has_new_members": bool(new_members),
            }

        except Exception as e:
            print(f"Error processing update: {e}")
            return None
