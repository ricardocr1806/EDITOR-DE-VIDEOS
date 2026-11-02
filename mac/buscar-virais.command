#!/bin/bash
# Busca, no Mac, os reels mais vistos de páginas de política do Instagram e devolve só os links.
#
#   bash ~/Downloads/buscar-virais.command                 -> páginas padrão, 40 links
#   bash ~/Downloads/buscar-virais.command pagina1 pagina2 -> só essas páginas
#   QUANTOS=20 DIAS=3 bash ~/Downloads/buscar-virais.command
#
# Usa o login do Instagram exportado do navegador com a extensão "Get cookies.txt LOCALLY"
# (arquivo ~/Downloads/www.instagram.com_cookies.txt). Só lê: não baixa, não curte, não segue.
# Vai devagar (pausa entre páginas) e para na hora se o Instagram reclamar.
# Salva a lista em ~/Downloads/links-virais.txt e já deixa copiada para colar no Claude.

COOKIES="${COOKIES_IG:-$HOME/Downloads/www.instagram.com_cookies.txt}"
SAIDA="$HOME/Downloads/links-virais.txt"
export QUANTOS="${QUANTOS:-40}" DIAS="${DIAS:-7}"

if [ "$#" -gt 0 ]; then
  PAGINAS=("$@")
else
  PAGINAS=(conexaopoliticabrasil metropolespolitica cnnpolitica rankingdospoliticos uolnoticias
           cnnbrasil jovempannews revistaoeste poder360 metropoles g1 estadao)
fi

if [ ! -f "$COOKIES" ]; then
  echo "Não achei $COOKIES."
  echo "Abra o instagram.com logado, clique na extensão Get cookies.txt LOCALLY e em Export."
  exit 1
fi
if ! grep -q "^\.instagram\.com.*sessionid" "$COOKIES"; then
  echo "Esse arquivo não tem o login do Instagram (talvez foi exportado na aba errada)."
  echo "Apague-o, abra a aba do instagram.com e exporte de novo."
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "Falta o python3. Rode: xcode-select --install   (e depois este script de novo)"
  exit 1
fi

python3 -I - "$COOKIES" "$SAIDA" "${PAGINAS[@]}" <<'PY'
import http.cookiejar, json, os, random, sys, time, urllib.request

cookies, saida, paginas = sys.argv[1], sys.argv[2], sys.argv[3:]
quantos, dias = int(os.environ["QUANTOS"]), int(os.environ["DIAS"])
cj = http.cookiejar.MozillaCookieJar(cookies)
cj.load(ignore_discard=True, ignore_expires=True)
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
csrf = next((c.value for c in cj if c.name == "csrftoken"), "")
H = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "X-IG-App-ID": "936619743392459",
    "X-CSRFToken": csrf,
    "Referer": "https://www.instagram.com/",
}
limite = time.time() - dias * 86400
achados, falhas = [], []
for i, u in enumerate(paginas):
    u = u.strip().lstrip("@").strip("/")
    if i:
        time.sleep(random.uniform(6, 11))
    try:
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={u}"
        user = json.load(op.open(urllib.request.Request(url, headers=H), timeout=30))["data"]["user"]
        n = 0
        for e in user["edge_owner_to_timeline_media"]["edges"]:
            p = e["node"]
            if not p.get("is_video") or p["taken_at_timestamp"] < limite:
                continue
            curt = (p.get("edge_liked_by") or p.get("edge_media_preview_like") or {}).get("count") or 0
            achados.append((p.get("video_view_count") or 0, curt, u, p["shortcode"]))
            n += 1
        print(f"  {u}: {n} vídeos dos últimos {dias} dias")
    except Exception as ex:  # noqa: BLE001
        msg = str(ex)
        print(f"  {u}: erro ({msg})")
        falhas.append(u)
        if "429" in msg or "401" in msg or "challenge" in msg.lower():
            print("\nO Instagram pediu uma pausa. Parei para não travar a conta; tente de novo em 1 hora.")
            break

achados.sort(key=lambda x: (x[0], x[1]), reverse=True)
vistos, links = set(), []
for views, curt, u, code in achados:
    if code not in vistos:
        vistos.add(code)
        links.append(f"https://www.instagram.com/p/{code}/")
links = links[:quantos]
with open(saida, "w") as f:
    f.write("\n".join(links) + ("\n" if links else ""))
print(f"\n{len(links)} links salvos em {saida}" + (f" (falharam: {', '.join(falhas)})" if falhas else ""))
PY

if [ -s "$SAIDA" ]; then
  pbcopy < "$SAIDA" 2>/dev/null && echo "A lista já está copiada: é só colar (Cmd+V) na conversa do Claude."
  echo
  cat "$SAIDA"
fi
