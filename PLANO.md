# Corte Limpo — plano de construção

Protótipo da interface: `prototipo/interface.html` (aprovar antes de codar o resto).

## 1. Pipeline de edição (núcleo)
1. **Ingestão** — copia o bruto para `/originais`, nunca sobrescreve. Lê fps, resolução, duração.
2. **Transcrição** — Whisper com timestamps por palavra (via Codex do usuário).
3. **Análise semântica** — marca erros, recomeços, frases abandonadas, palavras soltas,
   ideias repetidas e duas conclusões com o mesmo sentido.
4. **Onset/offset real** — RMS + detecção de fonação na forma de onda para achar o começo e o
   fim audíveis de cada palavra. O timestamp da transcrição nunca é o ponto de corte.
5. **Montagem dos cortes** — saída 0,12–0,18 s depois do fim da fonação, entrada no onset real.
   Começo do vídeo sem silêncio e com o primeiro fonema inteiro; fim com cauda de ~0,15 s.
6. **Legendas** — eventos de 1–3 palavras (~18 caracteres), reindexados depois de cada corte,
   renderizados em ASS com contorno por letra, sem sombra e sem caixa.
7. **Rosto** — detecção e tracking ao longo da timeline; se o rosto entra na faixa da legenda,
   o evento inteiro é reposicionado para a área livre mais próxima.
8. **Enquadramento** — crop 1080×1920 na resolução original, ~18% de aproximação, baseado nos olhos.
9. **Áudio** — normalização -14 LUFS, true peak ≤ -1,5 dBTP, música só sob pedido, com ducking.
10. **Checklist** — 13 itens verificados antes de exportar; falhou, volta para o passo 5.
11. **Export** — `/editados/NOME_DO_ARQUIVO_EDITADO.mp4`.

## 2. Níveis
- **Simples** — cortes + legendas (+ headline opcional).
- **Médio** — imagens entrando no momento da fala.
- **Hard** — tela dividida por assunto, com material enviado pelo usuário.

## 3. Recursos da interface
- Conexão do Codex em um único campo, com teste de conexão.
- 4 estilos de legenda pré-visualizados no quadro real.
- Campo de falas de destaque (nunca cortadas, viram gancho de imagem/tela dividida).
- Imagens: upload ou pedido ao app, com o instante de entrada preso à fala.
- Hook lido do próprio vídeo + headline escrita pelo app ou pelo usuário.
- Prévia de 10–15 s obrigatória antes do vídeo cheio.
- Memória de aprovações e rejeições, separada por atributo.
- Registro de custo por vídeo (tokens, transcrição, render, armazenamento, revisões).

## 4. Stack proposta
- Python + FFmpeg para corte, crop, legendas e mixagem.
- `librosa`/`numpy` para forma de onda e onsets; MediaPipe para rosto.
- Interface web local (o HTML do protótipo vira o front) com backend FastAPI.
