# Corte Limpo — instruções para o Claude

O usuário costuma pedir pelo celular, numa sessão na nuvem. Ele não usa Terminal: faça tudo e responda só com o resultado.

## Baixar vídeos do Instagram

Quando o usuário mandar links do Instagram ou pedir para baixar vídeos de lá:

1. `pip install -r requirements.txt` se o yt-dlp faltar.
2. Baixe com `python -m agente_instagram.baixar --json --saida originais "LINK1" "LINK2" ...`
   (o script já pede H.264, converte VP9/AV1 e separa post que é só foto com música).
3. Confira cada .mp4 com ffprobe: o vídeo tem que ser `h264`.
4. Entregue cada vídeo ao usuário com a ferramenta SendUserFile (status "normal"), para ele salvar
   direto no celular. Arquivo acima de ~15 MB: avise e mande mesmo assim.
5. Se o erro for de conexão/proxy (403 ao acessar instagram.com), a rede do ambiente bloqueia o Instagram:
   diga ao usuário para liberar `instagram.com`, `*.instagram.com`, `*.cdninstagram.com` e `*.fbcdn.net`
   em Network access do ambiente (ou escolher acesso total) e abrir uma sessão nova.
6. Se o Instagram pedir login (comum em servidor na nuvem), explique e peça um `cookies.txt` exportado
   do navegador; use `--cookies cookies.txt` e nunca faça commit desse arquivo.
