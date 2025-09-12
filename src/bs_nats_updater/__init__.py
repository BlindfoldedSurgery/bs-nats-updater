import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Self, overload

from bs_config import Env
from nats.aio.client import Client
from nats.js import JetStreamContext
from nats.js.errors import ServiceUnavailableError
from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.ext import Updater

_logger = logging.getLogger(__package__)


@dataclass
class NatsConfig:
    url: str
    consumer_name: str
    receiver_secret: str
    receiver_url: str
    stream_name: str

    @overload
    @classmethod
    def from_env(cls, env: Env, *, is_optional: Literal[False] = False) -> Self:
        pass

    @overload
    @classmethod
    def from_env(cls, env: Env, *, is_optional: Literal[True]) -> Self | None:
        pass

    @classmethod
    def from_env(cls, env: Env, *, is_optional: bool = False) -> Self | None:
        try:
            return cls(
                url=env.get_string("SERVER_URL", required=True),
                consumer_name=env.get_string("CONSUMER_NAME", required=True),
                receiver_secret=env.get_string("RECEIVER_SECRET", required=True),
                receiver_url=env.get_string("RECEIVER_URL", required=True),
                stream_name=env.get_string("STREAM_NAME", required=True),
            )
        except ValueError as e:
            if is_optional:
                return None

            raise e


class NatsUpdater(contextlib.AbstractAsyncContextManager["NatsUpdater"]):
    def __init__(self, *, bot: Bot, nats_config: NatsConfig) -> None:
        self.update_queue: asyncio.Queue[object] = asyncio.Queue()
        self.bot = bot
        self.nats_config = nats_config

        self.__lock = asyncio.Lock()
        self._is_running = False
        self._is_initialized = False

        self.__nats_client_closed = asyncio.Event()
        self.__nats_client = Client()

    @property
    def running(self) -> bool:
        return self._is_running

    async def initialize(self) -> None:
        if self._is_initialized:
            _logger.debug("Already initialized")
            return

        _logger.debug("Connecting to NATS server")
        await self.__nats_client.connect(
            self.nats_config.url,
            allow_reconnect=True,
            closed_cb=self.__on_nats_client_closed,
        )

        _logger.debug("Initializing bot")
        await self.bot.initialize()

        self._is_initialized = True

    async def __on_nats_client_closed(self) -> None:
        self.__nats_client_closed.set()

    async def shutdown(self) -> None:
        if self.running:
            raise RuntimeError("This Updater is still running!")

        if not self._is_initialized:
            _logger.debug("This Updater is already shut down. Returning.")
            return

        if self.__nats_client_closed.is_set():
            _logger.warning("NATS client is already closed. Returning.")
            return

        _logger.info("Draining NATS client")
        await self.__nats_client.drain()
        await self.__nats_client_closed.wait()

        _logger.info("Closing NATS client")
        await self.__nats_client.close()

        _logger.debug("Shutting down bot")
        await self.bot.shutdown()
        self._is_initialized = False
        _logger.debug("Shut down of Updater complete")

    async def __aenter__(self) -> Self:
        try:
            await self.initialize()
        except Exception:
            await self.shutdown()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.shutdown()

    async def _ensure_webhook(
        self,
        allowed_updates: Sequence[str] | None = None,
    ) -> None:
        bot = self.bot
        receiver_url = self.nats_config.receiver_url
        receiver_secret = self.nats_config.receiver_secret

        _logger.debug("Setting webhook for bot")
        await bot.set_webhook(
            url=receiver_url,
            secret_token=receiver_secret,
            allowed_updates=allowed_updates,
        )

    async def start_polling(
        self,
        poll_interval: float = 0.0,
        timeout: int = 10,
        bootstrap_retries: int = 0,
        allowed_updates: Sequence[str] | None = None,
        drop_pending_updates: bool | None = None,
        error_callback: Callable[[TelegramError], None] | None = None,
    ) -> asyncio.Queue[object]:
        async with self.__lock:
            if self.running:
                raise RuntimeError("This Updater is already running!")
            if not self._is_initialized:
                raise RuntimeError(
                    "This Updater was not initialized via `Updater.initialize`!"
                )

            self._is_running = True

            try:
                asyncio.create_task(
                    self._start_polling(
                        allowed_updates=allowed_updates,
                    ),
                    name="NatsUpdater.poll",
                )
            except Exception:
                self._is_running = False
                raise
            return self.update_queue

    def _deserialize_update(self, raw_data: bytes) -> Update:
        bot = self.bot
        json_data = json.loads(raw_data)
        return Update.de_json(json_data, bot)

    async def _start_polling(
        self,
        allowed_updates: Sequence[str] | None = None,
    ) -> None:
        client = self.__nats_client
        jetstream = client.jetstream()
        sub: JetStreamContext.PullSubscription = await jetstream.pull_subscribe_bind(
            consumer=self.nats_config.consumer_name,
            stream=self.nats_config.stream_name,
        )

        update_queue = self.update_queue

        _logger.debug("Setting up webhook config")
        await self._ensure_webhook(allowed_updates)

        while self.running and not (client.is_draining or client.is_closed):
            try:
                messages = await sub.fetch()
            except TimeoutError:
                continue
            except ServiceUnavailableError as e:
                _logger.warning(
                    "NATS service unavailable. Retrying after a short wait...",
                    exc_info=e,
                )
                await asyncio.sleep(2)
                continue
            except Exception:
                _logger.exception("Unknown error while fetching messages")
                continue

            if not self.running:
                _logger.warning(
                    "NatsUpdater has stopped running. Retrying messages that were just fetched.",
                )
                # Intentionally doing this sequentially
                for message in messages:
                    await message.nak()

                continue

            for message in messages:
                update = self._deserialize_update(message.data)
                await update_queue.put(update)
                await message.ack()

    async def stop(self) -> None:
        async with self.__lock:
            if not self.running:
                raise RuntimeError("This Updater is not running!")

            _logger.debug("Stopping Updater")

            self._is_running = False

            await self.__nats_client.drain()

            _logger.debug("Updater.stop() is complete")


def create_updater(
    bot_or_token: Bot | str,
    /,
    config: NatsConfig,
) -> Updater:
    if isinstance(bot_or_token, str):
        bot = Bot(token=bot_or_token)
    else:
        bot = bot_or_token

    updater = NatsUpdater(
        bot=bot,
        nats_config=config,
    )
    return updater  # type: ignore[return-value]
