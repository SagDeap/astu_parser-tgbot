import os
import logging
import asyncio
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler
from telegram.error import TelegramError, NetworkError, TimedOut
from telegram.request import HTTPXRequest
import parser
import db  
from datetime import datetime


load_dotenv()

# Настройка логирования, удалите есть спам в консоли не нравится)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


CHOOSING_GROUP, CHOOSING_SCHEDULE = range(2)

# Словарь для хранения выбранной группы пользователем (временное хранилище), если впадлу использовать БД, хотя объективно она тут не нужна, но эт уже моя шиза
# user_groups = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Тут группы свои ставим, которые надо (тестировал только на 3ех, как будет при 4 и более я хз)
    try:
        keyboard = [
            [
                InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🎓 Добро пожаловать в бот расписания АлтГТУ!\n\n"
            "Выберите вашу группу:",
            reply_markup=reply_markup
        )
        
        return CHOOSING_GROUP
    except Exception as e:
        logger.error(f"Ошибка в обработчике start: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте еще раз позже.")
        return ConversationHandler.END

async def group_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик выбора группы."""
    try:
        query = update.callback_query
        await query.answer()
        
        # Получаем выбранную группу
        group = query.data.split("_")[1]
        
        # Сохраняем выбор пользователя в базе данных
        user_id = update.effective_user.id
        db.save_user_group(user_id, group)
        
        keyboard = [
            [
                InlineKeyboardButton("На сегодня", callback_data="schedule_today"),
                InlineKeyboardButton("На завтра", callback_data="schedule_tomorrow"),
            ],
            [
                InlineKeyboardButton("Неделя 1", callback_data="schedule_week_1"),
                InlineKeyboardButton("Неделя 2", callback_data="schedule_week_2"),
            ],
            [
                InlineKeyboardButton("Изменить группу", callback_data="change_group"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"Выбрана группа: *{group}*\n\n"
            "Выберите период расписания:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        return CHOOSING_SCHEDULE
    except Exception as e:
        logger.error(f"Ошибка в обработчике group_selected: {e}")
        try:
            await query.edit_message_text("Произошла ошибка. Пожалуйста, попробуйте еще раз.")
        except:
            pass
        return ConversationHandler.END

async def schedule_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Тут тоже группы меняем
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        group = db.get_user_group(user_id)
        
        if not group:
            # Если группа не выбрана, предлагаем выбрать
            keyboard = [
                [
                    InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                    InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                    InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "Выберите группу:",
                reply_markup=reply_markup
            )
            return CHOOSING_GROUP
        
        schedule_type = query.data.split("_")[1]
        
        if schedule_type == "today":
            # Расписание на сегодня
            schedule_text = parser.get_today_schedule(group)
            # Добавляем кнопку "Назад"
            keyboard = [
                [InlineKeyboardButton("« Назад", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
        elif schedule_type == "tomorrow":
            
            schedule_text = parser.get_tomorrow_schedule(group)
           
            keyboard = [
                [InlineKeyboardButton("« Назад", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
        elif schedule_type.startswith("week"):
            
            week_number = int(query.data.split("_")[2])
            schedule_text = parser.get_week_schedule(group, week_number)
            
            # Добавляем кнопки навигации по дням для недельного расписания
            schedule = parser.parse_schedule(group)
            
            if schedule:
                for week in schedule.weeks:
                    if week.number == week_number and week.days:
                        # Сортируем дни по дате
                        sorted_days = sorted(week.days, key=lambda d: 
                            datetime.strptime(d.date, "%d.%m.%y") if "." in d.date else datetime.now())
                        
                        # Создаем кнопки для каждого дня недели
                        keyboard_days = []
                        row = []
                        
                        for day in sorted_days:
                            day_button = InlineKeyboardButton(
                                f"{day.date} ({day.weekday})", 
                                callback_data=f"day_{week_number}_{day.date}"
                            )
                            row.append(day_button)
                            
                            # Максимум 2 кнопки в ряду
                            if len(row) == 2:
                                keyboard_days.append(row)
                                row = []
                        
                        # Добавляем оставшиеся кнопки, если есть
                        if row:
                            keyboard_days.append(row)
                        
                        # Добавляем кнопку "Назад"
                        keyboard_days.append([InlineKeyboardButton("« Назад", callback_data="back_to_menu")])
                        reply_markup = InlineKeyboardMarkup(keyboard_days)
                        
                        # Отправляем сообщение
                        await query.edit_message_text(
                            schedule_text,
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                        return CHOOSING_SCHEDULE
            
           
            keyboard = [
                [InlineKeyboardButton("« Назад", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        else:
            schedule_text = "Неизвестный тип расписания."
            # Добавляем кнопку "Назад"
            keyboard = [
                [InlineKeyboardButton("« Назад", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            schedule_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        return CHOOSING_SCHEDULE
    except Exception as e:
        logger.error(f"Ошибка в обработчике schedule_selected: {e}")
        try:
            await query.edit_message_text("Произошла ошибка при получении расписания. Пожалуйста, попробуйте еще раз.")
            keyboard = [
                [InlineKeyboardButton("« Назад", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        except:
            pass
        return CHOOSING_SCHEDULE

async def show_day_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает расписание на конкретный день."""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        group = db.get_user_group(user_id)
        
        if not group:
            # Если группа не выбрана, предлагаем выбрать. Тут меняем на свои группы
            keyboard = [
                [
                    InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                    InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                    InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "Выберите группу:",
                reply_markup=reply_markup
            )
            return CHOOSING_GROUP
        
        # Получаем данные из callback
        data_parts = query.data.split("_")
        week_number = int(data_parts[1])
        date = data_parts[2]
        
        # Получаем расписание
        schedule = parser.parse_schedule(group)
        if not schedule:
            await query.edit_message_text(
                f"Не удалось получить расписание для группы {group}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Назад", callback_data="back_to_menu")]])
            )
            return CHOOSING_SCHEDULE
        
        # Ищем нужный день
        day_schedule = None
        day_obj = None
        week_obj = None
        
        for week in schedule.weeks:
            if week.number == week_number:
                week_obj = week
                for day in week.days:
                    if day.date == date:
                        day_obj = day
                        break
                break
        
        if not day_obj:
            await query.edit_message_text(
                f"Расписание на {date} для группы {group} не найдено",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Назад", callback_data=f"schedule_week_{week_number}")]])
            )
            return CHOOSING_SCHEDULE
        
        # Формируем текст расписания на выбранный день
        result = f"*Расписание группы {group} на {day_obj.date} ({day_obj.weekday})*\n\n"
        
        if day_obj.subjects:
            for subject in day_obj.subjects:
                result += f"{subject}\n"
        else:
            result += "Занятий нет"
        
        # Создаем кнопки навигации
        keyboard = []
        
        # Кнопки для перехода к предыдущему и следующему дню
        if week_obj:
            day_index = week_obj.days.index(day_obj)
            row = []
            
            # Кнопка для предыдущего дня
            if day_index > 0:
                prev_day = week_obj.days[day_index - 1]
                row.append(InlineKeyboardButton(
                    f"« {prev_day.date}",
                    callback_data=f"day_{week_number}_{prev_day.date}"
                ))
            
            # Кнопка для следующего дня
            if day_index < len(week_obj.days) - 1:
                next_day = week_obj.days[day_index + 1]
                row.append(InlineKeyboardButton(
                    f"{next_day.date} »",
                    callback_data=f"day_{week_number}_{next_day.date}"
                ))
            
            if row:
                keyboard.append(row)
        
        # Кнопка для возврата к недельному расписанию
        keyboard.append([InlineKeyboardButton("К неделе", callback_data=f"schedule_week_{week_number}")])
        keyboard.append([InlineKeyboardButton("« Назад в меню", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            result,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        return CHOOSING_SCHEDULE
    except Exception as e:
        logger.error(f"Ошибка в обработчике show_day_schedule: {e}")
        try:
            await query.edit_message_text("Произошла ошибка при получении расписания. Пожалуйста, попробуйте еще раз.")
            keyboard = [
                [InlineKeyboardButton("« Назад", callback_data="back_to_menu")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        except:
            pass
        return CHOOSING_SCHEDULE

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возвращает пользователя к меню выбора расписания."""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        group = db.get_user_group(user_id)
        
        keyboard = [
            [
                InlineKeyboardButton("На сегодня", callback_data="schedule_today"),
                InlineKeyboardButton("На завтра", callback_data="schedule_tomorrow"),
            ],
            [
                InlineKeyboardButton("Неделя 1", callback_data="schedule_week_1"),
                InlineKeyboardButton("Неделя 2", callback_data="schedule_week_2"),
            ],
            [
                InlineKeyboardButton("Изменить группу", callback_data="change_group"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"Выбрана группа: *{group}*\n\n"
            "Выберите период расписания:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        return CHOOSING_SCHEDULE
    except Exception as e:
        logger.error(f"Ошибка в обработчике back_to_menu: {e}")
        return CHOOSING_SCHEDULE

async def change_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Возвращает пользователя к выбору группы."""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [
                InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Выберите вашу группу:",
            reply_markup=reply_markup
        )
        
        return CHOOSING_GROUP
    except Exception as e:
        logger.error(f"Ошибка в обработчике change_group: {e}")
        return CHOOSING_GROUP

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help."""
    try:
        keyboard = [
            [
                InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = (
            "🔍 *Справка по боту расписания АлтГТУ*\n\n"
            "Этот бот позволяет просматривать расписание занятий для групп ИБ-41, ИБ-42, ИБ-43.\n\n"
            "Выберите группу для начала работы:"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в обработчике help_command: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте еще раз позже.")

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /today."""
    try:
        user_id = update.effective_user.id
        group = db.get_user_group(user_id)
        
        if not group:
            keyboard = [
                [
                    InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                    InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                    InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "⚠️ Сначала нужно выбрать группу:",
                reply_markup=reply_markup
            )
            return
        
        schedule_text = parser.get_today_schedule(group)
        
        # Добавляем кнопки навигации
        keyboard = [
            [
                InlineKeyboardButton("На завтра", callback_data="schedule_tomorrow"),
                InlineKeyboardButton("Неделя 1", callback_data="schedule_week_1"),
            ],
            [
                InlineKeyboardButton("Неделя 2", callback_data="schedule_week_2"),
                InlineKeyboardButton("Изменить группу", callback_data="change_group"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(schedule_text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в обработчике today_command: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте еще раз позже.")

async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /tomorrow."""
    try:
        user_id = update.effective_user.id
        group = db.get_user_group(user_id)
        
        if not group:
            keyboard = [
                [
                    InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                    InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                    InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "⚠️ Сначала нужно выбрать группу:",
                reply_markup=reply_markup
            )
            return
        
        schedule_text = parser.get_tomorrow_schedule(group)
        
        # Добавляем кнопки навигации
        keyboard = [
            [
                InlineKeyboardButton("На сегодня", callback_data="schedule_today"),
                InlineKeyboardButton("Неделя 1", callback_data="schedule_week_1"),
            ],
            [
                InlineKeyboardButton("Неделя 2", callback_data="schedule_week_2"),
                InlineKeyboardButton("Изменить группу", callback_data="change_group"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(schedule_text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в обработчике tomorrow_command: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте еще раз позже.")

async def week1_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /week1."""
    try:
        user_id = update.effective_user.id
        group = db.get_user_group(user_id)
        
        if not group:
            keyboard = [
                [
                    InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                    InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                    InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "⚠️ Сначала нужно выбрать группу:",
                reply_markup=reply_markup
            )
            return
        
        schedule_text = parser.get_week_schedule(group, 1)
        
        # Добавляем кнопки навигации
        keyboard = [
            [
                InlineKeyboardButton("На сегодня", callback_data="schedule_today"),
                InlineKeyboardButton("На завтра", callback_data="schedule_tomorrow"),
            ],
            [
                InlineKeyboardButton("Неделя 2", callback_data="schedule_week_2"),
                InlineKeyboardButton("Изменить группу", callback_data="change_group"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(schedule_text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в обработчике week1_command: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте еще раз позже.")

async def week2_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /week2."""
    try:
        user_id = update.effective_user.id
        group = db.get_user_group(user_id)
        
        if not group:
            keyboard = [
                [
                    InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                    InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                    InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "⚠️ Сначала нужно выбрать группу:",
                reply_markup=reply_markup
            )
            return
        
        schedule_text = parser.get_week_schedule(group, 2)
        
        # Добавляем кнопки навигации
        keyboard = [
            [
                InlineKeyboardButton("На сегодня", callback_data="schedule_today"),
                InlineKeyboardButton("На завтра", callback_data="schedule_tomorrow"),
            ],
            [
                InlineKeyboardButton("Неделя 1", callback_data="schedule_week_1"),
                InlineKeyboardButton("Изменить группу", callback_data="change_group"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(schedule_text, parse_mode="Markdown", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Ошибка в обработчике week2_command: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте еще раз позже.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик ошибок телеграма."""
    logger.error(f"Ошибка: {context.error}")
    
    # Если ошибка связана с таймаутом или сетью
    if isinstance(context.error, (NetworkError, TimedOut)):
        logger.error("Ошибка сети. Повторная попытка через 5 секунд...")
        await asyncio.sleep(5)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик для всех кнопок, которые не попадают в ConversationHandler."""
    try:
        query = update.callback_query
        await query.answer()
        
        # Проверяем тип callback_data
        data = query.data
        logger.info(f"Получен callback от кнопки: {data}")
        
        if data.startswith("group_"):
            # Получаем выбранную группу
            group = data.split("_")[1]
            
            # Сохраняем выбор пользователя в базу данных
            user_id = update.effective_user.id
            db.save_user_group(user_id, group)
            
            keyboard = [
                [
                    InlineKeyboardButton("На сегодня", callback_data="schedule_today"),
                    InlineKeyboardButton("На завтра", callback_data="schedule_tomorrow"),
                ],
                [
                    InlineKeyboardButton("Неделя 1", callback_data="schedule_week_1"),
                    InlineKeyboardButton("Неделя 2", callback_data="schedule_week_2"),
                ],
                [
                    InlineKeyboardButton("Изменить группу", callback_data="change_group"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"Выбрана группа: *{group}*\n\n"
                "Выберите период расписания:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
        elif data.startswith("schedule_"):
            # Передаем управление функции schedule_selected
            await schedule_selected(update, context)
            
        elif data.startswith("day_"):
            # Передаем управление функции show_day_schedule
            await show_day_schedule(update, context)
            
        elif data == "back_to_menu":
            user_id = update.effective_user.id
            group = db.get_user_group(user_id)
            
            if not group:
                # Если группа не выбрана, предлагаем выбрать
                keyboard = [
                    [
                        InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                        InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                        InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "Выберите группу:",
                    reply_markup=reply_markup
                )
                return
            
            keyboard = [
                [
                    InlineKeyboardButton("На сегодня", callback_data="schedule_today"),
                    InlineKeyboardButton("На завтра", callback_data="schedule_tomorrow"),
                ],
                [
                    InlineKeyboardButton("Неделя 1", callback_data="schedule_week_1"),
                    InlineKeyboardButton("Неделя 2", callback_data="schedule_week_2"),
                ],
                [
                    InlineKeyboardButton("Изменить группу", callback_data="change_group"),
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"Выбрана группа: *{group}*\n\n"
                "Выберите период расписания:",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
        elif data == "change_group":
            keyboard = [
                [
                    InlineKeyboardButton("ИБ-41", callback_data="group_ИБ-41"),
                    InlineKeyboardButton("ИБ-42", callback_data="group_ИБ-42"),
                    InlineKeyboardButton("ИБ-43", callback_data="group_ИБ-43"),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "Выберите вашу группу:",
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.error(f"Ошибка в обработчике button_handler: {e}")
        try:
            await query.edit_message_text("Произошла ошибка. Пожалуйста, попробуйте еще раз.")
        except:
            pass

async def main() -> None:
    """Запускает бота."""
    # Инициализируем базу данных при запуске
    db.init_db()
    
    # Получаем токен из переменной окружения
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("Токен бота не найден. Проверьте файл .env")
        return
    
    # Настройка параметров запроса с увеличенными тайм-аутами
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=10.0,  # 10 секунд на соединение
        read_timeout=30.0,     # 30 секунд на чтение
        write_timeout=30.0,    # 30 секунд на запись
    )
    

    application = Application.builder().token(token).request(request).build()
    
   
    application.add_error_handler(error_handler)
    
    
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Создаем conversation handler, но не добавляем его в бота
    # Вместо этого переходим на глобальный обработчик кнопок
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_GROUP: [
                # Пустые обработчики, теперь всё обрабатывается в button_handler
            ],
            CHOOSING_SCHEDULE: [
                # Пустые обработчики, теперь всё обрабатывается в button_handler
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=True,
        per_chat=False,
        name="schedule_conversation",
    )
    
    # Добавляем только обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("week1", week1_command))
    application.add_handler(CommandHandler("week2", week2_command))
    
    # Инициализируем бота и запускаем приложение
    await application.initialize()
    await application.start()
    await application.updater.start_polling(poll_interval=0.5, timeout=30, drop_pending_updates=True)
    
    logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    
    # Держим приложение запущенным до сигнала остановки
    try:
        await asyncio.Event().wait()  # Бесконечное ожидание
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка бота...")
    finally:
        # Корректно останавливаем бота
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main()) 
