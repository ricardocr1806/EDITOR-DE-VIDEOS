# Corte Limpo

Editor de vídeos curtos. Plano em [`PLANO.md`](PLANO.md), protótipo da interface em `prototipo/interface.html`.

## Agente que baixa vídeos do Instagram

Baixa reels, posts (inclusive carrossel), IGTV e stories para `originais/`, já em `.mp4`
(melhor vídeo + melhor áudio, H.264/AAC sempre que existir). Ao lado de cada vídeo grava um
`.json` com autor, legenda, link, data, resolução, fps e duração.

**Sem a logo do Instagram:** o agente pega o arquivo original que o Instagram guarda no servidor,
não o "Baixar" do app (é esse botão que carimba a logo e o @ no vídeo). Logo que já estava
gravada na imagem pelo próprio autor continua no vídeo.

**Sempre abre no Mac:** o Instagram às vezes entrega VP9/AV1, que o QuickTime toca só com áudio.
O agente pede H.264 + AAC primeiro, confere cada arquivo com `ffprobe` e converte o que vier diferente.
Para consertar uma pasta de vídeos já baixados: `python -m agente_instagram.baixar --consertar "PASTA"`.

### No Mac, sem instalar o projeto

`mac/Baixar-Videos-IG.command` é o mesmo agente num arquivo só. Ele instala o que faltar
(Homebrew, yt-dlp, ffmpeg), conserta os vídeos que já estão em `~/Downloads/Vídeos IG`, pede os links,
baixa, converte o que não abrir e mostra um resumo no final.

```bash
bash ~/Downloads/Baixar-Videos-IG.command
```

### Instalar

```bash
pip install -r requirements.txt
```

Precisa do `ffmpeg` instalado (para juntar vídeo e áudio e medir o arquivo).

### Pelo Claude Code

O agente está em `.claude/agents/baixador-instagram.md`. Com o Claude Code aberto nesta pasta,
basta colar os links: "baixa esses reels: https://www.instagram.com/reel/...".
Ele roda o script, pede o navegador quando o Instagram exigir login e devolve o caminho de cada vídeo.

### Pelo terminal

```bash
python -m agente_instagram.baixar https://www.instagram.com/reel/XXXXXXXX/
```

```bash
python -m agente_instagram.baixar --lista links.txt
```

Stories, perfis privados (que você segue) ou quando o Instagram pedir login:

```bash
python -m agente_instagram.baixar URL --cookies-do-navegador chrome
```

| Opção | O que faz |
|---|---|
| `--lista arquivo.txt` | um link por linha; linhas com `#` são ignoradas |
| `--saida PASTA` | muda a pasta de destino (padrão `originais/`) |
| `--cookies cookies.txt` | usa um arquivo de cookies exportado do navegador |
| `--cookies-do-navegador NOME` | usa o login do chrome, firefox, edge, safari, brave... |
| `--json` | saída em JSON (usada pelo agente) |

O mesmo vídeo nunca é baixado duas vezes nem sobrescrito: o nome do arquivo é
`instagram_<perfil>_<id>.mp4`, e se ele já existe o link é pulado.

Baixe só vídeos seus ou que você tem permissão de usar.

### Testes

```bash
python -m unittest discover tests
```
