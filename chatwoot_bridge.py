"""Integração Chatwoot: REST autenticado + validação HMAC de webhooks.
Nunca envia respostas de IA automaticamente.
"""
import hashlib
import hmac
import os
import time
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def settings():
    url = os.getenv('CHATWOOT_URL', '').rstrip('/')
    account = os.getenv('CHATWOOT_ACCOUNT_ID', '')
    token = os.getenv('CHATWOOT_API_TOKEN', '')
    if not (url and account.isdecimal() and token):
        raise HTTPException(503, 'Ligação ao Chatwoot ainda não configurada')
    parsed = urlparse(url)
    if parsed.scheme != 'https' and not (os.getenv('RISE_ALLOW_LOCAL_HTTP') == 'true' and parsed.hostname in ('localhost','127.0.0.1')):
        raise HTTPException(503, 'É necessário HTTPS para o servidor Chatwoot')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(503, 'URL Chatwoot inválido')
    return url, int(account), token


async def chatwoot_get(path):
    url, account, token = settings()
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        try:
            response = await client.get(f'{url}/api/v1/accounts/{account}/{path.lstrip("/")}', headers={'api_access_token': token})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, 'Não foi possível consultar o Chatwoot') from exc


async def chatwoot_post(path, payload):
    url, account, token = settings()
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        try:
            response = await client.post(f'{url}/api/v1/accounts/{account}/{path.lstrip("/")}', json=payload, headers={'api_access_token': token})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, 'Não foi possível enviar a mensagem no Chatwoot') from exc


def verify_webhook(raw: bytes, headers, secret: str, now=None, tolerance=300):
    if len(raw) > 250_000 or not secret:
        return False
    stamp = headers.get('x-chatwoot-timestamp', '')
    signature = headers.get('x-chatwoot-signature', '')
    if not stamp.isdecimal() or len(stamp) > 14:
        return False
    now = int(time.time()) if now is None else now
    if abs(now - int(stamp)) > tolerance:
        return False
    digest = hmac.new(secret.encode(), stamp.encode()+b'.'+raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest('sha256='+digest, signature)
