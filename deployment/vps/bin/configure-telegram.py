#!/usr/bin/env python3
"""Enter a BotFather token on the VPS without displaying or logging it."""
import getpass
import json
import os
from pathlib import Path
import re
import urllib.request

base = Path('/opt/tg-flow')
target = base / 'telegram.env'
if target.exists() and target.stat().st_size:
    raise SystemExit('Telegram credentials already exist; preserving them.')
token = getpass.getpass('BotFather token (hidden): ').strip()
if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
    raise SystemExit('Invalid token format. Nothing saved.')
try:
    with urllib.request.urlopen('https://api.telegram.org/bot' + token + '/getMe', timeout=20) as response:
        result = json.load(response)
    if not result.get('ok') or not result['result'].get('is_bot'):
        raise ValueError()
    username = result['result']['username']
    if not re.fullmatch(r'[A-Za-z0-9_]+', username):
        raise ValueError()
except Exception:
    raise SystemExit('Telegram verification failed. Token was not saved or printed.') from None
os.umask(0o077)
with target.open('w') as output:
    output.write('BOT_TOKEN=' + token + '\nTELEGRAM_BOT_TOKEN=' + token + '\n')
with (base / '.env').open('a') as output:
    output.write('TELEGRAM_BOT_USERNAME=' + username + '\n')
print('Telegram credentials saved privately. Bot: @' + username)
