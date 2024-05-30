import logging

from telebot import TeleBot
from tenacity import retry, wait_exponential

logger = logging.getLogger('__main__')


class TelegramHandler(logging.Handler):
    def __init__(self, bot: TeleBot, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot = bot

    @retry(wait=wait_exponential(max=60))
    def emit(self, record: logging.LogRecord) -> None:
        # TelegramHandler для важных сообщений, поэтому бесконечные ретраи
        # TODO: подумать, мб сделать это место более безопасным
        self.bot.send_message('@abobafrompsu', self.format(record))
