import re
import json
import redis

import settings


KARMA_INCR = 1
KARMA_DECR = 2
KARMA_STAT = 3

KARMA_STAT_REGEXP = re.compile(r'^/karma ([\w_\-]+)$')
KARMA_INCR_REGEXP = re.compile(r'^([\w_\-]+)\+\+$')
KARMA_DECR_REGEXP = re.compile(r'^([\w_\-]+)\-\-$')


class Message:

    def __init__(self, username, text, display_name):
        self.username = username.lower()
        self.text = text
        self.display_name = display_name

    @classmethod
    def from_string(cls, raw_message):
        """
        Returns instance of Message or raises ValueError
        If message have incorrect format.
        """
        data = json.loads(raw_message)
        if set(data.keys()) != {'username', 'text', 'display_name'}:
            raise ValueError('Invalid message format given')
        return cls(
            username=str(data['username']),
            text=str(data['text']),
            display_name=str(data['display_name'])
        )


class KarmaCmd:

    def __init__(self, type_, username):
        self.type = type_
        self.username = username.lower()

    @classmethod
    def from_message(cls, message: Message):
        """
        Get karma command or None if message isn't karma cmd
        """
        cmd = None
        if message.text == '/karma':
            cmd = cls(KARMA_STAT, message.username)
        elif message.text.startswith('/karma '):
            match = KARMA_STAT_REGEXP.search(message.text)
            if match:
                cmd = cls(KARMA_STAT, match.group(1))
        elif message.text.endswith('++'):
            match = KARMA_INCR_REGEXP.search(message.text)
            if match:
                cmd = cls(KARMA_INCR, match.group(1))
        elif message.text.endswith('--'):
            match = KARMA_DECR_REGEXP.search(message.text)
            if match:
                cmd = cls(KARMA_DECR, match.group(1))
        return cmd


class KarmaApp:

    KARMA_CHANGE_TIME_LIMIT = 60 * 60 * 12

    def __init__(self, initial_data=None):
        self.redis = redis.StrictRedis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
        )
        self.cmd_processors = {
            KARMA_INCR: self._process_incr,
            KARMA_DECR: self._process_decr,
            KARMA_STAT: self._process_stat,
        }
        if initial_data is not None:
            for username, value in initial_data.items():
                self.redis.hset('karma', username, value)

    def incr(self, username):
        return int(self.redis.hincrby('karma', username, 1))

    def decr(self, username):
        return int(self.redis.hincrby('karma', username, -1))

    def get(self, username):
        value = self.redis.hget('karma', username)
        if value is None:
            return 0
        return int(value)

    def process_request(self, request):
        try:
            message = Message.from_string(request)
        except ValueError:
            return
        cmd = KarmaCmd.from_message(message)
        if cmd is None:
            return
        return self.cmd_processors[cmd.type](cmd, by_username=message.username)

    def _process_incr(self, cmd, by_username):
        if cmd.username == by_username:
            return 'Вы не можете изменять свою карму!'
        change_flag_key = 'karma_change/{by}/{to}/'.format(
            by=by_username, to=cmd.username
        )
        if self.redis.exists(change_flag_key):
            return 'Вы можете менять карму пользователю не чаще раза в сутки.'
        user_karma = self.incr(cmd.username)
        self.redis.set(change_flag_key, 1)
        self.redis.expire(change_flag_key, self.KARMA_CHANGE_TIME_LIMIT)

        return 'Карма пользователя {} увеличена (текущее значение: {}).'\
            .format(cmd.username, user_karma)

    def _process_decr(self, cmd, by_username):
        if cmd.username == by_username:
            return 'Вы не можете изменять свою карму!'
        change_flag_key = 'karma_change/{by}/{to}/'.format(
            by=by_username, to=cmd.username
        )
        if self.redis.exists(change_flag_key):
            return 'Вы можете менять карму пользователю не чаще раза в сутки.'
        user_karma = self.decr(cmd.username)
        self.redis.set(change_flag_key, 1)
        self.redis.expire(change_flag_key, self.KARMA_CHANGE_TIME_LIMIT)
        return 'Карма пользователя {} уменьшена (текущее значение: {}).'\
            .format(cmd.username, user_karma)

    def _process_stat(self, cmd, by_username):
        user_karma = self.get(cmd.username)
        if cmd.username == by_username:
            return 'Ваша карма = {}.'.format(user_karma)
        return 'Карма пользователя {} = {}.'.format(
            cmd.username, user_karma
        )
