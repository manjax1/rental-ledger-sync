import json
import os
import time
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
import plaid
from plaid.api import plaid_api
from plaid.exceptions import ApiException
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.sandbox_public_token_create_request_options import SandboxPublicTokenCreateRequestOptions
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions

from plaid.model.country_code import CountryCode
from plaid.model.products import Products

from utils import clean_env

_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)


class PlaidClient:
    _ENV_MAP = {
        "sandbox": "https://sandbox.plaid.com",
        "development": "https://development.plaid.com",
        "production": "https://production.plaid.com",
    }

    def __init__(self):
        client_id = clean_env(os.getenv("PLAID_CLIENT_ID", ""), "PLAID_CLIENT_ID")
        secret    = clean_env(os.getenv("PLAID_SECRET", ""), "PLAID_SECRET")
        self.env = os.getenv("PLAID_ENV", "sandbox").lower()
        host = self._ENV_MAP.get(self.env, "https://sandbox.plaid.com")
        configuration = plaid.Configuration(
            host=host,
            api_key={
                "clientId": client_id,
                "secret":   secret,
            },
        )
        self._client = plaid_api.PlaidApi(plaid.ApiClient(configuration))
        self._client_name = os.getenv("PLAID_CLIENT_NAME", "Rental Ledger Sync")

    def create_link_token(self, user_id: str = "default-user") -> str:
        """Generate a Plaid Link token to initialize the Link flow."""
        request = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
            client_name=self._client_name,
            products=[Products("transactions")],
            country_codes=[CountryCode("US")],
            language="en",
        )
        response = self._client.link_token_create(request)
        return response.link_token

    def get_sandbox_access_token(self) -> str:
        """Bypass Plaid Link by creating a sandbox public token directly and exchanging it."""
        if self.env != "sandbox":
            raise RuntimeError("Cannot use sandbox token in production environment")
        request = SandboxPublicTokenCreateRequest(
            institution_id=os.environ["PLAID_TEST_INSTITUTION"],
            initial_products=[Products("transactions")],
            options=SandboxPublicTokenCreateRequestOptions(
                override_username=os.environ["PLAID_TEST_USERNAME"],
                override_password=os.environ["PLAID_TEST_PASSWORD"],
            ),
        )
        response = self._client.sandbox_public_token_create(request)
        return self.exchange_public_token(response.public_token)

    def verify_access_token(self, access_token: str) -> bool:
        """
        Validate an access token with a lightweight /accounts/get call.

        Returns True if the token is valid.
        Returns False if Plaid reports INVALID_ACCESS_TOKEN or ITEM_LOGIN_REQUIRED.
        Raises ApiException for any other error.
        """
        try:
            self._client.accounts_get(AccountsGetRequest(access_token=access_token))
            return True
        except ApiException as e:
            error_code = json.loads(e.body).get("error_code")
            if error_code in ("INVALID_ACCESS_TOKEN", "ITEM_LOGIN_REQUIRED"):
                return False
            raise

    def exchange_public_token(self, public_token: str) -> str:
        """Exchange a Plaid Link public token for a permanent access token."""
        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = self._client.item_public_token_exchange(request)
        return response.access_token

    def get_transactions(
        self,
        access_token: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """
        Fetch all transactions for the given date range.

        Returns a list of dicts with keys:
            date, name, amount, category, account_id
        """
        request = TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
        )

        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._client.transactions_get(request)
                break
            except ApiException as e:
                error_code = json.loads(e.body).get("error_code")
                if error_code == "PRODUCT_NOT_READY" and attempt < max_attempts:
                    print(f"Transactions not ready yet, retrying in 2 seconds... (attempt {attempt} of {max_attempts})")
                    time.sleep(2)
                else:
                    raise

        transactions = list(response.transactions)

        # Paginate through remaining pages if total exceeds first page
        while len(transactions) < response.total_transactions:
            request.options = TransactionsGetRequestOptions(offset=len(transactions))
            transactions += self._client.transactions_get(request).transactions

        return [
            {
                "date": t.date,
                "name": t.name,
                "amount": t.amount,
                "category": ", ".join(t.category) if t.category else "",
                "account_id": t.account_id,
            }
            for t in transactions
        ]
