"""Read-only Trilium ETAPI client: only GET requests, by construction."""

import httpx


class EtapiClient:
    def __init__(self, url: str, token: str, transport: httpx.BaseTransport | None = None, timeout: float = 30):
        self._http = httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": token},
                                  transport=transport, timeout=timeout)

    def _get(self, path: str, **params) -> httpx.Response:
        response = self._http.get(path, params=params)
        response.raise_for_status()
        return response

    def search(self, query: str, ancestor: str | None = None) -> list[dict]:
        params = {"search": query, "fastSearch": "true"}
        if ancestor:
            params["ancestorNoteId"] = ancestor
        return self._get("/notes", **params).json()["results"]

    def content(self, note_id: str) -> str:
        return self._get(f"/notes/{note_id}/content").text

    def app_info(self) -> dict:
        return self._get("/app-info").json()
