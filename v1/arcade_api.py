import json
import urllib.error
import urllib.request


class ApiRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def api_request(
    server_url: str,
    path: str,
    method: str = "GET",
    token: str | None = None,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{server_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            details = json.load(error)
        except ValueError:
            details = {}
        if not isinstance(details, dict):
            details = {}
        message = details.get("error", f"Server returned HTTP {error.code}.")
        raise ApiRequestError(str(message), error.code) from error
    except urllib.error.URLError as error:
        raise ApiRequestError(f"Could not reach the Arcade server: {error.reason}") from error
    except ValueError as error:
        raise ApiRequestError("The Arcade server returned invalid JSON.") from error
    if not isinstance(result, dict):
        raise ApiRequestError("The Arcade server returned an invalid response.")
    if result.get("ok") is False:
        raise ApiRequestError(str(result.get("error", "The request failed.")))
    return result
