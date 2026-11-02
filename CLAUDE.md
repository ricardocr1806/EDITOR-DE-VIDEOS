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

## Postar no TikTok (caminho principal: Zernio, grátis até 2 contas)

Agente: `python -m agente_tiktok.zernio` — publica direto, público e com legenda, ou agenda.
Precisa de `ZERNIO_API_KEY` no ambiente (nunca peça no chat). Conta conectada: @isabeladuartesantos.

1. `contas` para conferir a conta do TikTok conectada.
2. `postar ARQUIVO --legenda "..."` publica na hora; `--agendar 2026-11-03T18:00` agenda (fuso de São Paulo).
3. Legenda: sem @ e sem nomes de pessoas (o script já remove @); hashtags podem. O vídeo pode ter nomes.
4. Confira `status_tiktok` e `link` no resultado e mande o link ao usuário. Se `erro` vier preenchido, explique.
5. Só poste vídeo que o usuário tenha direito de usar.

## Postar no TikTok pela API oficial (alternativa, só rascunho)

Agente: `python -m agente_tiktok.postar` (API oficial do TikTok; app "Postar Videos", em Sandbox).
Precisa das variáveis de ambiente `TIKTOK_CLIENT_KEY` e `TIKTOK_CLIENT_SECRET` (nunca peça no chat).

1. Primeira vez numa sessão sem token: rode `link-autorizacao`, mande o link ao usuário, peça para ele
   autorizar e colar de volta o endereço inteiro da barra (vai mostrar erro 404 — é normal). Rode
   `trocar-codigo "URL"`. Se existir `TIKTOK_REFRESH_TOKEN`, não precisa autorizar de novo.
2. Postar: `postar ARQUIVO --modo rascunho` (padrão). O rascunho chega nas notificações do TikTok e o
   usuário toca em Publicar. A API NÃO leva legenda no rascunho: escreva a legenda e mande no chat
   para ele colar. `--modo direto --legenda "..."` só funciona depois que o TikTok aprovar o app
   (Submit for review); antes disso o TikTok recusa conta pública (unaudited_client_can_only_post_to_private_accounts).
   Legenda: sem @ e sem nomes de pessoas (preferência do usuário); hashtags podem.
3. Confira o `status` no resultado: `SEND_TO_USER_INBOX` (rascunho entregue) ou `PUBLISH_COMPLETE`.
4. Só poste vídeo que seja do usuário ou que ele tenha direito de usar. Nunca imprima tokens.
