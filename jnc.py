from __future__ import print_function
from datetime import datetime
import json
import os
import requests

# Config: START

downloadTargetDirectory = '~/Downloads/'
downloadedBooksListFile = '~/.downloadedJncBooks'

loginEmail = 'user@server.tld'
loginPassword = 'somepassword'

# Config: END

downloadTargetDirectory = os.path.expanduser(downloadTargetDirectory)
downloadedBooksListFile = os.path.expanduser(downloadedBooksListFile)
curTime = datetime.now().isoformat()[:23] + 'Z'

r = requests.post(
    'https://api.j-novel.club/api/users/login?include=user',
    headers={'Accept': 'application/json', 'content-type': 'application/json'},
    json={'email': loginEmail, 'password': loginPassword})

loginResponse = r.json()

assert('error' not in loginResponse)

authorizationToken = loginResponse['id']
userId = loginResponse['user']['id']
userName = loginResponse['user']['username']

r = requests.get(
    'https://api.j-novel.club/api/users/%s/' % userId,
    params={'filter': '{"include":[{"ownedBooks":"serie"}]}'},
    headers={'Authorization': authorizationToken})

rawAccountDetails = r.json()

ownedBooksList = rawAccountDetails['ownedBooks']
downloadedBooksList = []

if os.path.exists(downloadedBooksListFile):
	with open(downloadedBooksListFile, 'r') as f:
		downloadedBooksList = [line.strip() for line in f.readlines()]

for book in ownedBooksList:
    bookId = book['id']
    bookTime = book['publishingDate']
    bookTitle = book['title']

    if bookTime > curTime or bookId in downloadedBooksList:
        continue

    fileName = book['titleslug'] + '.epub'
    filePath = os.path.join(downloadTargetDirectory, fileName)

    print('%s %s %s' % (bookTitle, bookId, bookTime))

    r = requests.get(
        'https://api.j-novel.club/api/volumes/%s/getpremiumebook' % bookId,
        params={
            'userId': userId,
            'userName': userName,
            'access_token': authorizationToken
        }, allow_redirects=False)

    if r.status_code != 200:
        print(r.status_code, r.text)
        continue

    downloadedBooksList.append(bookId)

    with open(filePath, 'wb') as f:
        f.write(r.content)

    with open(downloadedBooksListFile, 'a') as f:
        f.write(bookId + '\n')
