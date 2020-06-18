from __future__ import print_function
from datetime import datetime, timezone
import csv
import os
import sys
from jnc_calls import login, request_owned_books
import requests

# Config: START

download_target_dir = '~/Downloads/'
downloaded_books_list_file = '~/.downloadedJncBooks'

login_email = 'user'
login_pw = 'password'

# Config: END

download_target_dir = os.path.expanduser(download_target_dir)
downloaded_books_list_file = os.path.expanduser(downloaded_books_list_file)
cur_time = datetime.now(timezone.utc).isoformat()[:23] + 'Z'

login_response = login(login_email, login_pw)

if 'error' in login_response:
    print('Login failed!')
    sys.exit()

auth_token = login_response['id']
user_id = login_response['user']['id']
user_name = login_response['user']['username']

raw_account_details = request_owned_books(user_id, auth_token)

owned_books = raw_account_details['ownedBooks']

owned_books = sorted(
    owned_books,
    key=lambda book: (book['serie']['titleslug'], book['volumeNumber']))

downloaded_book_ids = []

if os.path.exists(downloaded_books_list_file):
    with open(downloaded_books_list_file, 'r') as f:
        downloaded_book_ids = [row[0] for row in csv.reader(f, delimiter='\t')]

downloaded_books = []
preordered_books = []

for book in owned_books:
    book_id = book['id']
    book_time = book['publishingDate']
    book_title = book['title']

    if book_id in downloaded_book_ids:
        downloaded_books.append([book_id, book_title])
        continue

    if book_time > cur_time:
        preordered_books.append([book_title, book_id, book_time])
        continue

    print('%s \t%s \t%s' % (book_title, book_id, book_time))

    book_file_name = book['titleslug'] + '.epub'
    book_file_path = os.path.join(download_target_dir, book_file_name)

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

    downloaded_books.append([book_id, book_title])

    with open(book_file_path, 'wb') as f:
        f.write(r.content)

with open(downloaded_books_list_file, 'w') as f:
    csv_writer = csv.writer(f, delimiter='\t')
    csv_writer.writerows(downloaded_books)

requests.post(
    'https://api.j-novel.club/api/users/logout',
    headers={'Authorization': auth_token}
)

print('Finished downloading and logged out')

if len(preordered_books) > 0:
    print('\nBooks scheduled to be released after %s' % cur_time)

    for book_title, book_id, book_time in preordered_books:
        print('%s  %s' % (book_time, book_title))
