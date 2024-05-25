import logging
from typing import Callable


class TelegramHandler(logging.Handler):
    def __init__(self, send_msg_func: Callable, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.send_msg_func = send_msg_func

    def emit(self, record: logging.LogRecord) -> None:
        self.send_msg_func(self.format(record))
