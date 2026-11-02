"""Baixa vídeos do Instagram (reels, posts, IGTV e stories) para a pasta de originais.

Uso:
    python -m agente_instagram.baixar URL [URL ...]
    python -m agente_instagram.baixar --lista links.txt
    python -m agente_instagram.baixar URL --cookies-do-navegador chrome
    python -m agente_instagram.baixar URL --json     # saída para outro programa ler

    python -m agente_instagram.baixar --consertar "PASTA"  # conserta .mp4 que não abrem

Regras (mesmas da ingestão do Corte Limpo):
- O arquivo baixado nunca é sobrescrito. Se o mesmo vídeo já existe, ele é pulado.
- Todo vídeo sai em H.264 + AAC, que abre em qualquer player (QuickTime, iPhone, Windows,
  editores). O Instagram às vezes entrega VP9/AV1: aí o QuickTime toca só o áudio. O agente
  confere cada arquivo com ffprobe e converte o que não estiver em H.264.
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
    status: str  # "baixado" | "ja_existia" | "consertado" | "erro"
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


class SemVideo(Exception):
    """O arquivo não tem faixa de vídeo (post de foto com música, ou download incompleto)."""


def inspecionar(arquivo: Path) -> dict[str, str | None]:
    """Codec de vídeo, formato de pixel e codec de áudio do arquivo."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,pix_fmt",
           "-of", "json", str(arquivo)]
    try:
        dados = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {"video": None, "pix_fmt": None, "audio": None}
    streams = dados.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and s.get("codec_name") not in ("mjpeg", "png")), {})  # capa embutida não conta
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {"video": video.get("codec_name"), "pix_fmt": video.get("pix_fmt"),
            "audio": audio.get("codec_name")}


def abre_em_qualquer_lugar(info: dict[str, str | None]) -> bool:
    return (info["video"] == "h264" and info["pix_fmt"] in ("yuv420p", "yuvj420p")
            and info["audio"] in (None, "aac"))


def garantir_compativel(arquivo: Path) -> bool:
    """Deixa o .mp4 em H.264 + AAC. Devolve True se precisou converter.

    Converte para um arquivo temporário, confere o resultado e só então troca o original.
    Levanta SemVideo se o arquivo não tiver imagem.
    """
    info = inspecionar(arquivo)
    if not info["video"]:
        raise SemVideo(f"{arquivo.name} não tem vídeo, só áudio")
    if abre_em_qualquer_lugar(info):
        return False
    video_ok = info["video"] == "h264" and info["pix_fmt"] in ("yuv420p", "yuvj420p")
    temp = arquivo.with_name(arquivo.stem + ".convertendo.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(arquivo), "-map", "0:v:0", "-map", "0:a:0?"]
    cmd += (["-c:v", "copy"] if video_ok else
            ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"])
    cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(temp)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        if not abre_em_qualquer_lugar(inspecionar(temp)):
            raise RuntimeError(f"a conversão de {arquivo.name} não ficou em H.264")
    except subprocess.CalledProcessError as exc:
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg não conseguiu converter {arquivo.name}: {exc.stderr.strip()}")
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    temp.replace(arquivo)
    return True


def _opcoes_ytdlp(pasta: Path, cookies: Path | None, navegador: str | None) -> dict[str, Any]:
    opcoes: dict[str, Any] = {
        # H.264 + AAC primeiro (abre em qualquer lugar); só cai para outro codec se não houver,
        # e nesse caso garantir_compativel() converte depois.
        "format": "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[vcodec^=avc1]/bv*+ba/b",
        "format_sort": ["vcodec:h264", "res", "fps", "acodec:aac"],
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


def _salvar_ficha(arquivo: Path, info: dict[str, Any], link: str, convertido: bool) -> None:
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
        "convertido_para_h264": convertido,
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
                    # Já baixado antes: só confere se abre (versões antigas podiam vir em VP9/AV1).
                    if garantir_compativel(destino) and resultado.status == "ja_existia":
                        resultado.status = "consertado"
                    resultado.arquivos.append(str(destino))
                    continue
                final = ydl.process_ie_result(entrada, download=True)
                baixado = Path(final.get("filepath") or destino)
                if not baixado.exists():
                    baixado = destino
                try:
                    convertido = garantir_compativel(baixado)
                except SemVideo:
                    baixado.unlink(missing_ok=True)
                    raise
                _salvar_ficha(baixado, final, link, convertido)
                resultado.arquivos.append(str(baixado))
                resultado.status = "baixado"
    except SemVideo:
        return Resultado(link, "erro", arquivos=resultado.arquivos,
                         erro="O arquivo veio só com áudio.",
                         dica="Esse post provavelmente é foto (ou carrossel de fotos) com música, "
                              "não um vídeo. Abra o link no Instagram para conferir.")
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


def consertar_pasta(pasta: Path) -> list[Resultado]:
    """Confere todos os .mp4 de uma pasta e converte para H.264 os que não abrem."""
    resultados = []
    for arquivo in sorted(pasta.glob("*.mp4")):
        if arquivo.name.endswith(".convertendo.mp4"):
            continue
        try:
            status = "consertado" if garantir_compativel(arquivo) else "ja_existia"
            resultados.append(Resultado(str(arquivo), status, arquivos=[str(arquivo)]))
        except SemVideo:
            resultados.append(Resultado(str(arquivo), "erro", erro="Arquivo só com áudio.",
                                        dica="Baixe de novo pelo link; se repetir, o post é foto com música."))
        except Exception as exc:
            resultados.append(Resultado(str(arquivo), "erro", erro=str(exc),
                                        dica="Apague esse arquivo e baixe de novo pelo link."))
    return resultados


def _imprimir_resumo(resultados: list[Resultado]) -> None:
    icones = {"baixado": "OK ", "consertado": "FIX", "ja_existia": "== ", "erro": "XX "}
    for r in resultados:
        print(f"{icones[r.status]}{r.link}")
        for a in r.arquivos:
            print(f"     -> {a}")
        if r.erro:
            print(f"     erro: {r.erro}")
            print(f"     o que fazer: {r.dica}")
    contagem = {s: sum(r.status == s for r in resultados) for s in icones}
    print(f"\n{contagem['baixado']} baixado(s), {contagem['consertado']} consertado(s), "
          f"{contagem['ja_existia']} já ok, {contagem['erro']} com erro.")


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
    p.add_argument("--consertar", type=Path, metavar="PASTA",
                   help="confere os .mp4 da pasta e converte para H.264 os que não abrem")
    p.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    args = p.parse_args(argv)

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        p.error("o ffmpeg não está instalado (Mac: brew install ffmpeg)")

    if args.consertar:
        resultados = consertar_pasta(args.consertar)
        if args.json:
            print(json.dumps([asdict(r) for r in resultados], ensure_ascii=False, indent=2))
        else:
            _imprimir_resumo(resultados)
        return 1 if any(r.status == "erro" for r in resultados) else 0

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
