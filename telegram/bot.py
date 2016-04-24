import asyncio
import telepot
import telepot.async
from brain.models import Client
from brain import parser
from django.core.exceptions import ObjectDoesNotExist
from telepot.namedtuple import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardHide, ForceReply
from telepot.namedtuple import InlineKeyboardMarkup, InlineKeyboardButton
from telepot.namedtuple import InlineQueryResultArticle, InlineQueryResultPhoto, InputTextMessageContent


async def in_thread(func, *args):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, func, *args)
    return result


class ClientId(telepot.async.Bot):
    def _get_client(self, telegram_id):
        try:
            client = Client.objects.get(telegram_id=telegram_id)
        except ObjectDoesNotExist:
            client = None
        return client

    def _create_client(self, telegram_id, first_name, last_name):
        client = Client.objects.create(
            telegram_id=telegram_id, first_name=first_name,
            last_name=last_name, data={}
        )
        return client

    async def _get_or_create_client(self, msg):
        user_id = msg['from']['id']
        client = await in_thread(self._get_client, user_id)
        if not client:
            client = await in_thread(
                self._create_client, user_id,
                msg['from'].get('first_name', str(user_id)),
                msg['from'].get('last_name', '')
            )
        return client

    async def on_chat_message(self, msg):
        client = await self._get_or_create_client(msg)
        await self.on_client_message(msg['text'], msg, client)

    async def on_callback_query(self, msg):
        client = await self._get_or_create_client(msg)
        await self.on_client_message(msg['data'], msg, client)

    async def on_client_message(self, text, msg, client):
        raise NotImplementedError


class Page(object):
    def __init__(self, bot):
        self.bot = bot

    async def display(self, reply, data, msg):
        keyboard = []
        next_page = data and data.get('next_page') or None
        previous_page = data and data.get('prev_page') or None

        if previous_page:
            keyboard.append(
                InlineKeyboardButton(
                    text='previous page {}'.format(previous_page),
                    callback_data='previous'
                )
            )
        if next_page:
            keyboard.append(
                InlineKeyboardButton(
                    text='next page {}'.format(next_page),
                    callback_data='next'
                )
            )

        markup = keyboard and InlineKeyboardMarkup(inline_keyboard=[keyboard]) or None
        if telepot.flavor(msg) == 'callback_query':
            c, m = msg['message']['chat']['id'], msg['message']['message_id']
            await self.bot.editMessageText(
                (c, m), reply, reply_markup=markup
            )
            return data

        content_type, chat_type, chat_id = telepot.glance(msg)
        last_id = data.get('last_query_id')
        last_markup = data.get('last_query_markup')
        if last_id and last_markup:
            await self.bot.editMessageReplyMarkup(
                (last_id[0], last_id[1]), reply_markup=None
            )
        response = await self.bot.sendMessage(chat_id, reply, reply_markup=markup)
        data['last_query_id'] = [chat_id, response['message_id']]
        data['last_query_markup'] = markup and True or False
        return data


class Bot(ClientId):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.page = Page(self)

    async def on_client_message(self, text, msg, client):
        reply, data = parser.search_intent(text, client.data)
        data = await self.page.display(reply, data, msg)
        client.data.update(data)
        await in_thread(client.save)
