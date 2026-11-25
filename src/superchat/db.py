"""Thin PostgREST client. Every call is made as the signed-in person, so the database rules apply."""
import httpx

from . import auth
from .config import Settings


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status, self.code = status, code


class Api:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.http = client or httpx.Client(timeout=60)

    def _headers(self, signed_in: bool, extra: dict | None = None) -> dict:
        tok = auth.access_token(self.s, self.http) if signed_in else self.s.supabase_key
        h = {"apikey": self.s.supabase_key, "Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def _check(self, r: httpx.Response):
        if r.status_code < 400:
            return r.json() if r.content else None
        try:
            j = r.json()
        except ValueError:
            j = {}
        msg = j.get("message") or j.get("msg") or r.text[:300]
        if r.status_code in (401, 403) and not j.get("code"):
            msg = "Not allowed: " + msg
        raise ApiError(msg, r.status_code, str(j.get("code", "")))

    def rpc(self, fn: str, params: dict | None = None, signed_in: bool = True):
        r = self.http.post(f"{self.s.supabase_url}/rest/v1/rpc/{fn}",
                           headers=self._headers(signed_in), json=params or {})
        return self._check(r)

    def select(self, table: str, **query):
        r = self.http.get(f"{self.s.supabase_url}/rest/v1/{table}", headers=self._headers(True), params=query)
        return self._check(r)

    def insert(self, table: str, rows, upsert_on: str | None = None):
        extra = {"Prefer": "return=representation" + (",resolution=merge-duplicates" if upsert_on else "")}
        params = {"on_conflict": upsert_on} if upsert_on else None
        r = self.http.post(f"{self.s.supabase_url}/rest/v1/{table}",
                           headers=self._headers(True, extra), json=rows, params=params)
        return self._check(r)

    def delete(self, table: str, **query):
        r = self.http.delete(f"{self.s.supabase_url}/rest/v1/{table}",
                             headers=self._headers(True, {"Prefer": "return=representation"}), params=query)
        return self._check(r)

    def schema_version(self) -> str:
        return self.rpc("superchat_version", signed_in=False)
