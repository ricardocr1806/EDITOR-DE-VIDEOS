"""Baixa vídeos do Instagram (reels, posts, IGTV e stories) para a pasta de originais.

Uso:
    python -m agente_instagram.baixar URL [URL ...]
    python -m agente_instagram.baixar --lista links.txt
    python -m agente_instagram.baixar URL --cookies-do-navegador chrome
    python -m agente_instagram.baixar URL --json     # saída para outro programa ler

Regras (mesmas da ingestão do Corte Limpo):
- O arquivo baixado nunca é sobrescrito. Se o mesmo vídeo já existe, ele é pulado.
- Cada vídeo ganha um .json ao lado com autor, legenda, link, fps, resolução e duração.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

PASTA_PADRAO = Path(__file__).resolve().parent.parent / "originais"

_PADRAO_LINK = re.compile(
    r"^https?://(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/"
    r"(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv|stories)/[^\s]+$",
    re.IGNORECASE,
)

# Trechos de erro do yt-dlp -> explicação em português e o que fazer.
_DICAS_DE_ERRO = [
    (("login", "log in", "cookies", "rate-limit", "rate limit", "not available"),
     "O Instagram pediu login para liberar esse vídeo. Rode de novo com "
     "--cookies-do-navegador chrome (ou firefox/edge/safari) com a conta logada "
     "nesse navegador, ou passe --cookies cookies.txt."),
    (("private",),
     "O perfil é privado. Só baixa com os cookies de uma conta que segue esse perfil."),
    (("no video", "there is no video", "no formats"),
     "Esse post não tem vídeo (só foto)."),
    (("404", "not found", "page isn't available", "unable to extract"),
     "Link não encontrado. O post pode ter sido apagado, ou o link está errado."),
    (("proxy", "unable to connect", "timed out", "connection"),
     "Não consegui conectar ao Instagram. Confira a internet e tente de novo."),
]


class _Silencioso:
    """Engole as mensagens do yt-dlp; os erros chegam pela exceção e são explicados aqui."""

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


@dataclass
class Resultado:
    link: str
    status: str  # "baixado" | "ja_existia" | "erro"
    arquivos: list[str] = field(default_factory=list)
    erro: str | None = None
    dica: str | None = None


def link_valido(link: str) -> bool:
    return bool(_PADRAO_LINK.match(link.strip()))


def limpar_link(link: str) -> str:
    """Tira parâmetros de rastreio (?igsh=..., ?utm_source=...) do link."""
    return link.strip().split("?", 1)[0].split("#", 1)[0]


def explicar_erro(mensagem: str) -> str:
    texto = mensagem.lower()
    for gatilhos, dica in _DICAS_DE_ERRO:
        if any(g in texto for g in gatilhos):
            return dica
    return "Erro inesperado. Confira o link e tente atualizar o yt-dlp: pip install -U yt-dlp"


def ler_lista(caminho: Path) -> list[str]:
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in linhas if l.strip() and not l.strip().startswith("#")]


def medir_video(arquivo: Path) -> dict[str, Any]:
    """Lê fps, resolução e duração com ffprobe (passo 1 do pipeline)."""
    if not shutil.which("ffprobe"):
        return {}
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,codec_name:format=duration",
        "-of", "json", str(arquivo),
    ]
    try:
        dados = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {}
    stream = (dados.get("streams") or [{}])[0]
    num, _, den = (stream.get("r_frame_rate") or "0/1").partition("/")
    fps = round(float(num) / float(den or 1), 3) if float(den or 1) else None
    duracao = dados.get("format", {}).get("duration")
    return {
        "largura": stream.get("width"),
        "altura": stream.get("height"),
        "fps": fps,
        "codec_video": stream.get("codec_name"),
        "duracao_s": round(float(duracao), 3) if duracao else None,
    }


def _opcoes_ytdlp(pasta: Path, cookies: Path | None, navegador: str | None) -> dict[str, Any]:
    opcoes: dict[str, Any] = {
        # Melhor vídeo + melhor áudio, juntos num .mp4. Prefere H.264/AAC para editar sem dor.
        "format": "bv*+ba/b",
        "format_sort": ["res", "fps", "vcodec:h264", "acodec:aac"],
        "merge_output_format": "mp4",
        "outtmpl": str(pasta / "instagram_%(uploader_id,uploader|autor)s_%(id)s.%(ext)s"),
        "restrictfilenames": True,
        "overwrites": False,
        "noplaylist": False,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "logger": _Silencioso(),
    }
    if cookies:
        opcoes["cookiefile"] = str(cookies)
    if navegador:
        opcoes["cookiesfrombrowser"] = (navegador,)
    return opcoes


def _salvar_ficha(arquivo: Path, info: dict[str, Any], link: str) -> None:
    ficha = {
        "link": link,
        "id": info.get("id"),
        "autor": info.get("uploader") or info.get("channel"),
        "perfil": info.get("uploader_id"),
        "legenda": info.get("description"),
        "data_publicacao": info.get("upload_date"),
        "curtidas": info.get("like_count"),
        "comentarios": info.get("comment_count"),
        "arquivo": arquivo.name,
        **medir_video(arquivo),
    }
    arquivo.with_suffix(".json").write_text(
        json.dumps(ficha, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def baixar_um(link: str, pasta: Path, cookies: Path | None = None,
              navegador: str | None = None, validar: bool = True) -> Resultado:
    import yt_dlp  # importado aqui para --help funcionar mesmo sem o pacote

    original = link.strip()
    link = limpar_link(original) if validar else original
    if validar and not link_valido(link):
        return Resultado(original, "erro", erro="Não é um link de post, reel, IGTV ou story do Instagram.",
                         dica="Copie o link pelo botão Compartilhar > Copiar link no Instagram.")

    pasta.mkdir(parents=True, exist_ok=True)
    resultado = Resultado(link, "ja_existia")
    try:
        with yt_dlp.YoutubeDL(_opcoes_ytdlp(pasta, cookies, navegador)) as ydl:
            info = ydl.extract_info(link, download=False)
            # Post carrossel vira uma lista; cada vídeo dele é baixado separado.
            entradas = [e for e in (info.get("entries") or [info]) if e]
            if not entradas:
                raise yt_dlp.utils.DownloadError("There is no video in this post")
            for entrada in entradas:
                destino = Path(ydl.prepare_filename(entrada)).with_suffix(".mp4")
                if destino.exists():
                    resultado.arquivos.append(str(destino))
                    continue
                final = ydl.process_ie_result(entrada, download=True)
                baixado = Path(final.get("filepath") or destino)
                if not baixado.exists():
                    baixado = destino
                _salvar_ficha(baixado, final, link)
                resultado.arquivos.append(str(baixado))
                resultado.status = "baixado"
    except Exception as exc:  # yt-dlp levanta vários tipos; todos viram erro explicado
        mensagem = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).replace("ERROR: ", "")
        mensagem = mensagem.split("; please report this issue", 1)[0].strip()
        return Resultado(link, "erro", arquivos=resultado.arquivos,
                         erro=mensagem, dica=explicar_erro(mensagem))
    return resultado


def baixar_varios(links: Iterable[str], pasta: Path, cookies: Path | None = None,
                  navegador: str | None = None) -> list[Resultado]:
    vistos: set[str] = set()
    resultados = []
    for link in links:
        chave = limpar_link(link)
        if chave in vistos:
            continue
        vistos.add(chave)
        resultados.append(baixar_um(link, pasta, cookies, navegador))
    return resultados


def _imprimir_resumo(resultados: list[Resultado]) -> None:
    icones = {"baixado": "OK ", "ja_existia": "== ", "erro": "XX "}
    for r in resultados:
        print(f"{icones[r.status]}{r.link}")
        for a in r.arquivos:
            print(f"     -> {a}")
        if r.erro:
            print(f"     erro: {r.erro}")
            print(f"     o que fazer: {r.dica}")
    contagem = {s: sum(r.status == s for r in resultados) for s in icones}
    print(f"\n{contagem['baixado']} baixado(s), {contagem['ja_existia']} já existia(m), "
          f"{contagem['erro']} com erro.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m agente_instagram.baixar",
        description="Baixa vídeos do Instagram para a pasta de originais.",
    )
    p.add_argument("links", nargs="*", help="links de reel, post, IGTV ou story")
    p.add_argument("--lista", type=Path, help="arquivo .txt com um link por linha")
    p.add_argument("--saida", type=Path, default=PASTA_PADRAO,
                   help=f"pasta de destino (padrão: {PASTA_PADRAO})")
    p.add_argument("--cookies", type=Path, help="arquivo cookies.txt de uma conta logada")
    p.add_argument("--cookies-do-navegador", metavar="NAVEGADOR",
                   help="usa o login do navegador: chrome, firefox, edge, safari, brave...")
    p.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    args = p.parse_args(argv)

    links = list(args.links)
    if args.lista:
        links += ler_lista(args.lista)
    if not links:
        p.error("passe pelo menos um link ou --lista arquivo.txt")

    resultados = baixar_varios(links, args.saida, args.cookies, args.cookies_do_navegador)
    if args.json:
        print(json.dumps([asdict(r) for r in resultados], ensure_ascii=False, indent=2))
    else:
        _imprimir_resumo(resultados)
    return 1 if any(r.status == "erro" for r in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
