"""Posta vídeos no TikTok pela API oficial (Content Posting API + Login Kit).

Configuração (uma vez):
    Variáveis de ambiente TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET (do app no developers.tiktok.com).
    Opcional: TIKTOK_REDIRECT_URI (padrão abaixo) e TIKTOK_REFRESH_TOKEN (para não autorizar de novo).

Uso:
    python -m agente_tiktok.postar link-autorizacao
    python -m agente_tiktok.postar trocar-codigo "URL_COMPLETA_DO_RETORNO"
    python -m agente_tiktok.postar postar video.mp4 --legenda "texto #hashtag" [--modo rascunho|direto]
    python -m agente_tiktok.postar status PUBLISH_ID

Modos:
    rascunho  -> o vídeo chega na caixa de entrada do TikTok; o usuário toca em Publicar no app.
    direto    -> publica direto no perfil. Enquanto o app não for aprovado pelo TikTok, só
                 dá para publicar como privado (SELF_ONLY).

Nunca imprime tokens nem o client secret.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

API = "https://open.tiktokapis.com"
AUTORIZAR = "https://www.tiktok.com/v2/auth/authorize/"
REDIRECT_PADRAO = "https://mentoria.ricardocastro.site/tiktok-callback"
ESCOPOS = "user.info.basic,video.upload,video.publish"
ARQUIVO_TOKEN = Path(os.environ.get("TIKTOK_TOKEN_FILE", Path.home() / ".config/corte-limpo/tiktok.json"))

MB = 1024 * 1024
CHUNK = 10 * MB            # TikTok aceita pedaços de 5 a 64 MB (o último pode ter até 128 MB)
LIMITE_UM_PEDACO = 64 * MB


class ErroTikTok(Exception):
    pass


# ------------------------------------------------------------------ configuração
def _env(nome: str) -> str:
    valor = os.environ.get(nome, "").strip()
    if not valor:
        raise ErroTikTok(
            f"Falta a variável {nome}. Adicione nas configurações do ambiente "
            "(menu do ambiente > Editar > variáveis de ambiente) e abra uma sessão nova."
        )
    return valor


def redirect_uri() -> str:
    return os.environ.get("TIKTOK_REDIRECT_URI", REDIRECT_PADRAO).strip()


# ------------------------------------------------------------------ OAuth
def link_autorizacao(state: str | None = None) -> str:
    params = {
        "client_key": _env("TIKTOK_CLIENT_KEY"),
        "scope": ESCOPOS,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state or secrets.token_urlsafe(12),
    }
    return f"{AUTORIZAR}?{urlencode(params)}"


def extrair_codigo(texto: str) -> str:
    """Aceita a URL inteira do retorno (…?code=…&state=…) ou só o código."""
    texto = texto.strip()
    if texto.startswith("http"):
        query = parse_qs(urlparse(texto).query)
        if "error" in query:
            raise ErroTikTok(f"O TikTok recusou a autorização: {query.get('error_description', query['error'])[0]}")
        if "code" not in query:
            raise ErroTikTok("Esse link não tem o código (?code=...). Copie o endereço inteiro da barra.")
        return query["code"][0]  # parse_qs já desfaz o %2A etc.
    return texto


def _salvar_token(dados: dict[str, Any]) -> dict[str, Any]:
    agora = int(time.time())
    token = {
        "access_token": dados["access_token"],
        "refresh_token": dados["refresh_token"],
        "open_id": dados.get("open_id"),
        "scope": dados.get("scope"),
        "expira_em": agora + int(dados.get("expires_in", 0)),
        "refresh_expira_em": agora + int(dados.get("refresh_expires_in", 0)),
    }
    ARQUIVO_TOKEN.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO_TOKEN.write_text(json.dumps(token))
    ARQUIVO_TOKEN.chmod(0o600)
    return token


def _pedir_token(campos: dict[str, str]) -> dict[str, Any]:
    r = requests.post(
        f"{API}/v2/oauth/token/",
        data={"client_key": _env("TIKTOK_CLIENT_KEY"), "client_secret": _env("TIKTOK_CLIENT_SECRET"), **campos},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    dados = r.json()
    if "access_token" not in dados:
        raise ErroTikTok(f"Falha ao obter token: {dados.get('error_description') or dados.get('error') or dados}")
    return _salvar_token(dados)


def trocar_codigo(texto: str) -> dict[str, Any]:
    return _pedir_token({
        "code": extrair_codigo(texto),
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
    })


def token_valido() -> str:
    """Devolve um access token válido, renovando com o refresh token quando preciso."""
    token = json.loads(ARQUIVO_TOKEN.read_text()) if ARQUIVO_TOKEN.exists() else None
    if token and token["expira_em"] - 300 > time.time():
        return token["access_token"]
    refresh = (token or {}).get("refresh_token") or os.environ.get("TIKTOK_REFRESH_TOKEN", "").strip()
    if not refresh:
        raise ErroTikTok("A conta do TikTok ainda não foi autorizada. Rode: link-autorizacao")
    return _pedir_token({"grant_type": "refresh_token", "refresh_token": refresh})["access_token"]


# ------------------------------------------------------------------ API de postagem
def _api(caminho: str, corpo: dict[str, Any]) -> dict[str, Any]:
    r = requests.post(
        f"{API}{caminho}",
        json=corpo,
        headers={"Authorization": f"Bearer {token_valido()}",
                 "Content-Type": "application/json; charset=UTF-8"},
        timeout=60,
    )
    dados = r.json()
    erro = dados.get("error") or {}
    if erro.get("code") not in (None, "ok"):
        dica = DICAS_ERRO.get(erro.get("code"), "")
        raise ErroTikTok(f"{erro.get('code')}: {erro.get('message')}" + (f"\n{dica}" if dica else ""))
    return dados.get("data") or {}


def plano_de_pedacos(tamanho: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) segundo as regras do TikTok."""
    if tamanho <= LIMITE_UM_PEDACO:
        return tamanho, 1
    total = tamanho // CHUNK  # o resto vai junto no último pedaço
    return CHUNK, total


def enviar_arquivo(upload_url: str, arquivo: Path) -> None:
    tamanho = arquivo.stat().st_size
    chunk, total = plano_de_pedacos(tamanho)
    with arquivo.open("rb") as f:
        for i in range(total):
            inicio = i * chunk
            fim = tamanho - 1 if i == total - 1 else inicio + chunk - 1
            f.seek(inicio)
            pedaco = f.read(fim - inicio + 1)
            r = requests.put(
                upload_url,
                data=pedaco,
                headers={"Content-Type": "video/mp4",
                         "Content-Length": str(len(pedaco)),
                         "Content-Range": f"bytes {inicio}-{fim}/{tamanho}"},
                timeout=300,
            )
            if r.status_code not in (200, 201, 206):
                raise ErroTikTok(f"Falha no envio do pedaço {i + 1}/{total}: HTTP {r.status_code} {r.text[:200]}")


def info_do_criador() -> dict[str, Any]:
    return _api("/v2/post/publish/creator_info/query/", {})


def postar(arquivo: Path, legenda: str, modo: str = "rascunho", privacidade: str | None = None,
           esperar: bool = True) -> dict[str, Any]:
    tamanho = arquivo.stat().st_size
    chunk, total = plano_de_pedacos(tamanho)
    origem = {"source": "FILE_UPLOAD", "video_size": tamanho, "chunk_size": chunk, "total_chunk_count": total}

    if modo == "rascunho":
        dados = _api("/v2/post/publish/inbox/video/init/", {"source_info": origem})
    else:
        criador = info_do_criador()
        opcoes = criador.get("privacy_level_options") or ["SELF_ONLY"]
        nivel = privacidade or ("PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in opcoes else opcoes[0])
        if nivel not in opcoes:
            raise ErroTikTok(f"Privacidade {nivel} não permitida para esta conta/app. Opções: {', '.join(opcoes)}")
        dados = _api("/v2/post/publish/video/init/", {
            "post_info": {"title": legenda[:2200], "privacy_level": nivel,
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                          "video_cover_timestamp_ms": 1000},
            "source_info": origem,
        })

    enviar_arquivo(dados["upload_url"], arquivo)
    resultado = {"publish_id": dados["publish_id"], "modo": modo, "arquivo": arquivo.name}
    if esperar:
        resultado.update(acompanhar(dados["publish_id"]))
    return resultado


DICAS_ERRO = {
    "unaudited_client_can_only_post_to_private_accounts":
        "App ainda não aprovado pelo TikTok só posta direto em conta privada. Use --modo rascunho "
        "ou peça a aprovação (Submit for review) na aba Produção.",
    "spam_risk_too_many_posts": "Limite diário de posts pela API atingido. Tente amanhã.",
    "spam_risk_user_banned_from_posting": "A conta está impedida de postar pelo TikTok.",
    "access_token_invalid": "Autorização expirada ou revogada. Gere um novo link de autorização.",
    "scope_not_authorized": "A conta não autorizou essa permissão. Autorize de novo.",
}

FINAIS = {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"}


def status(publish_id: str) -> dict[str, Any]:
    return _api("/v2/post/publish/status/fetch/", {"publish_id": publish_id})


def acompanhar(publish_id: str, limite_s: int = 300) -> dict[str, Any]:
    fim = time.time() + limite_s
    dados: dict[str, Any] = {}
    while time.time() < fim:
        dados = status(publish_id)
        if dados.get("status") in FINAIS:
            break
        time.sleep(5)
    return {"status": dados.get("status"), "motivo_falha": dados.get("fail_reason"),
            "ids_publicados": dados.get("publicaly_available_post_id") or []}


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agente_tiktok.postar")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("link-autorizacao", help="mostra o link para autorizar a conta do TikTok")
    t = sub.add_parser("trocar-codigo", help="troca o código do retorno pelo token")
    t.add_argument("url_ou_codigo")
    sub.add_parser("criador", help="mostra as opções de privacidade e limites da conta")
    po = sub.add_parser("postar", help="envia um vídeo")
    po.add_argument("arquivo", type=Path)
    po.add_argument("--legenda", default="")
    po.add_argument("--modo", choices=["rascunho", "direto"], default="rascunho")
    po.add_argument("--privacidade", help="PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, FOLLOWER_OF_CREATOR, SELF_ONLY")
    st = sub.add_parser("status")
    st.add_argument("publish_id")
    a = p.parse_args(argv)

    try:
        if a.cmd == "link-autorizacao":
            print(link_autorizacao())
        elif a.cmd == "trocar-codigo":
            tok = trocar_codigo(a.url_ou_codigo)
            dias = (tok["refresh_expira_em"] - time.time()) / 86400
            print(json.dumps({"ok": True, "open_id": tok["open_id"], "escopos": tok["scope"],
                              "autorizacao_vale_dias": math.floor(dias)}, ensure_ascii=False))
        elif a.cmd == "criador":
            print(json.dumps(info_do_criador(), ensure_ascii=False, indent=2))
        elif a.cmd == "postar":
            print(json.dumps(postar(a.arquivo, a.legenda, a.modo, a.privacidade), ensure_ascii=False, indent=2))
        elif a.cmd == "status":
            print(json.dumps(status(a.publish_id), ensure_ascii=False, indent=2))
    except ErroTikTok as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
