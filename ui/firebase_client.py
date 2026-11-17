"""Firebase Authentication REST calls used by the Streamlit UI (email and password flows).

Google sign-in needs a browser popup, so it lives in the `firebase_google` component;
everything else is plain HTTPS to Firebase with the project's public web API key.
Only `requests` is needed.
"""

import time
from dataclasses import dataclass

import requests

IDENTITY_URL = "https://identitytoolkit.googleapis.com/v1"
TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
TIMEOUT = 20

# Firebase error codes -> messages a student can act on.
MESSAGES = {
    "EMAIL_EXISTS": "An account with this email already exists. Sign in instead.",
    "INVALID_LOGIN_CREDENTIALS": "The email or password is incorrect.",
    "INVALID_PASSWORD": "The email or password is incorrect.",
    "EMAIL_NOT_FOUND": "The email or password is incorrect.",
    "INVALID_EMAIL": "Enter a valid email address.",
    "MISSING_PASSWORD": "Enter a password.",
    "WEAK_PASSWORD": "Choose a password of at least 6 characters.",
    "USER_DISABLED": "This account has been disabled.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Wait a few minutes and try again.",
    "OPERATION_NOT_ALLOWED": "This sign-in method is not enabled in the Firebase project.",
    "CREDENTIAL_TOO_OLD_LOGIN_AGAIN": "Please sign in again, then retry.",
    "TOKEN_EXPIRED": "Your session has ended. Please sign in again.",
    "INVALID_REFRESH_TOKEN": "Your session has ended. Please sign in again.",
    "USER_NOT_FOUND": "Your session has ended. Please sign in again.",
    "INVALID_ID_TOKEN": "Your session has ended. Please sign in again.",
    "NETWORK_ERROR": "Cannot reach Firebase. Check your internet connection and try again.",
}


class FirebaseError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(MESSAGES.get(code, f"Sign-in failed ({code})."))


@dataclass
class FirebaseSession:
    id_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    provider: str = "password"

    def expires_soon(self, margin_s: int = 300) -> bool:
        return time.time() > self.expires_at - margin_s


def _code(response: requests.Response) -> str:
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return f"HTTP_{response.status_code}"
    # e.g. "WEAK_PASSWORD : Password should be at least 6 characters"
    return str(message).split(" ")[0].split(":")[0].strip()


class FirebaseClient:
    def __init__(self, api_key: str, identity_url: str = IDENTITY_URL, token_url: str = TOKEN_URL):
        self.api_key = api_key
        self.identity_url = identity_url.rstrip("/")
        self.token_url = token_url

    def _post(self, url: str, **kwargs) -> dict:
        try:
            response = requests.post(url, params={"key": self.api_key}, timeout=TIMEOUT, **kwargs)
        except requests.RequestException:
            raise FirebaseError("NETWORK_ERROR") from None
        if not response.ok:
            raise FirebaseError(_code(response))
        return response.json()

    def _account(self, method: str, body: dict) -> dict:
        return self._post(f"{self.identity_url}/accounts:{method}", json=body)

    @staticmethod
    def _session(data: dict, provider: str = "password") -> FirebaseSession:
        return FirebaseSession(
            id_token=data["idToken"],
            refresh_token=data["refreshToken"],
            expires_at=time.time() + int(data.get("expiresIn", 3600)),
            provider=provider,
        )

    def sign_up(self, email: str, password: str) -> FirebaseSession:
        body = {"email": email.strip(), "password": password, "returnSecureToken": True}
        return self._session(self._account("signUp", body))

    def sign_in(self, email: str, password: str) -> FirebaseSession:
        body = {"email": email.strip(), "password": password, "returnSecureToken": True}
        return self._session(self._account("signInWithPassword", body))

    def refresh(self, session: FirebaseSession) -> FirebaseSession:
        data = self._post(
            self.token_url,
            data={"grant_type": "refresh_token", "refresh_token": session.refresh_token},
        )
        return FirebaseSession(
            id_token=data["id_token"],
            refresh_token=data["refresh_token"],
            expires_at=time.time() + int(data.get("expires_in", 3600)),
            provider=session.provider,
        )

    def send_password_reset(self, email: str) -> None:
        self._account("sendOobCode", {"requestType": "PASSWORD_RESET", "email": email.strip()})

    def send_verification_email(self, session: FirebaseSession) -> None:
        self._account("sendOobCode", {"requestType": "VERIFY_EMAIL", "idToken": session.id_token})

    def delete_account(self, session: FirebaseSession) -> None:
        self._account("delete", {"idToken": session.id_token})
