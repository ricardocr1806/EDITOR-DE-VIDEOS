"""Posta vídeos no TikTok (e outras redes) pela Zernio, que já tem app aprovado pelo TikTok.

Grátis para até 2 contas conectadas. Publica direto, público e com legenda, ou agenda.

Configuração: variável de ambiente ZERNIO_API_KEY (painel da Zernio > API keys). Nunca no chat.

Uso:
    python -m agente_tiktok.zernio contas
    python -m agente_tiktok.zernio postar video.mp4 --legenda "texto #hashtag"
    python -m agente_tiktok.zernio postar video.mp4 --legenda "..." --agendar 2026-11-03T18:00
    python -m agente_tiktok.zernio status POST_ID

A legenda nunca sai com @ (preferência do usuário): menções são removidas antes de enviar.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

API = "https://zernio.com/api/v1"
FUSO = "America/Sao_Paulo"


class ErroZernio(Exception):
    pass


def _chave() -> str:
    chave = os.environ.get("ZERNIO_API_KEY", "").strip()
    if not chave:
        raise ErroZernio("Falta a variável ZERNIO_API_KEY. Adicione nas configurações do ambiente "
                         "(menu do ambiente > Editar > variáveis de ambiente) e abra uma sessão nova.")
    return chave


def _req(metodo: str, caminho: str, **kw) -> dict[str, Any]:
    r = requests.request(metodo, f"{API}{caminho}",
                         headers={"Authorization": f"Bearer {_chave()}"}, timeout=180, **kw)
    try:
        dados = r.json()
    except ValueError:
        dados = {"error": r.text[:300]}
    if r.status_code >= 400:
        msg = dados.get("error") or dados.get("message") or dados
        if r.status_code == 401:
            msg = "chave da API inválida ou revogada (ZERNIO_API_KEY)"
        raise ErroZernio(f"HTTP {r.status_code}: {msg}")
    dados["_http"] = r.status_code
    return dados


# ------------------------------------------------------------------ legenda
_ARROBA = re.compile(r"(?<![\w.])@[\w.]+")


def sem_arrobas(texto: str) -> str:
    """Tira @menções e arruma os espaços que sobram (hashtags ficam)."""
    texto = _ARROBA.sub("", texto)
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    texto = re.sub(r" +([,.!?;:])", r"\1", texto)
    return "\n".join(l.strip() for l in texto.splitlines()).strip()


# ------------------------------------------------------------------ contas
def contas() -> list[dict[str, Any]]:
    return _req("GET", "/accounts").get("accounts", [])


def conta_tiktok(usuario: str | None = None) -> dict[str, Any]:
    tiktoks = [c for c in contas() if c.get("platform") == "tiktok"]
    if usuario:
        alvo = usuario.lstrip("@").lower()
        tiktoks = [c for c in tiktoks if alvo in (str(c.get("username", "")).lower(),
                                                  str(c.get("displayName", "")).lower())]
    if not tiktoks:
        raise ErroZernio("Nenhuma conta do TikTok conectada na Zernio" + (f" com o nome {usuario}" if usuario else "")
                         + ". Conecte no painel da Zernio.")
    if len(tiktoks) > 1 and not usuario:
        nomes = ", ".join("@" + str(c.get("username")) for c in tiktoks)
        raise ErroZernio(f"Há mais de uma conta do TikTok ({nomes}). Diga qual com --conta.")
    return tiktoks[0]


def privacidades(account_id: str) -> list[str]:
    dados = _req("GET", f"/accounts/{account_id}/tiktok/creator-info", params={"mediaType": "video"})
    niveis = dados.get("privacyLevels") or dados.get("creatorInfo", {}).get("privacyLevels") or []
    return [n["value"] if isinstance(n, dict) else n for n in niveis]


# ------------------------------------------------------------------ mídia e post
def enviar_midia(arquivo: Path) -> str:
    tipo = mimetypes.guess_type(arquivo.name)[0] or "video/mp4"
    pre = _req("POST", "/media/presign",
               json={"filename": arquivo.name, "contentType": tipo, "size": arquivo.stat().st_size})
    with arquivo.open("rb") as f:
        r = requests.put(pre["uploadUrl"], data=f, headers={"Content-Type": tipo}, timeout=600)
    if r.status_code >= 300:
        raise ErroZernio(f"Falha ao enviar o arquivo: HTTP {r.status_code}")
    return pre["publicUrl"]


def postar(arquivo: Path, legenda: str, usuario: str | None = None, privacidade: str = "PUBLIC_TO_EVERYONE",
           agendar: str | None = None, fuso: str = FUSO) -> dict[str, Any]:
    conta = conta_tiktok(usuario)
    permitidas = privacidades(conta["_id"])
    if permitidas and privacidade not in permitidas:
        raise ErroZernio(f"Privacidade {privacidade} não disponível nessa conta. Opções: {', '.join(permitidas)}")

    corpo: dict[str, Any] = {
        "content": sem_arrobas(legenda),
        "mediaItems": [{"url": enviar_midia(arquivo), "type": "video"}],
        "platforms": [{"platform": "tiktok", "accountId": conta["_id"]}],
        "tiktokSettings": {
            "privacy_level": privacidade,
            "allow_comment": True, "allow_duet": True, "allow_stitch": True,
            # O usuário pediu o post e revisou o vídeo antes: são as confirmações que o TikTok exige.
            "content_preview_confirmed": True, "express_consent_given": True,
        },
    }
    if agendar:
        corpo.update({"scheduledFor": agendar, "timezone": fuso})
    else:
        corpo["publishNow"] = True

    dados = _req("POST", "/posts", json=corpo)
    return resumo(dados, conta)


def resumo(dados: dict[str, Any], conta: dict[str, Any] | None = None) -> dict[str, Any]:
    post = dados.get("post") or {}
    plataformas = post.get("platforms") or []
    tiktok = next((p for p in plataformas if p.get("platform") == "tiktok"), {})
    falhas = [r for r in (dados.get("platformResults") or []) if r.get("status") == "failed" or r.get("error")]
    return {
        "post_id": post.get("_id"),
        "status": post.get("status"),
        "status_tiktok": tiktok.get("status"),
        "link": tiktok.get("platformPostUrl") or dados.get("platformPostUrl"),
        "agendado_para": post.get("scheduledFor"),
        "conta": "@" + str(conta.get("username")) if conta else None,
        "erro": tiktok.get("errorMessage") or (falhas[0].get("error") if falhas else None) or
                (dados.get("error") if dados.get("_http") == 207 else None),
        "avisos": dados.get("warnings") or [],
    }


def status(post_id: str) -> dict[str, Any]:
    return resumo(_req("GET", f"/posts/{post_id}"))


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agente_tiktok.zernio")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("contas", help="lista as contas conectadas na Zernio")
    po = sub.add_parser("postar", help="publica (ou agenda) um vídeo no TikTok")
    po.add_argument("arquivo", type=Path)
    po.add_argument("--legenda", default="")
    po.add_argument("--conta", help="@usuario do TikTok, se houver mais de uma conectada")
    po.add_argument("--privacidade", default="PUBLIC_TO_EVERYONE",
                    help="PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, FOLLOWER_OF_CREATOR, SELF_ONLY")
    po.add_argument("--agendar", help="data e hora local, ex.: 2026-11-03T18:00 (fuso de São Paulo)")
    st = sub.add_parser("status")
    st.add_argument("post_id")
    a = p.parse_args(argv)
    try:
        if a.cmd == "contas":
            saida = [{"plataforma": c.get("platform"), "usuario": c.get("username"),
                      "nome": c.get("displayName"), "id": c.get("_id")} for c in contas()]
        elif a.cmd == "postar":
            saida = postar(a.arquivo, a.legenda, a.conta, a.privacidade, a.agendar)
        else:
            saida = status(a.post_id)
        print(json.dumps(saida, ensure_ascii=False, indent=2))
    except ErroZernio as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    return 0 if a.cmd != "postar" or not saida.get("erro") else 1


if __name__ == "__main__":
    sys.exit(main())
