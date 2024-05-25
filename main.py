import telebot
from datetime import datetime
import requests
from collections import defaultdict
import os
import threading
import time
from tenacity import retry, stop_after_attempt, wait_exponential
import json

HOST = 'http://158.160.126.20:8080'
ASK_QUESTION_URL = f'{HOST}/api/ask_question'
CREATE_UNKNOWN_QUESTION_URL = f'{HOST}/api/uk/'
API_USER_TOKEN = os.environ.get('API_USER_TOKEN')
API_USER_AUTH_STRING = f'Token {API_USER_TOKEN}'
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_ID = 450681732
bot = telebot.TeleBot(TELEGRAM_TOKEN)

if not os.path.exists('logs'):
    os.makedirs('logs')

def log_message(chat_id, message):
    with open(f'logs/{message.chat.username}_{chat_id}.txt', 'a') as f:
        f.write(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} : {message.text}\n')

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
    retry_attempts = 10
    for attempt in range(retry_attempts):
        try:
            bot.send_message(chat_id, text, *args, **kwargs)
            break
        except telebot.apihelper.ApiException as e:
            if e.result.status_code == 429:
                sleep_time = e.result.json()['parameters']['retry_after']
                print(f"Too many requests! Sleeping for {sleep_time} seconds")
                time.sleep(sleep_time)
            else:
                print(f"ApiException: {e}")
                time.sleep(2 ** attempt)
        except Exception as e:
            print(f"Exception during sending message: {e}")
            time.sleep(2 ** attempt)

def safe_send_message(chat_id, text, *args, **kwargs):
    try:
        send_message_with_retry(chat_id, text, *args, **kwargs)
    except Exception as e:
        print(f"Failed to send message to {chat_id}: {e}")
    finally:
        if 'feedback_requested' in user_data[chat_id] and user_data[chat_id]['feedback_requested']:
            feedback_scheduled[chat_id].cancel()
            user_data[chat_id]['feedback_requested'] = False

user_data = defaultdict(dict)
feedback_scheduled = defaultdict(lambda: threading.Timer(0, lambda: None))

@bot.message_handler(func=lambda m: True)
def echo_all(message):
    try:
        log_message(message.chat.id, message)
        print("Сообщение пришло в: " + str(datetime.strftime(datetime.now(), "%H:%M:%S")))
        print("Текст сообщения: " + str(message.text))
        print(message.chat.id)

        if user_data[message.chat.id].get('feedback_requested') and message.text.isdigit() and 1 <= int(message.text) <= 5:
            record_feedback(message.chat.id, message.text)
            safe_send_message(message.chat.id, 'Спасибо за вашу оценку! \nВаша оценка была записана.')
            return

        if user_data[message.chat.id].get('button_send'):
            topic = message.text
            data = user_data[message.chat.id]
            topic_id = get_topic_id_from_possible_answers_by_topic(topic, data)
            possible_answer = get_data_from_possible_answers_by_topic_id(topic_id, data)

            if possible_answer is not None:
                safe_send_message(message.chat.id, possible_answer['answer'])
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
                    safe_send_message(ADMIN_ID, f'Ошибка при обращении к серверу: {e}')
            else:
                safe_send_message(message.chat.id, 'Мы рассмотрим ваш вопрос и постараемся добавить ответ на него в нашу базу данных')
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
                    safe_send_message(ADMIN_ID, f'Ошибка при обращении к серверу: {e}')

            user_data[message.chat.id]['button_send'] = False
        else:
            data = get_answer(str(message.text))
            print(type(data))
            print(data)

            if data.get('answer'):
                safe_send_message(message.chat.id, data['answer'])
                user_data[message.chat.id]['button_send'] = False
            else:
                keyboard = telebot.types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
                for item in data["possible_answers"]:
                    button = telebot.types.KeyboardButton(text=item['topic'])
                    keyboard.add(button)
                keyboard.add('Ни один из вариантов не подошел')

                safe_send_message(message.chat.id, "К сожалению, я не понял ваш вопрос, выберите один из вариантов предложенных ниже", reply_markup=keyboard)

                user_data[message.chat.id] = data
                user_data[message.chat.id]['button_send'] = True
                user_data[message.chat.id]['user_question'] = message.text

        schedule_feedback(message.chat.id)

    except requests.RequestException as e:
        send_message_with_retry(ADMIN_ID, f'Ошибка при обращении к серверу: {e}')
        print(f"RequestException: {e}")
    except telebot.apihelper.ApiException as e:
        send_message_with_retry(ADMIN_ID, f'Ошибка при обработке сообщения: {e}')
        print(f"ApiException: {e}")
    except json.JSONDecodeError as e:
        send_message_with_retry(ADMIN_ID, f'Ошибка декодирования JSON: {e}')
        print(f"JSONDecodeError: {e}")
    except ValueError as e:
        send_message_with_retry(ADMIN_ID, f'Ошибка значения: {e}')
        print(f"ValueError: {e}")
    except TypeError as e:
        send_message_with_retry(ADMIN_ID, f'Ошибка типа: {e}')
        print(f"TypeError: {e}")
    except KeyError as e:
        send_message_with_retry(ADMIN_ID, f'Ошибка ключа: {e}')
        print(f"KeyError: {e}")
    except IndexError as e:
        send_message_with_retry(ADMIN_ID, f'Ошибка индекса: {e}')
        print(f"IndexError: {e}")
    except OSError as e:
        send_message_with_retry(ADMIN_ID, f'Ошибка ОС: {e}')
        print(f"OSError: {e}")
    except Exception as e:
        send_message_with_retry(ADMIN_ID, f'Непредвиденная ошибка: {e}')
        print(f"Exception: {e}")

while True:
    try:
        bot.polling(none_stop=True)
    except telebot.apihelper.ApiException as e:
        if e.result.status_code == 429:
            sleep_time = e.result.json()['parameters']['retry_after']
            print(f"Too many requests! Sleeping for {sleep_time} seconds")
            time.sleep(sleep_time)
        else:
            send_message_with_retry(ADMIN_ID, f'Ошибка API Telegram: {e}')
            print(f"ApiException: {e}")
    except Exception as e:
        send_message_with_retry(ADMIN_ID, f'Непредвиденная ошибка: {e}')
        print(f"Exception: {e}")
        time.sleep(15)  # Добавляем задержку перед повторной
