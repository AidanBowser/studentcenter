"""Read-only AssetPanda client.

The live account can change records. This client refuses every call that
would. Two requests are allowed:

* POST /v3/session/token signs in and does not change assets.
* POST /v3/groups/{id}/search/objects is how AssetPanda lists records.
  There is no GET for that list. The body is a query. It does not create,
  update, or delete anything.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import requests

API_ROOT = "https://api.assetpanda.com"
_SEARCH = re.compile(r"^/v3/groups/\d+/search/objects$")


class ReadOnlyError(PermissionError):
    """A call that would change AssetPanda, or that this client does not allow."""


def assert_read_only(method: str, path: str) -> None:
    method = method.upper()
    if not path.startswith("/v3/") or "://" in path:
        raise ReadOnlyError(f"Blocked {method} {path}")
    if method == "GET":
        # AssetPanda describes this GET as creating a report, so it is not a read.
        if re.match(r"^/v3/reports/\d+$", path):
            raise ReadOnlyError(f"Blocked {method} {path}")
        return
    if method == "POST" and path == "/v3/session/token":
        return
    if method == "POST" and _SEARCH.match(path):
        return
    raise ReadOnlyError(f"Blocked {method} {path}")


class AssetPanda:
    def __init__(self, email: str, password: str, http: Callable[..., Any] | None = None):
        self._email = email
        self._password = password
        self._http = http or requests.request
        self._token: str | None = None

    def search_objects(
        self,
        group_id: str,
        body: dict[str, Any] | None = None,
        limit: int = 40,
        offset: int = 0,
    ) -> dict[str, Any]:
        if not str(group_id).isdigit():
            raise ReadOnlyError(f"Blocked group id {group_id}")
        path = f"/v3/groups/{group_id}/search/objects"
        assert_read_only("POST", path)
        query = {} if body is None else dict(body)
        allowed = {"search", "ids", "field_filters", "last_modified", "created_at", "view_archived", "field_match"}
        extra = set(query) - allowed
        if extra:
            raise ReadOnlyError(f"Blocked search fields {sorted(extra)}")
        response = self._send(
            "POST",
            path,
            params={"limit": limit, "offset": offset},
            json=query,
        )
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("AssetPanda search did not return an object")
        return data

    def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        assert_read_only(method, path)
        headers = {"accept": "application/json"}
        if method != "POST" or path != "/v3/session/token":
            headers["authorization"] = f"Bearer {self._token or self._login()}"
        if "json" in kwargs:
            headers["content-type"] = "application/json"
        response = self._http(
            method,
            API_ROOT + path,
            headers=headers,
            timeout=kwargs.pop("timeout", 120),
            **kwargs,
        )
        if getattr(response, "status_code", 200) == 401 and path != "/v3/session/token":
            self._token = None
            headers["authorization"] = f"Bearer {self._login()}"
            response = self._http(
                method,
                API_ROOT + path,
                headers=headers,
                timeout=120,
                **kwargs,
            )
        if getattr(response, "status_code", 200) >= 400:
            raise RuntimeError(f"AssetPanda {method} {path} failed ({response.status_code})")
        return response

    def _login(self) -> str:
        assert_read_only("POST", "/v3/session/token")
        response = self._http(
            "POST",
            API_ROOT + "/v3/session/token",
            headers={"accept": "application/json", "content-type": "application/json"},
            json={"email": self._email, "password": self._password},
            timeout=30,
        )
        if getattr(response, "status_code", 200) >= 400:
            raise RuntimeError("AssetPanda sign-in failed")
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("AssetPanda sign-in returned no token")
        self._token = token
        return token
