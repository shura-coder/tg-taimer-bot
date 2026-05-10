import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeAllGroupChats,
)

TOKEN = "8749867081:AAExkjw5oZRjT2vgSwkptaHd9XER8_Sr0zU"

bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


@dataclass
class TimerData:
    task: asyncio.Task
    owner_id: int
    title: str
    total_seconds: int
    message_id: Optional[int] = None


active_timers: Dict[int, TimerData] = {}


def format_time(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if days > 0:
        parts.append(f"{days}д")
    parts.append(f"{hours:02}ч")
    parts.append(f"{minutes:02}м")
    parts.append(f"{secs:02}с")
    return " ".join(parts)


def build_stop_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⛔ Остановить таймер",
                    callback_data=f"stop_timer:{chat_id}"
                )
            ]
        ]
    )


def parse_duration(text: str) -> Optional[int]:
    text = text.strip().lower().replace(" ", "")
    if not text:
        return None

    pattern = r"(\d+)([dhmsдчмс])"
    matches = re.findall(pattern, text)
    if not matches:
        return None

    rebuilt = "".join(f"{value}{unit}" for value, unit in matches)
    if rebuilt != text:
        return None

    total = 0
    for value, unit in matches:
        value = int(value)

        if unit in ("d", "д"):
            total += value * 86400
        elif unit in ("h", "ч"):
            total += value * 3600
        elif unit in ("m", "м"):
            total += value * 60
        elif unit in ("s", "с"):
            total += value

    return total if total > 0 else None


async def is_admin_or_owner(message: Message) -> bool:
    # Если сообщение отправлено анонимно от имени группы/чата,
    # Telegram может не дать нормальный from_user.
    # В таком режиме обычно это и есть админ/владелец.
    if message.sender_chat and not message.from_user:
        return True

    if not message.from_user:
        return False

    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        admin_ids = {member.user.id for member in admins}
        return message.from_user.id in admin_ids
    except Exception as e:
        print(f"is_admin_or_owner error: {e}")
        return False


async def is_admin_or_owner_by_user_id(chat_id: int, user_id: int) -> bool:
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = {member.user.id for member in admins}
        return user_id in admin_ids
    except Exception as e:
        print(f"is_admin_or_owner_by_user_id error: {e}")
        return False


async def stop_timer_in_chat(chat_id: int) -> bool:
    timer = active_timers.get(chat_id)
    if not timer:
        return False

    timer.task.cancel()
    try:
        await timer.task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

    active_timers.pop(chat_id, None)
    return True


async def timer_worker(chat_id: int, title: str, duration_seconds: int, owner_id: int):
    timer_message: Optional[Message] = None

    try:
        timer_message = await bot.send_message(
            chat_id=chat_id,
            text=(
                f"<b>{title}</b>\n"
                f"-----------------------\n"
                f"осталось времени {format_time(duration_seconds)}"
            ),
            reply_markup=build_stop_keyboard(chat_id)
        )

        if chat_id in active_timers:
            active_timers[chat_id].message_id = timer_message.message_id

        for remaining in range(duration_seconds - 1, -1, -1):
            await asyncio.sleep(1)

            if chat_id not in active_timers:
                return

            text = (
                f"<b>{title}</b>\n"
                f"-----------------------\n"
                f"осталось времени {format_time(remaining)}"
            )

            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=timer_message.message_id,
                    text=text,
                    reply_markup=build_stop_keyboard(chat_id)
                )
            except Exception:
                pass

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=timer_message.message_id,
                text=(
                    f"<b>{title}</b>\n"
                    f"-----------------------\n"
                    f"⏰ <b>ВРЕМЯ ВЫШЛО</b>"
                ),
                reply_markup=None
            )
        except Exception:
            pass

    except asyncio.CancelledError:
        if timer_message:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=timer_message.message_id,
                    text=(
                        f"<b>{title}</b>\n"
                        f"-----------------------\n"
                        f"⛔ <b>ТАЙМЕР ОСТАНОВЛЕН</b>"
                    ),
                    reply_markup=None
                )
            except Exception:
                pass
        raise

    finally:
        current = active_timers.get(chat_id)
        if current and current.owner_id == owner_id:
            active_timers.pop(chat_id, None)


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Я бот таймеров.\n\n"
        "Примеры:\n"
        "<code>/timer 45s Тест</code>\n"
        "<code>/timer 10m Новое обновление</code>\n"
        "<code>/timer 2h Ивент</code>\n"
        "<code>/timer 1d До релиза</code>\n\n"
        "Дополнительно:\n"
        "<code>/whoami</code> — показать, как бот видит твой статус"
    )


@dp.message(Command("whoami"))
async def cmd_whoami(message: Message):
    lines = [
        f"chat_id: <code>{message.chat.id}</code>",
        f"chat_type: <code>{message.chat.type}</code>",
    ]

    if message.from_user:
        lines.append(f"from_user.id: <code>{message.from_user.id}</code>")
        lines.append(f"from_user.full_name: <code>{message.from_user.full_name}</code>")
    else:
        lines.append("from_user: <code>None</code>")

    if message.sender_chat:
        lines.append(f"sender_chat.id: <code>{message.sender_chat.id}</code>")
        lines.append(f"sender_chat.title: <code>{message.sender_chat.title}</code>")
    else:
        lines.append("sender_chat: <code>None</code>")

    allowed = await is_admin_or_owner(message)
    lines.append(f"admin_check: <code>{allowed}</code>")

    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        admin_list = [f"{a.user.full_name} ({a.user.id})" for a in admins]
        lines.append("")
        lines.append("<b>Админы, которых видит бот:</b>")
        lines.extend([f"• <code>{x}</code>" for x in admin_list[:20]])
    except Exception as e:
        lines.append(f"admins_error: <code>{e}</code>")

    await message.answer("\n".join(lines))


@dp.message(Command("timer"))
async def cmd_timer(message: Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.answer("Эта команда работает только в группе.")
        return

    if not await is_admin_or_owner(message):
        await message.answer(
            "❌ Команда доступна только администраторам и владельцу.\n"
            "Отправь <code>/whoami</code>, чтобы я показал, как вижу твой статус."
        )
        return

    if not message.text:
        await message.answer("Пример:\n<code>/timer 10m Новое обновление!!</code>")
        return

    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.answer(
            "Пример:\n"
            "<code>/timer 10m Новое обновление!!</code>\n\n"
            "Поддержка:\n"
            "<code>45s</code>, <code>10m</code>, <code>2h</code>, <code>1d</code>, <code>1h30m</code>"
        )
        return

    duration_text = parts[1].strip()
    title = parts[2].strip()

    duration_seconds = parse_duration(duration_text)
    if duration_seconds is None:
        await message.answer(
            "❌ Неверный формат времени.\n\n"
            "Примеры:\n"
            "<code>/timer 45s Тест</code>\n"
            "<code>/timer 10m Новое обновление</code>\n"
            "<code>/timer 2h Ивент</code>\n"
            "<code>/timer 1d Релиз</code>\n"
            "<code>/timer 1h30m Комбинированный таймер</code>"
        )
        return

    if duration_seconds > 20 * 86400:
        await message.answer("❌ Максимум: 20 дней.")
        return

    if message.chat.id in active_timers:
        await stop_timer_in_chat(message.chat.id)

    owner_id = message.from_user.id if message.from_user else 0

    task = asyncio.create_task(
        timer_worker(
            chat_id=message.chat.id,
            title=title,
            duration_seconds=duration_seconds,
            owner_id=owner_id
        )
    )

    active_timers[message.chat.id] = TimerData(
        task=task,
        owner_id=owner_id,
        title=title,
        total_seconds=duration_seconds
    )

    await message.answer(
        f"✅ Таймер запущен: <b>{title}</b>\n"
        f"Длительность: <b>{format_time(duration_seconds)}</b>"
    )


@dp.callback_query(F.data.startswith("stop_timer:"))
async def stop_timer_callback(callback: CallbackQuery):
    if not callback.message or not callback.from_user:
        await callback.answer()
        return

    try:
        _, chat_id_str = callback.data.split(":", 1)
        chat_id = int(chat_id_str)
    except Exception:
        await callback.answer("Ошибка данных кнопки.", show_alert=True)
        return

    if callback.message.chat.id != chat_id:
        await callback.answer("Нельзя остановить чужой таймер.", show_alert=True)
        return

    is_allowed = await is_admin_or_owner_by_user_id(chat_id, callback.from_user.id)
    if not is_allowed:
        await callback.answer("❌ Только админ или владелец может остановить таймер.", show_alert=True)
        return

    if chat_id not in active_timers:
        await callback.answer("Таймер уже остановлен.")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    await stop_timer_in_chat(chat_id)
    await callback.answer("Таймер остановлен.")


async def set_group_commands():
    await bot.set_my_commands(
        [
            BotCommand(command="timer", description="Запустить таймер"),
            BotCommand(command="whoami", description="Проверить права"),
        ],
        scope=BotCommandScopeAllGroupChats()
    )


async def main():
    logging.basicConfig(level=logging.INFO)
    await set_group_commands()
    print("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())