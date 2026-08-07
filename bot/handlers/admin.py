"""Команды администратора в Telegram (рассылка пользователям)."""
import httpx
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.config import settings
from bot.handlers.user import _api, _internal_headers

router = Router()


def _is_admin(user_id: int) -> bool:
    aid = (settings.admin_telegram_id or "").strip()
    if not aid:
        return False
    try:
        return user_id == int(aid)
    except ValueError:
        return False


class BroadcastStates(StatesGroup):
    wait_text = State()


def _audience_keyboard(prefix: str = "bc_aud") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="С активным конфигом VPN", callback_data=f"{prefix}:with_vpn")],
        [InlineKeyboardButton(text="С активной подпиской", callback_data=f"{prefix}:active_subscription")],
        [InlineKeyboardButton(text="Всем пользователям бота", callback_data=f"{prefix}:all")],
        [InlineKeyboardButton(text="Отмена", callback_data=f"{prefix}:cancel")],
    ])


def _confirm_keyboard(audience: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data=f"bc_send:{audience}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="bc_send:cancel"),
        ],
    ])


def _notify_endpoint_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="bc_preset:endpoint:send"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="bc_preset:endpoint:cancel"),
        ],
    ])


@router.message(Command("admin"))
async def cmd_admin_help(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        "<b>Команды администратора</b>\n\n"
        "/notify_endpoint — рассылка об обновлении конфига (пользователям с VPN)\n"
        "/broadcast — произвольное сообщение (выбор аудитории)\n"
        "/cancel — отменить ввод текста рассылки",
        parse_mode="HTML",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Отменено.")


@router.message(Command("notify_endpoint"))
async def cmd_notify_endpoint(message: Message):
    """Готовая рассылка про блокировку домена и обновление Endpoint."""
    if not _is_admin(message.from_user.id):
        return
    if not _internal_headers():
        await message.answer("Не настроен INTERNAL_SECRET в .env.")
        return
    try:
        preview = await _api(
            "GET",
            "/api/internal/broadcast/preview?preset=endpoint_update&audience=with_vpn",
            headers=_internal_headers(),
        )
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return
    count = preview.get("count", 0)
    text = preview.get("text", "")
    await message.answer(
        f"<b>Предпросмотр рассылки</b> ({count} получателей с активным конфигом):\n\n{text}",
        parse_mode="HTML",
        reply_markup=_notify_endpoint_confirm_keyboard(),
    )


@router.callback_query(F.data.startswith("bc_preset:endpoint:"))
async def cb_preset_endpoint(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только администратор.", show_alert=True)
        return
    action = callback.data.split(":")[-1]
    if action == "cancel":
        await callback.answer("Отменено.")
        try:
            await callback.message.edit_text("Рассылка отменена.")
        except Exception:
            pass
        return
    if not _internal_headers():
        await callback.answer("INTERNAL_SECRET не настроен.", show_alert=True)
        return
    await callback.answer("Отправляю…")
    try:
        result = await _api(
            "POST",
            "/api/internal/broadcast-preset",
            json={"preset": "endpoint_update", "audience": "with_vpn"},
            headers=_internal_headers(),
        )
    except httpx.HTTPStatusError as e:
        await callback.message.answer(f"Ошибка API: {e.response.text}")
        return
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
        return
    await callback.message.answer(
        f"✅ Рассылка завершена.\n"
        f"Всего: {result.get('total', 0)}\n"
        f"Доставлено: {result.get('sent', 0)}\n"
        f"Не доставлено: {result.get('failed', 0)}",
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "Выберите, кому отправить сообщение:",
        reply_markup=_audience_keyboard(),
    )


@router.callback_query(F.data.startswith("bc_aud:"))
async def cb_broadcast_audience(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только администратор.", show_alert=True)
        return
    audience = callback.data.split(":", 1)[1]
    if audience == "cancel":
        await state.clear()
        await callback.answer("Отменено.")
        await callback.message.edit_text("Рассылка отменена.")
        return
    await state.update_data(audience=audience)
    await state.set_state(BroadcastStates.wait_text)
    await callback.answer()
    labels = {
        "all": "всем пользователям",
        "with_vpn": "пользователям с активным конфигом",
        "active_subscription": "пользователям с активной подпиской",
    }
    await callback.message.edit_text(
        f"Аудитория: <b>{labels.get(audience, audience)}</b>\n\n"
        "Отправьте текст сообщения (поддерживается HTML: &lt;b&gt;, &lt;i&gt;, &lt;code&gt;).\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


@router.message(BroadcastStates.wait_text, F.text)
async def broadcast_wait_text(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    audience = data.get("audience", "with_vpn")
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пустое сообщение. Отправьте текст или /cancel.")
        return
    await state.update_data(pending_text=text, text=text)
    await state.set_state(None)
    if not _internal_headers():
        await message.answer("Не настроен INTERNAL_SECRET.")
        return
    try:
        preview = await _api(
            "GET",
            f"/api/internal/broadcast/count?audience={audience}",
            headers=_internal_headers(),
        )
        count = preview.get("count", 0)
    except Exception as e:
        await message.answer(f"Не удалось получить число получателей: {e}")
        return
    await message.answer(
        f"<b>Предпросмотр</b> ({count} получателей):\n\n{text}",
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(audience),
    )


@router.message(BroadcastStates.wait_text)
async def broadcast_wait_non_text(message: Message):
    if not _is_admin(message.from_user.id):
        return
    await message.answer("Отправьте текст сообщения или /cancel.")


@router.callback_query(F.data.startswith("bc_send:"))
async def cb_broadcast_send(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только администратор.", show_alert=True)
        return
    audience = callback.data.split(":", 1)[1]
    if audience == "cancel":
        await state.clear()
        await callback.answer("Отменено.")
        try:
            await callback.message.edit_text("Рассылка отменена.")
        except Exception:
            pass
        return
    data = await state.get_data()
    text = (data.get("pending_text") or data.get("text") or "").strip()
    if not text:
        await callback.answer("Нет текста. Начните с /broadcast.", show_alert=True)
        return
    if not _internal_headers():
        await callback.answer("INTERNAL_SECRET не настроен.", show_alert=True)
        return
    await callback.answer("Отправляю…")
    try:
        result = await _api(
            "POST",
            "/api/internal/broadcast",
            json={"audience": audience, "text": text},
            headers=_internal_headers(),
        )
    except httpx.HTTPStatusError as e:
        await callback.message.answer(f"Ошибка API: {e.response.text}")
        return
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
        return
    await state.clear()
    await callback.message.answer(
        f"✅ Рассылка завершена.\n"
        f"Всего: {result.get('total', 0)}\n"
        f"Доставлено: {result.get('sent', 0)}\n"
        f"Не доставлено: {result.get('failed', 0)}",
    )
