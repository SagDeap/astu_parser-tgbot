import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Union, Optional
import logging
import time

# Настройка логирования
logger = logging.getLogger(__name__)

# Тут ссылки на группы которые хотим получать расписание
GROUP_URLS = {
    "ИБ-41": "https://www.altstu.ru/m/s/7000020491/",
    "ИБ-42": "https://www.altstu.ru/m/s/7000020492/",
    "ИБ-43": "https://www.altstu.ru/m/s/7000020493/"
}

# Кеш для хранения расписаний, чтобы не парсить на каждый запрос
schedule_cache = {}
cache_timeout = 3600  # 1 час в секундах

# Словарь сокращений названий предметов, чтобы на мобилке красиво все было. Меняйте не свои предметы и аббревиатуры
SUBJECT_ABBREVIATIONS = {
    "Дискретная математика и теория чисел": "Дискретка",
    "Аппаратные средства вычислительной техники": "Аппаратка",
    "Информационные процессы и системы": "ИПИС",
    "Иностранный язык": "Ин. яз",
    "Математический анализ": "Матан",
    "Физическая культура и спорт": "Физра",
    "История России": "История",
    "Документоведение": "Док-ведение"
}

def get_short_subject_name(name: str) -> str:
    """Возвращает сокращенное название предмета, если оно есть в словаре сокращений"""
    return SUBJECT_ABBREVIATIONS.get(name, name)

class Subject:
    def __init__(self, time: str, name: str, type_: str, room: str, teacher: str, position: str, is_exam: bool = False, is_once: bool = False):
        self.time = time
        self.name = name
        self.type = type_
        self.room = room
        self.teacher = teacher
        self.position = position
        self.is_exam = is_exam
        self.is_once = is_once
    
    def __str__(self) -> str:
        # Используем сокращенное название предмета
        short_name = get_short_subject_name(self.name)
        
        type_str = f"{self.type}" if self.type else ""
        room_str = f"- {self.room}" if self.room else ""
        # Убираем отображение преподавателя
        
        # Компактное отображение предмета
        result = f"*{self.time}* - *{short_name}* {type_str} {room_str}"
        
        # Заменяем "подгруппа X" на просто букву подгруппы
        result = result.replace("подгруппа А", "А")
        result = result.replace("подгруппа Б", "Б")
        result = result.replace("подгруппа В", "В")
        result = result.replace("подгруппа Г", "Г")
        
        # Убираем лишние пробелы
        result = re.sub(r'\s+', ' ', result).strip()
        # Заменяем двойные тире на одинарные
        result = result.replace('- -', '-')
        
        if self.is_exam:
            result = f"📝 {result}" # Экзамен / зачет
        elif self.is_once:
            result = f"⚠️ {result}" # Разовое занятие
            
        return result

class Day:
    def __init__(self, date: str, weekday: str):
        self.date = date
        self.weekday = weekday
        self.subjects: List[Subject] = []
    
    def add_subject(self, subject: Subject) -> None:
        self.subjects.append(subject)
    
    def __str__(self) -> str:
        if not self.subjects:
            return f"*{self.date} {self.weekday}*\nЗанятий нет"
        
        result = f"*{self.date} {self.weekday}*\n"
        for subject in self.subjects:
            result += f"{subject}\n"
        return result

class Week:
    def __init__(self, number: int):
        self.number = number
        self.days: List[Day] = []
    
    def add_day(self, day: Day) -> None:
        self.days.append(day)
    
    def __str__(self) -> str:
        result = f"*Неделя {self.number}*\n\n"
        for day in self.days:
            result += f"{day}\n"
        return result

class Schedule:
    def __init__(self, group: str):
        self.group = group
        self.weeks: List[Week] = []
        # Добавляем время создания расписания
        self.created_at = time.time()
    
    def add_week(self, week: Week) -> None:
        self.weeks.append(week)
    
    def __str__(self) -> str:
        result = f"*Расписание группы {self.group}*\n\n"
        for week in self.weeks:
            result += f"{week}\n"
        return result

def parse_schedule(group: str) -> Optional[Schedule]:
    """
    Парсит расписание для указанной группы.
    Использует кеширование для уменьшения количества запросов к серверу.
    """
    global schedule_cache
    
    if group not in GROUP_URLS:
        logger.error(f"Группа {group} не найдена в списке URL")
        return None
    
    # Проверяем кеш
    if group in schedule_cache:
        cached_schedule = schedule_cache[group]
        # Проверяем время создания расписания
        if hasattr(cached_schedule, 'created_at') and time.time() - cached_schedule.created_at < cache_timeout:
            logger.info(f"Используем кешированное расписание для группы {group}")
            return cached_schedule
    
    url = GROUP_URLS[group]
    
    # Количество попыток запроса
    max_retries = 3
    retry_delay = 2  # секунды
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Получение расписания для группы {group}, попытка {attempt+1}")
            
            # Настройка сессии с параметрами тайм-аута
            session = requests.Session()
            response = session.get(
                url, 
                timeout=(10, 30),  # (connect timeout, read timeout)
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            )
            response.raise_for_status()
            
            # Сохраним ответ сервера в отладочный файл для анализа
            with open(f"debug_{group}.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            schedule = Schedule(group)
            
            # Находим все заголовки недель
            week_headers = soup.find_all('h4', string=re.compile(r'Неделя\s+\d+'))
            
            if not week_headers:
                logger.warning(f"Не найдены заголовки недель для группы {group}")
                return None
                
            logger.info(f"Найдено {len(week_headers)} недель")
            
            # Разбиваем все блоки дней на разные недели
            weeks_content = []
            for i in range(len(week_headers)):
                current_header = week_headers[i]
                # Определяем, где заканчивается контент текущей недели
                next_header = None
                if i < len(week_headers) - 1:
                    next_header = week_headers[i + 1]
                
                # Извлекаем номер недели
                week_match = re.search(r'Неделя\s+(\d+)', current_header.text)
                if not week_match:
                    logger.warning(f"Не удалось извлечь номер недели из '{current_header.text}'")
                    continue
                
                week_number = int(week_match.group(1))
                
                # Находим все блоки дней для этой недели
                day_blocks = []
                current_elem = current_header.next_sibling
                
                while current_elem:
                    # Если достигли следующего заголовка недели, останавливаемся
                    if next_header and current_elem == next_header:
                        break
                    
                    # Если это блок дня, добавляем его
                    if hasattr(current_elem, 'name') and current_elem.name == 'div' and 'block-index' in current_elem.get('class', []):
                        day_blocks.append(current_elem)
                    
                    # Переходим к следующему элементу
                    if hasattr(current_elem, 'next_sibling'):
                        current_elem = current_elem.next_sibling
                    else:
                        break
                
                weeks_content.append({
                    'week_number': week_number,
                    'day_blocks': day_blocks
                })
            
            # Обрабатываем каждую неделю отдельно
            for week_data in weeks_content:
                week_number = week_data['week_number']
                day_blocks = week_data['day_blocks']
                
                logger.info(f"Обработка недели {week_number}, найдено {len(day_blocks)} дней")
                
                # Создаем объект недели
                week = Week(week_number)
                
                # Обрабатываем каждый день
                for day_block in day_blocks:
                    # Находим заголовок дня
                    day_header = day_block.find('h2')
                    if not day_header:
                        logger.warning(f"Не найден заголовок дня в блоке")
                        continue
                    
                    day_info = day_header.text.strip().split()
                    if len(day_info) < 2:
                        logger.warning(f"Неверный формат заголовка дня: '{day_header.text}'")
                        continue
                    
                    date = day_info[0]
                    weekday = day_info[1]
                    
                    logger.info(f"Обработка дня {date} {weekday}")
                    
                    day = Day(date, weekday)
                    
                    # Получаем список предметов для текущего дня
                    subjects_block = day_block.find('div', class_='list-group')
                    if not subjects_block:
                        logger.warning(f"Не найден блок предметов для дня {date}")
                        week.add_day(day)
                        continue
                    
                    subject_items = subjects_block.find_all('div', class_='list-group-item')
                    
                    logger.info(f"Найдено {len(subject_items)} предметов для дня {date}")
                    
                    for subject_item in subject_items:
                        # Проверяем является ли это разовым занятием или экзаменом
                        is_once = 'once' in subject_item.get('class', [])
                        is_exam = 'once-exam' in subject_item.get('class', [])
                        
                        # Очищаем текст от лишних пробелов и переносов
                        subject_text = re.sub(r'\s+', ' ', subject_item.get_text(strip=True).replace('\n', ' '))
                        
                        # Извлекаем данные с помощью регулярных выражений
                        time_val = ""
                        name = ""
                        type_ = ""
                        room = ""
                        teacher = ""
                        position = ""
                        
                        # Парсим время (обычно в формате XX:XX-XX:XX)
                        time_match = re.match(r'(\d{2}:\d{2}-\d{2}:\d{2})', subject_text)
                        if time_match:
                            time_val = time_match.group(1)
                            subject_text = subject_text[len(time_val):].strip()
                        
                        # Парсим название предмета
                        name_elem = subject_item.find('strong')
                        if name_elem:
                            name = name_elem.text.strip()
                            # Удаляем название из оставшегося текста
                            subject_text = subject_text.replace(name, '', 1).strip()
                        
                        # Парсим тип занятия (в скобках)
                        type_match = re.search(r'\(([^)]+)\)', subject_text)
                        if type_match:
                            type_ = type_match.group(0)  # Включая скобки
                            subject_text = subject_text.replace(type_, '', 1).strip()
                        
                        # Парсим аудиторию
                        room_match = re.search(r'\d+\s*[А-Я]+', subject_text)
                        if room_match:
                            room = room_match.group(0)
                            subject_text = subject_text.replace(room, '', 1).strip()
                        
                        # Парсим преподавателя
                        teacher_match = re.search(r'[А-Яа-я]+\s+[А-Я]\.\s*[А-Я]\.', subject_text)
                        if teacher_match:
                            teacher = teacher_match.group(0).strip()
                            subject_text = subject_text.replace(teacher, '', 1).strip()
                        
                        # Оставшийся текст считаем должностью
                        position = subject_text.strip('-').strip()
                        
                        # Создаем объект Subject
                        subject = Subject(
                            time=time_val,
                            name=name,
                            type_=type_,
                            room=room,
                            teacher=teacher,
                            position=position,
                            is_exam=is_exam,
                            is_once=is_once
                        )
                        
                        logger.info(f"Добавлен предмет: {subject}")
                        day.add_subject(subject)
                    
                    week.add_day(day)
                
                # Добавляем неделю в расписание
                schedule.add_week(week)
            
            # Сохраняем в кеш
            schedule_cache[group] = schedule
            
            return schedule
        
        except requests.Timeout as e:
            logger.error(f"Тайм-аут при запросе расписания для группы {group}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Повторная попытка через {retry_delay} сек...")
                # Используем time.sleep() вместо sleep
                time.sleep(retry_delay)
                retry_delay *= 2  # Увеличиваем задержку для следующей попытки
            else:
                logger.error(f"Превышено количество попыток запроса расписания для группы {group}")
                # Проверяем, есть ли устаревшие данные в кеше
                if group in schedule_cache:
                    logger.info(f"Используем устаревшие данные из кеша для группы {group}")
                    return schedule_cache[group]
                return None
                
        except requests.RequestException as e:
            logger.error(f"Ошибка при запросе расписания для группы {group}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Повторная попытка через {retry_delay} сек...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.error(f"Превышено количество попыток запроса расписания для группы {group}")
                # Проверяем, есть ли устаревшие данные в кеше
                if group in schedule_cache:
                    logger.info(f"Используем устаревшие данные из кеша для группы {group}")
                    return schedule_cache[group]
                return None
                
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при парсинге расписания для группы {group}: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Повторная попытка через {retry_delay} сек...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.error(f"Превышено количество попыток запроса расписания для группы {group}")
                # Проверяем, есть ли устаревшие данные в кеше
                if group in schedule_cache:
                    logger.info(f"Используем устаревшие данные из кеша для группы {group}")
                    return schedule_cache[group]
                return None
    
    return None

def get_today_schedule(group: str) -> str:
    try:
        schedule = parse_schedule(group)
        if not schedule:
            return f"Не удалось получить расписание для группы {group}"
        
        today = datetime.now()
        today_date = today.strftime("%d.%m.%y")
        
        logger.info(f"Поиск расписания на сегодня ({today_date}) для группы {group}")
        
        for week in schedule.weeks:
            for day in week.days:
                day_date = day.date
                logger.info(f"Проверка дня {day_date}")
                
                try:
                    # Иногда формат даты может быть другим, поэтому пробуем несколько вариантов
                    day_date_obj = None
                    
                    date_formats = ["%d.%m.%y", "%d.%m.%Y"]
                    for fmt in date_formats:
                        try:
                            day_date_obj = datetime.strptime(day_date, fmt)
                            break
                        except ValueError:
                            continue
                    
                    if not day_date_obj:
                        logger.warning(f"Не удалось распознать формат даты: {day_date}")
                        continue
                    
                    logger.info(f"Сравнение дат: {day_date_obj.date()} и {today.date()}")
                    
                    if day_date_obj.date() == today.date():
                        logger.info(f"Найдено расписание на сегодня для группы {group}")
                        
                        if not day.subjects:
                            return f"*Расписание группы {group} на сегодня*\n\n----- *{day.date} {day.weekday}* -----\n\nЗанятий нет"
                        
                        result = f"*Расписание группы {group} на сегодня*\n\n----- *{day.date} {day.weekday}* -----\n\n"
                        for subject in day.subjects:
                            result += f"{subject}\n"
                        
                        return result
                except Exception as e:
                    logger.error(f"Ошибка при обработке даты {day_date}: {e}")
                    continue
        
        logger.warning(f"Расписание на сегодня для группы {group} не найдено")
        return f"Расписание на сегодня для группы {group} не найдено"
    except Exception as e:
        logger.error(f"Ошибка при получении расписания на сегодня для группы {group}: {e}")
        return f"Произошла ошибка при получении расписания. Пожалуйста, попробуйте позже."

def get_tomorrow_schedule(group: str) -> str:
    try:
        schedule = parse_schedule(group)
        if not schedule:
            return f"Не удалось получить расписание для группы {group}"
        
        today = datetime.now()
        tomorrow = today + timedelta(days=1)
        tomorrow_date = tomorrow.strftime("%d.%m.%y")
        
        logger.info(f"Поиск расписания на завтра ({tomorrow_date}) для группы {group}")
        
        for week in schedule.weeks:
            for day in week.days:
                day_date = day.date
                logger.info(f"Проверка дня {day_date}")
                
                try:
                    # Иногда формат даты может быть другим, поэтому пробуем несколько вариантов
                    day_date_obj = None
                    
                    date_formats = ["%d.%m.%y", "%d.%m.%Y"]
                    for fmt in date_formats:
                        try:
                            day_date_obj = datetime.strptime(day_date, fmt)
                            break
                        except ValueError:
                            continue
                    
                    if not day_date_obj:
                        logger.warning(f"Не удалось распознать формат даты: {day_date}")
                        continue
                    
                    logger.info(f"Сравнение дат: {day_date_obj.date()} и {tomorrow.date()}")
                    
                    if day_date_obj.date() == tomorrow.date():
                        logger.info(f"Найдено расписание на завтра для группы {group}")
                        
                        if not day.subjects:
                            return f"*Расписание группы {group} на завтра*\n\n----- *{day.date} {day.weekday}* -----\n\nЗанятий нет"
                        
                        result = f"*Расписание группы {group} на завтра*\n\n----- *{day.date} {day.weekday}* -----\n\n"
                        for subject in day.subjects:
                            result += f"{subject}\n"
                        
                        return result
                except Exception as e:
                    logger.error(f"Ошибка при обработке даты {day_date}: {e}")
                    continue
        
        logger.warning(f"Расписание на завтра для группы {group} не найдено")
        return f"Расписание на завтра для группы {group} не найдено"
    except Exception as e:
        logger.error(f"Ошибка при получении расписания на завтра для группы {group}: {e}")
        return f"Произошла ошибка при получении расписания. Пожалуйста, попробуйте позже."

def get_week_schedule(group: str, week_number: int = None) -> str:
    try:
        schedule = parse_schedule(group)
        if not schedule:
            return f"Не удалось получить расписание для группы {group}"
        
        if week_number is None:
            # Определяем текущую неделю (для простоты - неделя 1)
            week_number = 1
        
        logger.info(f"Поиск расписания на неделю {week_number} для группы {group}")
        
        for week in schedule.weeks:
            if week.number == week_number:
                logger.info(f"Найдена неделя {week_number}, дней: {len(week.days)}")
                
                if not week.days:
                    return f"*Расписание группы {group} на неделю {week_number}*\n\nНет данных о занятиях"
                
                # Сортируем дни по дате
                sorted_days = sorted(week.days, key=lambda d: datetime.strptime(d.date, "%d.%m.%y") if "." in d.date else datetime.now())
                
                # Берем только первые дни, чтобы сообщение не было слишком длинным
                days_to_show = sorted_days[:3]
                
                # Формируем текст расписания
                result = f"*Расписание группы {group} на неделю {week_number}*\n\n"
                
                for day in days_to_show:
                    # Добавляем сокращенный разделитель для каждого дня
                    result += f"----- *{day.date} {day.weekday}* -----\n"
                    if day.subjects:
                        for subject in day.subjects:
                            result += f"{subject}\n"
                    else:
                        result += "Занятий нет\n"
                    result += "\n"
                    
                return result
        
        logger.warning(f"Расписание на неделю {week_number} для группы {group} не найдено")
        return f"Расписание на неделю {week_number} для группы {group} не найдено"
    except Exception as e:
        logger.error(f"Ошибка при получении расписания на неделю {week_number} для группы {group}: {e}")
        return f"Произошла ошибка при получении расписания. Пожалуйста, попробуйте позже." 
