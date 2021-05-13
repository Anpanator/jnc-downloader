import requests


class JNCUserData:
    user_id: str
    user_name: str
    auth_token: str
    premium_credits: int
    account_type: str

    def __init__(self, user_id: str, user_name: str, auth_token: str, premium_credits: int, account_type: str):
        self.user_id = user_id
        self.user_name = user_name
        self.auth_token = auth_token
        self.premium_credits = premium_credits
        self.account_type = account_type


class JNClient:
    """Everything you need to talk to the JNC API"""

    LOGIN_URL = 'https://api.j-novel.club/api/users/login?include=user'
    FETCH_LIBRARY_URL = 'https://labs.j-novel.club/app/v1/me/library?include=serie&format=json'

    ACCOUNT_TYPE_PREMIUM = 'PremiumMembership'

    @staticmethod
    def login(user: str, password: str) -> JNCUserData:
        """
        :raise JNCApiError when the login failed
        """
        login_response = requests.post(
            JNClient.LOGIN_URL,
            headers={'Accept': 'application/json', 'content-type': 'application/json'},
            json={'email': user, 'password': password}
        ).json()

        if 'error' in login_response:
            raise JNCApiError('Login failed!')

        subscription = login_response['user']['currentSubscription']
        return JNCUserData(
            user_id=login_response['user']['id'],
            user_name=login_response['user']['name'],
            auth_token=login_response['id'],
            premium_credits=login_response['user']['earnedCredits'] - login_response['user']['usedCredits'],
            account_type=subscription['plan']['id'] if 'plan' in subscription else None
        )


class JNCApiError(Exception):
    pass


class NoCreditsError(Exception):
    pass


class ArgumentError(Exception):
    pass
