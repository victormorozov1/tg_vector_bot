import os

HOST = 'http://158.160.126.20:8080'
ASK_QUESTION_URL = f'{HOST}/api/ask_question'
CREATE_UNKNOWN_QUESTION_URL = f'{HOST}/api/uk/'
API_USER_TOKEN = os.environ.get('API_USER_TOKEN')
API_USER_AUTH_STRING = f'Token {API_USER_TOKEN}'
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_ID = 450681732
