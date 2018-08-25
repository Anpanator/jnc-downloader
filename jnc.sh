#!/bin/bash
set -e
command -v jq > /dev/null
command -v curl > /dev/null
#Config: START

downloadTargetDirectory=~/Downloads/
loginEmail='user@server.tld'
loginPassword='somepassword'

#Config: END


curTime=$(date -u +%s)
loginResponseFile=~/.jncLoginData.json
rawAccountDetailsFile=~/.rawAccountDetails.json
ownedBooksList=~/.ownedJncBooks
downloadedBooksList=~/.downloadedJncBooks
touch "$downloadedBooksList"

curl --silent --request 'POST' "https://api.j-novel.club/api/users/login?include=user" \
--header "Accept: application/json" \
--header "content-type: application/json" \
--data "{\"email\":\"${loginEmail}\",\"password\":\"${loginPassword}\"}" \
> "$loginResponseFile"

if grep -Fo 'login failed' "$loginResponseFile";
  then
  exit 1
fi

authorizationToken=$(jq -r '.["id"]' "$loginResponseFile")
userId=$(jq -r '.["user"]["id"]' "$loginResponseFile")
userName=$(jq -r '.["user"]["username"]' "$loginResponseFile")

#Get access tokens and owned books of this account
detailsRequestUrl='https://api.j-novel.club/api/users/'
detailsRequestUrl+=$userId
detailsRequestUrl+='?filter={"include":[{"ownedBooks":"serie"}]}'

curl --globoff --silent --request 'GET' "$detailsRequestUrl" --header "Authorization: $authorizationToken" \
> "$rawAccountDetailsFile"

#Parse the "ownedBooks" section of the raw account information for the relevant data, pipe-separated
jq -r '.["ownedBooks"][] | .id + "|" + .publishingDate + "|" + .title' "$rawAccountDetailsFile" > "$ownedBooksList"

cd "$downloadTargetDirectory"
while read line;
  do
  bookId=$(cut -d '|' -f 1 <<< $line)
  bookTime=$(cut -d '|' -f 2 <<< $line | xargs date +%s -d)
  bookTitle=$(cut -d '|' -f 3 <<< $line)
  if [ $curTime -gt $bookTime ] &&  ! grep -Fxq "$bookId" "$downloadedBooksList";
    then
      set +e
      echo "$bookId 	 $bookTime 	 $bookTitle"
      downloadLink="https://api.j-novel.club/api/volumes/${bookId}/getpremiumebook?userId=${userId}&userName=${userName}&access_token=$authorizationToken"
      curl -O -J -f --globoff "$downloadLink"
      if [ $? -eq 0 ]
        then
        echo $bookId >> "$downloadedBooksList"
      fi
      set -e
    fi
done < "$ownedBooksList"
cd - > /dev/null

#Log out to invalidate access token
curl --silent --request 'POST' 'https://api.j-novel.club/api/users/logout' \
--header "Authorization: $authorizationToken"
echo 'Finished downloading and logged out'
