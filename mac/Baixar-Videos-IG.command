#!/bin/bash
# Agente de download do Instagram para Mac.
#
#   bash ~/Downloads/Baixar-Videos-IG.command            -> conserta a pasta e pede os links
#   bash ~/Downloads/Baixar-Videos-IG.command LINK LINK  -> conserta a pasta e baixa esses links
#
# Garante que todo vídeo abre no Mac: baixa em H.264 + AAC quando o Instagram oferece e,
# se vier em VP9/AV1 (o QuickTime toca só o áudio desses), converte para H.264.
# Salva em ~/Downloads/Vídeos IG (mude com a variável PASTA_IG).

PASTA="${PASTA_IG:-$HOME/Downloads/Vídeos IG}"
SEM_IMAGEM="$PASTA/_sem imagem (só áudio)"
EXTRA_YTDLP=()          # usado só nos testes
[ -n "$YTDLP_EXTRA" ] && EXTRA_YTDLP=($YTDLP_EXTRA)

OK=0; CONVERTIDOS=0
PROBLEMAS=()

# ---------------------------------------------------------------- ferramentas
preparar() {
  echo "== Conferindo as ferramentas =="
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && eval "$("$b" shellenv)"
  done
  if ! command -v brew >/dev/null 2>&1; then
    echo "Instalando o Homebrew (vai pedir a senha do Mac)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      [ -x "$b" ] && eval "$("$b" shellenv)"
    done
  fi
  if ! command -v yt-dlp >/dev/null 2>&1; then
    echo "Se perguntar [y/n], aperte só a tecla y."
    brew install yt-dlp
  else
    # O Instagram muda o site com frequência; yt-dlp desatualizado é a causa nº 1 de erro.
    brew upgrade yt-dlp >/dev/null 2>&1
  fi
  if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "Se perguntar [y/n], aperte só a tecla y."
    brew install ffmpeg
  fi
  for f in yt-dlp ffmpeg ffprobe; do
    command -v "$f" >/dev/null 2>&1 || { echo "ERRO: $f não instalou. Me mande um print disto."; exit 1; }
  done
}

# ---------------------------------------------------------------- conferência
campo() {  # campo ARQUIVO STREAM ENTRADA -> valor
  ffprobe -v error -select_streams "$2" -show_entries "stream=$3" \
    -of default=noprint_wrappers=1:nokey=1 "$1" 2>/dev/null | head -n 1
}

abre_no_mac() {  # 0 se H.264 yuv420p + AAC (ou sem áudio)
  local v pix a
  v=$(campo "$1" V:0 codec_name); pix=$(campo "$1" V:0 pix_fmt); a=$(campo "$1" a:0 codec_name)
  [ "$v" = h264 ] && { [ "$pix" = yuv420p ] || [ "$pix" = yuvj420p ]; } && { [ -z "$a" ] || [ "$a" = aac ]; }
}

# garantir ARQUIVO -> 0 já abria, 3 convertido, 2 sem imagem, 1 falhou
garantir() {
  local f="$1" v pix tmp
  v=$(campo "$f" V:0 codec_name)
  [ -z "$v" ] && return 2
  abre_no_mac "$f" && return 0
  pix=$(campo "$f" V:0 pix_fmt)
  tmp="${f%.*}.convertendo.mp4"
  echo "   convertendo $(basename "$f") de ${v} para H.264..."
  if [ "$v" = h264 ] && { [ "$pix" = yuv420p ] || [ "$pix" = yuvj420p ]; }; then
    vopts=(-c:v copy)
  else
    vopts=(-c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p)
  fi
  if ffmpeg -nostdin -y -v error -i "$f" -map 0:V:0 -map '0:a:0?' "${vopts[@]}" \
       -c:a aac -b:a 192k -movflags +faststart "$tmp" && abre_no_mac "$tmp"; then
    mv -f "$tmp" "$f"
    return 3
  fi
  rm -f "$tmp"
  return 1
}

# trata o resultado de garantir() para um arquivo
avaliar() {
  local f="$1" origem="$2"
  garantir "$f"
  case $? in
    0) OK=$((OK + 1)) ;;
    3) OK=$((OK + 1)); CONVERTIDOS=$((CONVERTIDOS + 1)) ;;
    2) mkdir -p "$SEM_IMAGEM"; mv -f "$f" "$SEM_IMAGEM/"
       PROBLEMAS+=("só áudio, sem imagem (provavelmente é foto com música): ${origem:-$(basename "$f")}") ;;
    *) PROBLEMAS+=("não consegui converter: $(basename "$f")") ;;
  esac
}

consertar_pasta() {
  local f achou=0
  for f in "$PASTA"/*.mp4; do
    [ -e "$f" ] || continue
    case "$f" in *.convertendo.mp4) rm -f "$f"; continue ;; esac
    if [ $achou -eq 0 ]; then echo; echo "== Conferindo os vídeos que já estão na pasta =="; achou=1; fi
    avaliar "$f" ""
  done
}

# ---------------------------------------------------------------- download
baixar_link() {  # baixar_link LINK [args extras do yt-dlp...] ; grava os caminhos em $LISTA
  local link="$1"; shift
  yt-dlp --no-overwrites --restrict-filenames \
    -f "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/b[vcodec^=avc1]/bv*+ba/b" \
    -S "vcodec:h264,res,fps,acodec:aac" --merge-output-format mp4 \
    -o "%(uploader_id,uploader|autor)s_%(id)s.%(ext)s" \
    --print-to-file after_move:filepath "$LISTA" \
    "${EXTRA_YTDLP[@]}" "$@" "$link"
}

baixar_todos() {
  local link nav ok
  LISTA=$(mktemp)
  echo; echo "== Baixando ${#LINKS[@]} link(s) =="
  for link in "${LINKS[@]}"; do
    echo; echo "-> $link"
    : > "$LISTA"
    ok=0
    if baixar_link "$link"; then
      ok=1
    else
      for nav in chrome safari firefox brave edge; do
        echo "   tentando com o login do Instagram do $nav..."
        if baixar_link "$link" --cookies-from-browser "$nav" 2>/dev/null; then ok=1; break; fi
      done
    fi
    if [ $ok -eq 0 ]; then
      PROBLEMAS+=("não baixou (post apagado, privado ou sem vídeo): $link")
      continue
    fi
    while IFS= read -r f; do
      [ -f "$f" ] && avaliar "$f" "$link"
    done < "$LISTA"
  done
  rm -f "$LISTA"
}

ler_links() {
  local linha w
  LINKS=()
  if [ $# -gt 0 ]; then
    for w in "$@"; do case "$w" in http*) LINKS+=("$w") ;; esac; done
    return
  fi
  echo
  echo "Cole os links do Instagram (pode colar vários de uma vez)."
  echo "Quando terminar, aperte Enter numa linha vazia:"
  while IFS= read -r linha; do
    [ -z "$linha" ] && break
    for w in $linha; do case "$w" in http*) LINKS+=("$w") ;; esac; done
  done
}

main() {
  preparar
  mkdir -p "$PASTA"
  cd "$PASTA" || exit 1
  consertar_pasta
  ler_links "$@"
  [ ${#LINKS[@]} -gt 0 ] && baixar_todos

  echo
  echo "======================================"
  echo "Pronto. Pasta: $PASTA"
  echo "Vídeos que abrem no Mac: $OK  (convertidos para H.264 agora: $CONVERTIDOS)"
  if [ ${#PROBLEMAS[@]} -gt 0 ]; then
    echo "Atenção:"
    printf '  - %s\n' "${PROBLEMAS[@]}"
  fi
  echo "======================================"
  command -v open >/dev/null 2>&1 && open "$PASTA"
}

[ "${BASH_SOURCE[0]}" = "$0" ] && main "$@"
