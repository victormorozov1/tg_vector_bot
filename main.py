import logging
import os
import requests
import telebot
import threading
import time
from collections import defaultdict
from functools import partial
from telegram_handler import TelegramHandler
from tenacity import retry, stop_after_attempt, wait_exponential

from constants import *

if not os.path.exists('logs'):
    os.makedirs('logs')

bot = telebot.TeleBot(TELEGRAM_TOKEN)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(f'logs/{__name__}.log')
stream_handler = logging.StreamHandler()
telegram_handler = TelegramHandler(partial(bot.send_message, '@abobafrompsu'))

file_handler.setLevel(logging.INFO)
stream_handler.setLevel(logging.INFO)
telegram_handler.setLevel(logging.WARNING)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)
logger.addHandler(telegram_handler)


@retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_answer(question: str) -> dict:
    response = requests.get(ASK_QUESTION_URL, json={'question': question})
    response.raise_for_status()
    return response.json()


def get_topic_id_from_possible_answers_by_topic(topic: str, data: dict):
    for i in data['possible_answers']:
        if i['topic'] == topic:
            return i['topic_id']
    return None


def get_data_from_possible_answers_by_topic_id(topic_id: int, data: dict):
    for i in data['possible_answers']:
        if i['topic_id'] == topic_id:
            return i
    return None


def ask_for_feedback(chat_id):
    if feedback_scheduled[chat_id]:
        keyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=5, one_time_keyboard=True)
        for i in range(1, 6):
            keyboard.add(str(i))
        send_message_with_retry(chat_id, "Оцените пожалуйста нашу работу:", reply_markup=keyboard)
        user_data[chat_id]['feedback_requested'] = True


def schedule_feedback(chat_id):
    if feedback_scheduled[chat_id]:
        feedback_scheduled[chat_id].cancel()
    feedback_scheduled[chat_id] = threading.Timer(1 * 30, ask_for_feedback, args=(chat_id,))
    feedback_scheduled[chat_id].start()


def record_feedback(chat_id, rating):
    with open('feedback.txt', 'a') as f:
        f.write(f'{chat_id}: {rating}\n')


def send_message_with_retry(chat_id, text, *args, **kwargs):
    retry_attempts = 50
    for attempt in range(retry_attempts):
        try:
            bot.send_message(chat_id, text, *args, **kwargs)
            break
        except telebot.apihelper.ApiException as e:
            if e.result.status_code == 429:
                sleep_time = e.result.json()['parameters']['retry_after']
                logger.warning('Too many requests! Sleeping for %d seconds', sleep_time)
                time.sleep(sleep_time)
            else:
                sleep_seconds = 2 ** attempt
                logger.error('%s, sleep for %d seconds', repr(e), sleep_seconds)
                time.sleep(sleep_seconds)
        except Exception as e:
            sleep_seconds = 2 ** attempt
            logger.critical(
                'Unexpected error during sending message %s, sleep for %d seconds', repr(e), sleep_seconds,
            )
            time.sleep(sleep_seconds)


user_data = defaultdict(dict)
feedback_scheduled = defaultdict(lambda: threading.Timer(0, lambda: None))


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    logger.info(
        'Receive message: chat_id=%d, user=%s, text="%s"',
        message.chat.id,
        message.chat.username,
        message.text,
    )

    if user_data[message.chat.id].get('feedback_requested') and message.text.isdigit() and 1 <= int(
            message.text) <= 5:
        record_feedback(message.chat.id, message.text)
        send_message_with_retry(message.chat.id, 'Спасибо за вашу оценку! \nВаша оценка была записана.')
        return

    if user_data[message.chat.id].get('button_send'):
        topic = message.text
        data = user_data[message.chat.id]
        topic_id = get_topic_id_from_possible_answers_by_topic(topic, data)
        possible_answer = get_data_from_possible_answers_by_topic_id(topic_id, data)

        if possible_answer is not None:
            send_message_with_retry(message.chat.id, possible_answer['answer'])
            try:
                response = requests.post(
                    CREATE_UNKNOWN_QUESTION_URL,
                    json={
                        'question': data['user_question'],
                        'select_topic': topic_id,
                    },
                    headers={'Authorization': API_USER_AUTH_STRING},
                )
                response.raise_for_status()
            except requests.RequestException as e:
                send_message_with_retry(ADMIN_ID, f'Ошибка при обращении к серверу: {e}')
        else:
            send_message_with_retry(message.chat.id,
                              'Мы рассмотрим ваш вопрос и постараемся добавить ответ на него в нашу базу данных')
            try:
                response = requests.post(
                    CREATE_UNKNOWN_QUESTION_URL,
                    json={
                        'question': data['user_question'],
                        'select_topic': None,
                    },
                    headers={'Authorization': API_USER_AUTH_STRING},
                )
                response.raise_for_status()
            except requests.RequestException as e:
                send_message_with_retry(ADMIN_ID, f'Ошибка при обращении к серверу: {e}')

        user_data[message.chat.id]['button_send'] = False
    else:
        data = get_answer(str(message.text))

        if data.get('answer'):
            send_message_with_retry(message.chat.id, data['answer'])
            user_data[message.chat.id]['button_send'] = False
        else:
            keyboard = telebot.types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
            for item in data["possible_answers"]:
                button = telebot.types.KeyboardButton(text=item['topic'])
                keyboard.add(button)
            keyboard.add('Ни один из вариантов не подошел')

            send_message_with_retry(
                message.chat.id,
                "К сожалению, я не понял ваш вопрос, выберите один из вариантов предложенных ниже",
                reply_markup=keyboard,
            )

            user_data[message.chat.id] = data
            user_data[message.chat.id]['button_send'] = True
            user_data[message.chat.id]['user_question'] = message.text

    schedule_feedback(message.chat.id)


if __name__ == '__main__':
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.critical('Bot stopped due to %s', repr(e))
        raise
