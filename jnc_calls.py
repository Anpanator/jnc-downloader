import requests

LOGIN_URL = 'https://api.j-novel.club/api/users/login?include=user'
API_USER_URL_PATTERN = 'https://api.j-novel.club/api/users/%s/'


def login(login_email, password):
    """Sends a login request to JNC. This method will not work if the user uses SSO (Google, Facebook)

    :param login_email
    :param password"""
    return requests.post(
        LOGIN_URL,
        headers={'Accept': 'application/json', 'content-type': 'application/json'},
        json={'email': login_email, 'password': password}
    ).json()


def request_owned_books(user_id, auth_token):
    """Requests the list of owned books from JNC.

    :param user_id the id of the user. Note that this is different from the user name (login email)
    :param auth_token the token that's returned in the login response."""
    return requests.get(
        API_USER_URL_PATTERN % user_id,
        params={'filter': '{"include":[{"ownedBooks":"serie"}]}'},
        headers={'Authorization': auth_token}
    ).json()
