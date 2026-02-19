import httpx
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.keyboards import main_keyboard
from app.config import settings
from app.services.telegram_notify import CONFIG_WARNING, config_to_qr_png, send_message


def _payment_info_text() -> str:
    """Официальный текст реквизитов для оплаты подписки."""
    amount = int(settings.subscription_amount)
    phone = (settings.payment_phone or "").strip()
    if phone:
        recipient = f"на номер телефона <b>{phone}</b>"
    else:
        recipient = "на номер телефона (уточните у администратора)"
    return (
        "<b>Реквизиты для оплаты подписки</b>\n\n"
        f"Оплата производится переводом {recipient}.\n\n"
        "В сообщении к переводу <b>ничего не указывайте</b> и не пишите.\n\n"
        f"Стоимость подписки: <b>{amount} ₽ в месяц</b>."
    )

router = Router()

# Описание товара: показываем при нажатии «Подключиться»
PRODUCT_DESCRIPTION = (
    "🔒 <b>VPN-подписка</b>\n\n"
    "Доступ в интернет через защищённый туннель: шифрование трафика, смена IP, "
    "обход блокировок. Один конфиг — одно устройство (телефон, ноутбук или ПК).\n\n"
    "После оплаты вы получите конфиг для приложения WireGuard — установите приложение, "
    "добавьте туннель по конфигу или QR-коду и подключайтесь в один клик."
)


class ConnectVPN(StatesGroup):
    wait_months = State()       # выбор срока подписки
    wait_config_name = State()  # ввод названия конфига


async def _api(method: str, path: str, json: dict | None = None, headers: dict | None = None) -> dict | list:
    url = f"{settings.backend_url.rstrip('/')}{path}"
    async with httpx.AsyncClient() as client:
        if method == "GET":
            r = await client.get(url, timeout=10.0, headers=headers)
        else:
            r = await client.post(url, json=json or {}, timeout=10.0, headers=headers)
        r.raise_for_status()
        return r.json()


def _internal_headers() -> dict:
    """Заголовок для внутреннего API (подтверждение оплаты из Telegram)."""
    secret = (settings.internal_secret or "").strip()
    return {"X-Internal-Secret": secret} if secret else {}


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    try:
        data = await _api("POST", "/api/register", {
            "telegram_id": message.from_user.id,
            "telegram_username": message.from_user.username,
            "full_name": message.from_user.full_name,
        })
    except Exception as e:
        await message.answer(f"Ошибка регистрации: {e}")
        return
    await message.answer(
        "👋 Добро пожаловать. Выберите действие:",
        reply_markup=main_keyboard(),
    )


@router.message(F.text.in_(["Подключиться", "🔗 Подключиться"]))
async def connect_vpn(message: Message, state: FSMContext):
    await state.set_state(ConnectVPN.wait_months)
    await message.answer(PRODUCT_DESCRIPTION, parse_mode="HTML")
    await message.answer(
        "📅 Выберите срок подписки:",
        reply_markup=_months_keyboard(),
    )


def _months_keyboard():
    """Клавиатура выбора срока подписки (100 ₽/мес)."""
    price = int(settings.subscription_amount)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"1 месяц — {price} ₽", callback_data="sub_months:1"),
            InlineKeyboardButton(text=f"3 месяца — {price * 3} ₽", callback_data="sub_months:3"),
        ],
        [
            InlineKeyboardButton(text=f"5 месяцев — {price * 5} ₽", callback_data="sub_months:5"),
            InlineKeyboardButton(text=f"12 месяцев — {price * 12} ₽", callback_data="sub_months:12"),
        ],
    ])


@router.callback_query(F.data.startswith("sub_months:"))
async def connect_vpn_choose_months(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        months = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.message.answer("Ошибка выбора. Начните заново: «Подключиться».")
        await state.clear()
        return
    if months not in (1, 3, 5, 12):
        months = 1
    await state.update_data(months=months)
    await state.set_state(ConnectVPN.wait_config_name)
    await callback.message.answer(
        "✏️ Введите название конфига на любом языке (например: Телефон, Ноутбук) — так вам будет проще выбирать конфиг потом. "
        "Или отправьте «-» чтобы пропустить."
    )


@router.message(ConnectVPN.wait_config_name, F.text)
async def connect_vpn_enter_name(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    display_name = None if raw == "-" else (raw[:128] if raw else None)
    data = await state.get_data()
    months = data.get("months", 1)
    await state.clear()
    try:
        result = await _api("POST", "/api/payment/request", {
            "telegram_id": message.from_user.id,
            "display_name": display_name,
            "months": months,
        })
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            await message.answer(
                "У вас уже есть заявка на подключение. Ожидайте подтверждения или нажмите «Я оплатил» после перевода."
            )
            return
        await message.answer(f"Ошибка: {e.response.text}")
        return
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return
    payment_id = result.get("payment_id")
    amount = int(settings.subscription_amount) * months
    text = (
        f"📋 Заявка создана на <b>{months} мес.</b> (к оплате {amount} ₽).\n\n"
        + _payment_info_text() + "\n\n"
        "После перевода нажмите кнопку ниже — заявка уйдёт администратору на подтверждение. После подтверждения вам придёт конфиг для подключения."
    )
    pay_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"i_paid:{payment_id}")],
    ])
    await _send_payment_info(message, text, pay_keyboard)


async def _send_payment_info(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """Отправить реквизиты: при наличии SBP QR — фото с подписью, иначе текст."""
    qr_url = (getattr(settings, "payment_sbp_qr_url", None) or "").strip()
    if qr_url:
        try:
            await message.answer_photo(photo=qr_url, caption=text, parse_mode="HTML", reply_markup=reply_markup)
            return
        except Exception:
            pass
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@router.callback_query(F.data.startswith("i_paid:"))
async def i_paid_callback(callback: CallbackQuery):
    """Пользователь нажал «Я оплатил» под сообщением с реквизитами — отправляем заявку админу."""
    await callback.answer()
    try:
        payment_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.message.answer("Ошибка. Нажмите «Я оплатил» в главном меню после перевода.")
        return
    await callback.message.answer(
        "Заявка отправлена администратору. Ожидайте подтверждения — после подтверждения оплаты вам придёт конфиг в этот чат."
    )
    if _internal_headers():
        try:
            await _api(
                "POST",
                "/api/internal/admin-notify-payment",
                json={"payment_id": payment_id},
                headers=_internal_headers(),
            )
        except Exception:
            pass


@router.message(F.text.in_(["Я оплатил", "✅ Я оплатил"]))
async def i_paid(message: Message):
    await message.answer(
        "Ожидайте подтверждения от администратора. После подтверждения оплаты "
        "вам придёт конфиг WireGuard в этот чат."
    )
    try:
        data = await _api("GET", f"/api/user/by-telegram/{message.from_user.id}/pending-payment")
        payment_id = data.get("payment_id")
        if payment_id and _internal_headers():
            await _api(
                "POST",
                "/api/internal/admin-notify-payment",
                json={"payment_id": payment_id},
                headers=_internal_headers(),
            )
    except Exception:
        pass


def _fmt_date(iso_date: str | None) -> str:
    if not iso_date:
        return "—"
    try:
        parts = iso_date[:10].split("-")
        return f"{parts[2]}.{parts[1]}.{parts[0]}" if len(parts) == 3 else iso_date[:10]
    except Exception:
        return iso_date[:10] or "—"


@router.message(F.text.in_(["Моя подписка", "📋 Моя подписка"]))
async def my_subscription(message: Message):
    try:
        items = await _api("GET", f"/api/user/by-telegram/{message.from_user.id}/subscriptions")
    except Exception:
        await message.answer("Не удалось получить данные. Обратитесь к администратору.")
        return
    if not items:
        await message.answer("У вас пока нет подписок. Нажмите «Подключиться».")
        return
    lines = []
    for s in items:
        name = s.get("display_name") or f"Конфиг #{s.get('id', '?')}"
        status = s.get("status", "")
        is_blocked = s.get("is_blocked", False)
        if is_blocked and status == "active":
            lines.append(f"• <b>{name}</b>: доступ приостановлен администратором")
        elif status == "pending_payment":
            lines.append(f"• <b>{name}</b>: ожидает подтверждения оплаты")
        elif status == "active":
            exp = _fmt_date(s.get("expires_at"))
            lines.append(f"• <b>{name}</b>: активна до {exp}")
        elif status == "expired":
            exp = _fmt_date(s.get("expires_at"))
            lines.append(f"• <b>{name}</b>: истекла {exp}")
        elif status == "blocked":
            lines.append(f"• <b>{name}</b>: доступ приостановлен администратором")
        else:
            lines.append(f"• <b>{name}</b>: {status}")
    await message.answer("📋 Ваши подписки:\n\n" + "\n".join(lines))


def _config_format_keyboard(vpn_client_id: int | None = None) -> InlineKeyboardMarkup:
    suffix = f":{vpn_client_id}" if vpn_client_id is not None else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Текст конфига (файл)", callback_data=f"cfg:txt{suffix}"),
            InlineKeyboardButton(text="QR-код", callback_data=f"cfg:qr{suffix}"),
        ],
    ])


@router.message(F.text.in_(["Получить конфиг", "📥 Получить конфиг"]))
async def get_config(message: Message):
    try:
        configs = await _api("GET", f"/api/user/by-telegram/{message.from_user.id}/vpn-configs")
    except Exception:
        await message.answer("Ошибка запроса.")
        return
    if not configs:
        await message.answer(
            "Конфиг недоступен. Если вы уже получали конфиг ранее, возможно, доступ приостановлен администратором. "
            "Обратитесь в поддержку."
        )
        return
    if len(configs) == 1:
        cid = configs[0]["id"]
        await message.answer(
            "Выберите формат выдачи конфига:",
            reply_markup=_config_format_keyboard(cid),
        )
        return
    # Несколько конфигов — выбор по удобному названию
    buttons = [
        [InlineKeyboardButton(
            text=c.get("display_name") or c.get("name") or f"Конфиг #{i+1}",
            callback_data=f"cfg_sel:{c['id']}",
        )]
        for i, c in enumerate(configs)
    ]
    await message.answer(
        "У вас несколько конфигов. Выберите, какой получить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("confirm_pay:") | F.data.startswith("reject_pay:"))
async def admin_confirm_payment(callback: CallbackQuery):
    """Обработка кнопок «Подтвердить»/«Отклонить» в уведомлении админу — только для admin_telegram_id."""
    aid = (settings.admin_telegram_id or "").strip()
    if not aid or callback.from_user.id != int(aid):
        await callback.answer("Доступ только у администратора.", show_alert=True)
        return
    is_confirm = callback.data.startswith("confirm_pay:")
    try:
        payment_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка данных.", show_alert=True)
        return
    if not _internal_headers():
        await callback.answer("Не настроен INTERNAL_SECRET.", show_alert=True)
        return
    try:
        await _api(
            "POST",
            "/api/internal/confirm-payment",
            json={"payment_id": payment_id, "action": "confirm" if is_confirm else "reject"},
            headers=_internal_headers(),
        )
    except httpx.HTTPStatusError as e:
        await callback.answer(f"Ошибка: {e.response.text}", show_alert=True)
        return
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return
    await callback.answer("Подтверждено." if is_confirm else "Отклонено.", show_alert=True)
    try:
        suffix = "\n\n✅ Оплата подтверждена." if is_confirm else "\n\n❌ Оплата отклонена."
        await callback.message.edit_text((callback.message.text or "") + suffix)
    except Exception:
        pass


async def _send_config_by_id(callback: CallbackQuery, vpn_client_id: int, as_qr: bool) -> None:
    """Получить конфиг по vpn_client_id и отправить текстом или QR (для активации и «Получить конфиг»)."""
    url = f"/api/user/by-telegram/{callback.from_user.id}/vpn-config?vpn_client_id={vpn_client_id}"
    try:
        data = await _api("GET", url)
    except Exception:
        await callback.message.answer("Ошибка запроса.")
        return
    config = data.get("config")
    if not config:
        await callback.message.answer("Конфиг недоступен.")
        return
    if as_qr:
        caption = f"{CONFIG_WARNING}\n\nQR-код конфига — отсканируйте в приложении WireGuard."
        qr_bytes = config_to_qr_png(config)
        if qr_bytes:
            await callback.message.answer_photo(
                BufferedInputFile(qr_bytes, filename="qr.png"),
                caption=caption,
                parse_mode="HTML",
            )
        else:
            await callback.message.answer("Не удалось сгенерировать QR. Запросите конфиг текстом.")
    else:
        text = (
            f"{CONFIG_WARNING}\n\n"
            "Ваш конфиг WireGuard (скопируйте в приложение или сохраните как .conf):\n\n"
            f"<pre>{config.replace('<', '&lt;').replace('>', '&gt;')}</pre>"
        )
        await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("act_cfg:txt:"))
async def activation_send_config_text(callback: CallbackQuery):
    """После активации подписки пользователь выбрал «Текст конфига»."""
    await callback.answer()
    try:
        vpn_client_id = int(callback.data.split(":", 2)[2])
    except (IndexError, ValueError):
        await callback.message.answer("Ошибка данных.")
        return
    await _send_config_by_id(callback, vpn_client_id, as_qr=False)


@router.callback_query(F.data.startswith("act_cfg:qr:"))
async def activation_send_config_qr(callback: CallbackQuery):
    """После активации подписки пользователь выбрал «QR-код»."""
    await callback.answer()
    try:
        vpn_client_id = int(callback.data.split(":", 2)[2])
    except (IndexError, ValueError):
        await callback.message.answer("Ошибка данных.")
        return
    await _send_config_by_id(callback, vpn_client_id, as_qr=True)


def _parse_cfg_callback(data: str) -> tuple[str, int | None]:
    """Из callback_data 'cfg:txt' или 'cfg:txt:123' возвращает ('txt', None) или ('txt', 123)."""
    parts = data.split(":", 2)
    if len(parts) >= 3:
        try:
            return parts[1], int(parts[2])
        except ValueError:
            pass
    return (parts[1], None) if len(parts) >= 2 else ("txt", None)


@router.callback_query(F.data.startswith("cfg_sel:"))
async def choose_config_then_format(callback: CallbackQuery):
    """После выбора конфига из списка — показать кнопки Текст/QR."""
    await callback.answer()
    try:
        vpn_client_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.message.answer("Ошибка данных.")
        return
    await callback.message.answer(
        "Выберите формат выдачи конфига:",
        reply_markup=_config_format_keyboard(vpn_client_id),
    )


@router.callback_query(F.data.startswith("cfg:txt"))
async def send_config_text(callback: CallbackQuery):
    await callback.answer()
    _, vpn_client_id = _parse_cfg_callback(callback.data)
    url = f"/api/user/by-telegram/{callback.from_user.id}/vpn-config"
    if vpn_client_id is not None:
        url += f"?vpn_client_id={vpn_client_id}"
    try:
        data = await _api("GET", url)
    except Exception:
        await callback.message.answer("Ошибка запроса.")
        return
    config = data.get("config")
    if not config:
        await callback.message.answer("Конфиг недоступен.")
        return
    text = (
        f"{CONFIG_WARNING}\n\n"
        "Ваш конфиг WireGuard (скопируйте в приложение или сохраните как .conf):\n\n"
        f"<pre>{config.replace('<', '&lt;').replace('>', '&gt;')}</pre>"
    )
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("cfg:qr"))
async def send_config_qr(callback: CallbackQuery):
    await callback.answer()
    _, vpn_client_id = _parse_cfg_callback(callback.data)
    url = f"/api/user/by-telegram/{callback.from_user.id}/vpn-config"
    if vpn_client_id is not None:
        url += f"?vpn_client_id={vpn_client_id}"
    try:
        data = await _api("GET", url)
    except Exception:
        await callback.message.answer("Ошибка запроса.")
        return
    config = data.get("config")
    if not config:
        await callback.message.answer("Конфиг недоступен.")
        return
    caption = f"{CONFIG_WARNING}\n\nQR-код конфига — отсканируйте в приложении WireGuard."
    qr_bytes = config_to_qr_png(config)
    if qr_bytes:
        await callback.message.answer_photo(
            BufferedInputFile(qr_bytes, filename="qr.png"),
            caption=caption,
            parse_mode="HTML",
        )
    else:
        await callback.message.answer("Не удалось сгенерировать QR. Запросите конфиг текстом.")


INSTALL_INSTRUCTIONS = """
<b>Инструкция по установке WireGuard</b>

<b>1. Установите приложение WireGuard</b>
• Телефон: <a href="https://apps.apple.com/app/wireguard/id1441195209">iOS</a> или <a href="https://play.google.com/store/apps/details?id=com.wireguard.android">Android</a>
• Windows: <a href="https://www.wireguard.com/install/">официальный сайт</a>
• macOS: App Store или wireguard.com/install

<b>2. Получите конфиг</b>
После подтверждения оплаты администратором вы получите в этот чат:
• текст конфига — можно скопировать целиком;
• или QR-код — удобно для телефона (сканируйте камерой в приложении).

Кнопка «Получить конфиг» — повторно запросить конфиг, если уже получили его ранее.

<b>3. Добавьте туннель</b>
• <b>Телефон:</b> Откройте WireGuard → «Добавить туннель» → «Создать из QR-кода» (если прислали QR) или «Создать из файла или архива» / вставьте конфиг из буфера.
• <b>ПК:</b> Импорт туннелей из файла (.conf) или вставка конфига из буфера.

<b>4. Подключитесь</b>
Включите туннель переключателем. После подключения весь трафик идёт через VPN.

Если конфиг не подключается — проверьте интернет и что подписка активна («Моя подписка»).
"""


@router.message(F.text.in_(["Реквизиты для оплаты", "💳 Реквизиты для оплаты"]))
async def payment_info(message: Message):
    await _send_payment_info(message, _payment_info_text())


@router.message(F.text.in_(["Инструкция по установке", "📖 Инструкция по установке"]))
async def install_instructions(message: Message):
    await message.answer(INSTALL_INSTRUCTIONS, parse_mode="HTML")
