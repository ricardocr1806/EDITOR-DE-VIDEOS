"""Acha os reels que estão funcionando num perfil e baixa os melhores.

Uso:
    python -m agente_instagram.virais pablomarcal1 alfredosoares --cookies-do-navegador chrome
    python -m agente_instagram.virais --lista perfis.txt --analisar 24 --baixar 5
    python -m agente_instagram.virais PERFIL --baixar 0        # só a lista, sem baixar

A régra é a do /ig-viral: views cruas não são prova. O que vale é o **múltiplo**
(views do reel ÷ mediana daquele perfil). Acima de 3x é sinal; abaixo de 1,5x é
dia normal da conta e não ensina nada, por maior que seja o número.

O Instagram exige conta logada para listar o perfil. Em servidor na nuvem isso
sempre cai em login ou 429: use --cookies-do-navegador (no Mac) ou --cookies.

Saída:
- tabela no terminal, ordenada por múltiplo;
- virais/capturado.tsv, no formato que o swipe.py do /ig-viral lê;
- os melhores reels baixados em originais/, com o .json de sempre ao lado.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .baixar import (ESPERAS_LIMITE, PASTA_PADRAO, _opcoes_ytdlp, baixar_varios,
                     explicar_erro)

PASTA_VIRAIS = Path(__file__).resolve().parent.parent / "virais"
PAUSA_ENTRE_PERFIS = 8     # pedidos em rajada são o que dispara o 429
SINAL = 3.0                # múltiplo a partir do qual o reel ensina alguma coisa
RUIDO = 1.5                # abaixo disso é o dia normal da conta


@dataclass
class Reel:
    perfil: str
    link: str
    id: str
    views: int | None
    curtidas: int | None
    comentarios: int | None
    data: str | None
    gancho: str
    multiplo: float | None = None


def normalizar_perfil(entrada: str) -> str:
    """'@fulano', 'fulano', 'instagram.com/fulano/reels/' -> 'fulano'."""
    texto = entrada.strip().strip('"').strip("'")
    texto = re.sub(r"^(?:https?://)?(?:www\.|m\.)?instagram\.com/", "", texto, flags=re.I)
    texto = texto.split("?")[0].strip("/")
    texto = re.sub(r"/(reels?|tagged|feed)$", "", texto, flags=re.I)
    return texto.lstrip("@").strip().lower()


def url_dos_reels(perfil: str) -> str:
    return f"https://www.instagram.com/{normalizar_perfil(perfil)}/reels/"


def gancho_da_legenda(legenda: str | None, limite: int = 120) -> str:
    """A primeira linha com texto da legenda, que é o gancho escrito do reel."""
    if not legenda:
        return ""
    for linha in legenda.splitlines():
        limpa = re.sub(r"\s+", " ", linha).strip()
        limpa = re.sub(r"(#\w+\s*)+$", "", limpa).strip()
        if limpa:
            return limpa[:limite]
    return ""


def calcular_multiplos(reels: list[Reel]) -> int | None:
    """Preenche o múltiplo de cada reel e devolve a mediana usada como base."""
    numeros = [r.views for r in reels if r.views]
    if not numeros:
        numeros = [r.curtidas for r in reels if r.curtidas]
        if not numeros:
            return None
        base = int(statistics.median(numeros))
        for r in reels:
            r.multiplo = round(r.curtidas / base, 2) if r.curtidas and base else None
        return base
    base = int(statistics.median(numeros))
    for r in reels:
        r.multiplo = round(r.views / base, 2) if r.views and base else None
    return base


def _numero(info: dict[str, Any], *chaves: str) -> int | None:
    for chave in chaves:
        valor = info.get(chave)
        if isinstance(valor, (int, float)) and valor > 0:
            return int(valor)
    return None


def _reel_de(info: dict[str, Any], perfil: str) -> Reel | None:
    ident = str(info.get("id") or "").split("/")[-1]
    if not ident:
        return None
    link = info.get("webpage_url") or info.get("url") or f"https://www.instagram.com/reel/{ident}/"
    return Reel(
        perfil=perfil,
        link=link,
        id=ident,
        views=_numero(info, "view_count", "play_count"),
        curtidas=_numero(info, "like_count"),
        comentarios=_numero(info, "comment_count"),
        data=info.get("upload_date"),
        gancho=gancho_da_legenda(info.get("description") or info.get("title")),
    )


def listar_reels(perfil: str, analisar: int, cookies: Path | None = None,
                 navegador: str | None = None, dormir=time.sleep) -> tuple[list[Reel], str | None]:
    """Lê os reels recentes de um perfil. Devolve (reels, erro_explicado)."""
    import yt_dlp

    opcoes = _opcoes_ytdlp(PASTA_PADRAO, cookies, navegador)
    opcoes.update({"extract_flat": "in_playlist", "playlistend": analisar, "skip_download": True})
    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            dados = ydl.extract_info(url_dos_reels(perfil), download=False)
    except Exception as erro:  # noqa: BLE001 - a mensagem do yt-dlp é o que interessa
        return [], explicar_erro(str(erro))

    entradas = [e for e in (dados or {}).get("entries", []) if e]
    reels: list[Reel] = []
    faltando: list[dict[str, Any]] = []
    for entrada in entradas:
        reel = _reel_de(entrada, perfil)
        if not reel:
            continue
        if reel.views or reel.curtidas:
            reels.append(reel)
        else:
            faltando.append(entrada)

    # A listagem às vezes vem sem números; aí é preciso abrir reel por reel.
    detalhe = _opcoes_ytdlp(PASTA_PADRAO, cookies, navegador)
    detalhe.update({"skip_download": True})
    for entrada in faltando:
        link = entrada.get("webpage_url") or entrada.get("url")
        if not link:
            continue
        dormir(1.5)
        try:
            with yt_dlp.YoutubeDL(detalhe) as ydl:
                info = ydl.extract_info(link, download=False)
        except Exception:  # noqa: BLE001 - um reel que não abre não derruba o perfil
            continue
        reel = _reel_de(info or {}, perfil)
        if reel:
            reels.append(reel)
    return reels, None


def linhas_tsv(reels: list[Reel], medianas: dict[str, int | None],
               seguidores: dict[str, int | None] | None = None) -> list[str]:
    """TSV no formato que o swipe.py do /ig-viral espera."""
    seguidores = seguidores or {}
    linhas = ["account\tfollowers\tmedian\tviews\thook"]
    for r in reels:
        linhas.append("\t".join([
            f"@{r.perfil}",
            str(seguidores.get(r.perfil) or ""),
            str(medianas.get(r.perfil) or ""),
            str(r.views or r.curtidas or 0),
            r.gancho,
        ]))
    return linhas


def _imprimir(reels: list[Reel], medianas: dict[str, int | None]) -> None:
    print()
    print(f"{'múltiplo':>9}  {'views':>9}  {'perfil':<22} gancho")
    print("-" * 100)
    for r in reels:
        marca = "->" if (r.multiplo or 0) >= SINAL else ("  " if (r.multiplo or 0) >= RUIDO else "  ")
        mult = f"{r.multiplo:.2f}x" if r.multiplo else "-"
        print(f"{marca}{mult:>7}  {str(r.views or r.curtidas or '-'):>9}  @{r.perfil:<21} {r.gancho[:52]}")
    print()
    for perfil, base in medianas.items():
        print(f"@{perfil}: mediana {base or '-'} · sinal a partir de {SINAL}x, ruído abaixo de {RUIDO}x")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m agente_instagram.virais",
        description="Acha os reels que estão funcionando num perfil e baixa os melhores.")
    p.add_argument("perfis", nargs="*", help="@perfil, perfil ou link do perfil")
    p.add_argument("--lista", type=Path, help="arquivo .txt com um perfil por linha")
    p.add_argument("--analisar", type=int, default=18, help="reels recentes lidos por perfil")
    p.add_argument("--baixar", type=int, default=3, help="quantos melhores baixar por perfil (0 = nenhum)")
    p.add_argument("--saida", type=Path, default=PASTA_PADRAO, help="pasta dos vídeos")
    p.add_argument("--tsv", type=Path, default=PASTA_VIRAIS / "capturado.tsv")
    p.add_argument("--cookies", type=Path, help="arquivo cookies.txt de uma conta logada")
    p.add_argument("--cookies-do-navegador", metavar="NAVEGADOR", dest="cookies_do_navegador",
                   help="chrome, firefox, edge, safari, brave...")
    p.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    args = p.parse_args(argv)

    perfis = [normalizar_perfil(x) for x in args.perfis]
    if args.lista:
        perfis += [normalizar_perfil(l) for l in args.lista.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.lstrip().startswith("#")]
    perfis = [x for i, x in enumerate(perfis) if x and x not in perfis[:i]]
    if not perfis:
        p.error("informe ao menos um perfil (ou --lista)")

    todos: list[Reel] = []
    medianas: dict[str, int | None] = {}
    erros: dict[str, str] = {}
    for i, perfil in enumerate(perfis):
        if i:
            time.sleep(PAUSA_ENTRE_PERFIS)
        reels, erro = listar_reels(perfil, args.analisar, args.cookies, args.cookies_do_navegador)
        if erro:
            erros[perfil] = erro
            print(f"@{perfil}: {erro}", file=sys.stderr)
            continue
        medianas[perfil] = calcular_multiplos(reels)
        todos += reels

    todos.sort(key=lambda r: (r.multiplo or 0), reverse=True)

    baixados: list[dict[str, Any]] = []
    if todos and args.baixar > 0:
        escolhidos: list[str] = []
        for perfil in medianas:
            do_perfil = [r for r in todos if r.perfil == perfil][:args.baixar]
            escolhidos += [r.link for r in do_perfil]
        baixados = [asdict(r) for r in baixar_varios(escolhidos, args.saida,
                                                     args.cookies, args.cookies_do_navegador)]

    if todos:
        args.tsv.parent.mkdir(parents=True, exist_ok=True)
        args.tsv.write_text("\n".join(linhas_tsv(todos, medianas)) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"reels": [asdict(r) for r in todos], "medianas": medianas,
                          "erros": erros, "baixados": baixados, "tsv": str(args.tsv)},
                         ensure_ascii=False, indent=2))
    else:
        if todos:
            _imprimir(todos, medianas)
            print(f"\nTSV para o /ig-viral: {args.tsv}")
        if baixados:
            print(f"Vídeos baixados em {args.saida}")
    return 0 if todos else 1


if __name__ == "__main__":
    raise SystemExit(main())
