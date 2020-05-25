from __future__ import print_function

import os
import sys
from datetime import datetime

import requests

# Config: START

download_target_dir = '~/Downloads/'
downloaded_books_list_file = '~/.downloadedJncBooks'

login_email = 'user@server.tld'
login_pw = 'somepassword'

# Config: END

download_target_dir = os.path.expanduser(download_target_dir)
downloaded_books_list_file = os.path.expanduser(downloaded_books_list_file)
cur_time = datetime.now().isoformat()[:23] + 'Z'

r = requests.post(
    'https://api.j-novel.club/api/users/login?include=user',
    headers={'Accept': 'application/json', 'content-type': 'application/json'},
    json={'email': login_email, 'password': login_pw}
)

login_response = r.json()

if 'error' in login_response:
    print('Login failed!')
    sys.exit()

auth_token = login_response['id']
user_id = login_response['user']['id']
user_name = login_response['user']['username']

r = requests.get(
    'https://api.j-novel.club/api/users/%s/' % user_id,
    params={'filter': '{"include":[{"ownedBooks":"serie"}]}'},
    headers={'Authorization': auth_token}
)

raw_account_details = r.json()

owned_books = raw_account_details['ownedBooks']
downloaded_books = []
new_books = []

if os.path.exists(downloaded_books_list_file):
    with open(downloaded_books_list_file, 'r') as f:
        downloaded_books = [line.strip() for line in f.readlines()]

for book in owned_books:
    book_id = book['id']
    book_time = book['publishingDate']
    book_title = book['title']

    if book_time > cur_time or book_id in downloaded_books:
        continue

    book_file_name = book['titleslug'] + '.epub'
    book_file_path = os.path.join(download_target_dir, book_file_name)

    print('%s \t%s \t%s' % (book_title, book_id, book_time))

    r = requests.get(
        'https://api.j-novel.club/api/volumes/%s/getpremiumebook' % book_id,
        params={
            'userId': user_id,
            'userName': user_name,
            'access_token': auth_token
        }, allow_redirects=False
    )

    if r.status_code != 200:
        print(r.status_code, ': Book not available.')
        continue

    new_books.append(book_id)

    with open(book_file_path, 'wb') as f:
        f.write(r.content)

with open(downloaded_books_list_file, 'a') as f:
    for book_id in new_books:
        f.write(book_id + '\n')

requests.post(
    'https://api.j-novel.club/api/users/logout',
    headers={'Authorization': auth_token}
)

print('Finished downloading and logged out')
