import requests


class UnipileClient:
    def __init__(self, api_key: str, base_url: str = "https://api40.unipile.com:17075/api/v1"):
        self.api_key = api_key
        self.base_url = base_url

    def _headers(self) -> dict:
        return {"X-API-KEY": self.api_key, "accept": "application/json"}

    def get_accounts(self) -> list[dict]:
        response = requests.get(
            f"{self.base_url}/accounts",
            headers=self._headers(),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return data["items"] if isinstance(data, dict) and "items" in data else data

    def get_relations(self, account_id: str) -> list[dict]:
        """List a LinkedIn account's accepted connections (relations).

        Confirmed via https://developer.unipile.com/reference/userscontroller_getrelations :
        GET /users/relations?account_id=... -> {"object": "UserRelationsList", "items": [...]}
        Each item includes `public_profile_url` among other fields.
        """
        response = requests.get(
            f"{self.base_url}/users/relations",
            headers=self._headers(),
            params={"account_id": account_id},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return data["items"] if isinstance(data, dict) and "items" in data else data
