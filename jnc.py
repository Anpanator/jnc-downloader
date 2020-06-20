from __future__ import print_function
import sys
import os
import csv
from datetime import datetime, timezone
from jnc_api_tools import JNClient

# Config: START

download_target_dir = '~/Downloads/'
downloaded_books_list_file = '~/.downloadedJncBooks'

login_email = 'user'
login_pw = 'password'

# Config: END
try:
    jnclient = JNClient(login_email, login_pw)
except RuntimeError as err:
    print(err)
    sys.exit(1)

# overwrite credentials to make sure they're not used later
login_email = None
login_pw = None

download_target_dir = os.path.expanduser(download_target_dir)
downloaded_books_list_file = os.path.expanduser(downloaded_books_list_file)
cur_time = datetime.now(timezone.utc).isoformat()[:23] + 'Z'

owned_books = jnclient.get_owned_books()

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

    try:
        book_content = jnclient.download_book(book_id)

        downloaded_books.append([book_id, book_title])

        with open(book_file_path, 'wb') as f:
            f.write(book_content)
    except RuntimeError as err:
        print(err)

del jnclient

with open(downloaded_books_list_file, 'w') as f:
    csv_writer = csv.writer(f, delimiter='\t')
    csv_writer.writerows(downloaded_books)

if len(preordered_books) > 0:
    print('\nBooks scheduled to be released after %s' % cur_time)

    for book_title, book_id, book_time in preordered_books:
        print('%s  %s' % (book_time, book_title))
