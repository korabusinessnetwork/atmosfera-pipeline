# Fórmula — ritmo e montagem a partir do áudio

**Origem:** análise do vídeo `youtu.be/WVT2FCjhDDY` — *"How To Create Viral
YouTube Videos From Scratch With FREE AI Tools"* — pedida pelo dono em 2026-08-05.
Documento de referência, no molde de `docs/hook-playbook.md`: alimenta um `/spec`
futuro, não é a spec.

## 0. Honestidade sobre a fonte

**Não consegui assistir ao vídeo.** A política de egresso desta sessão bloqueia
`youtube.com` (403 no CONNECT do proxy), e os espelhos de transcrição
(`glasp.co`, `youtubetotranscript.com`) caem no mesmo bloqueio. O método abaixo
foi reconstruído a partir de resumos indexados do vídeo, que batem entre si em
todos os cinco passos e nos nomes de ferramenta.

Consequência prática: **os cinco passos são confiáveis; frases exatas, números e
prompts ditos na tela, não.** Nada nesta fórmula depende de um número que teria
vindo do vídeo — tudo que é numérico aqui saiu do nosso código. Se o dono quiser
o texto literal, é assistir e me passar os trechos.

## 1. O método do vídeo

| # | Passo | Ferramenta |
|---|-------|-----------|
| 1 | Escrever o roteiro | Claude, plano grátis |
| 2 | **Gerar a locução primeiro** | ElevenLabs, tier grátis |
| 3 | Marcar os timestamps da locução | FoziScribe AI |
| 4 | Gerar as cenas em lote | Google Flow + extensão Zappy Flow |
| 5 | **As pausas naturais da locução ditam as trocas de cena** | montagem |

Os passos 2 e 5 são a tese; 1, 3 e 4 são encanamento a serviço dela.

## 2. Triagem contra o que já existe

Antes de importar qualquer coisa: a maior parte deste vídeo o pipeline já faz
melhor. O valor está em não copiar o que já ganhamos.

| Passo do vídeo | Atmosfera hoje | Veredito |
|---|---|---|
| 1 · roteiro no Claude | `pauta_local.py`: 18 exemplos-ouro, régua de 8 dimensões, best-of-N, juiz, reescrita, e few-shot dos hooks de **retenção real** (R13) | **Já ganhamos.** Copiar nada. |
| 2 · locução ElevenLabs | edge-tts dentro do MPT, grátis, já no loop | Equivalente e já automático. ElevenLabs pago viola "auto só gratuito/local". |
| 3 · timestamps FoziScribe | **nada** | É a lacuna — mas não precisamos do FoziScribe (§ 4). |
| 4 · cenas no Google Flow | footage `local` ou `pexels` (R6) | Extensão de Chrome tocada à mão não roda headless num loop de 3 vídeos/dia. Descartar. |
| 5 · corte na pausa | `video_clip_duration: 4` — metrônomo fixo | **O prêmio.** |

## 3. A lacuna, medida no nosso código

`worker/mpt.py:180` manda `"video_clip_duration": 4` — cravado. O MPT troca de
plano a cada 4 segundos, do primeiro ao último, independentemente do que a
narração está fazendo.

Do outro lado, `montar_prompt` (`worker/pauta_local.py:419`) exige do roteiro:
**5 linhas sequenciais, 8 a 12 segundos no total**.

Junte os dois: um vídeo de 10s recebe ~2 trocas de plano para carregar **5 batidas
retóricas**. Os cortes caem no meio das frases. A imagem muda enquanto um
pensamento ainda está terminando, e não muda quando ele aterrissa.

É uma incoerência interna, não uma questão de gosto: gastamos uma rodada inteira
(R7 + hook playbook) engenheirando o texto **linha a linha**, e a montagem é surda
a essa estrutura. O corte não sabe que existe uma linha 3.

## 4. O que o vídeo ensina e o que ele custa caro à toa

A tese — **o áudio é a espinha, o corte é derivado dele** — é boa e é
exatamente a que falta aqui.

A implementação dele é que não serve: ele **paga uma SaaS (FoziScribe) para
descobrir onde estão as pausas**. Nós já temos isso instalado. O `ffmpeg` está
cabeado em `worker/postprocess.py` desde a Sprint 3 (`FFMPEG_BIN`/`FFPROBE_BIN`,
validados na largada), e o filtro `silencedetect` devolve início e fim de cada
silêncio de uma faixa de áudio — de graça, offline, sem chave, sem dependência
nova no caminho do render.

> A metade difícil do vídeo (achar as pausas) é a metade que já é nossa.
> O que falta é **usar** a lista de pausas.

## 5. A fórmula

```
áudio primeiro  →  pausa = corte  →  1 batida = 1 plano  →  a retenção julga
```

Quatro movimentos, em ordem de dependência. Cada um só começa quando o anterior
deu número.

### M1 — Ouvir o próprio render (barato, não muda nada)

Rodar `silencedetect` sobre o áudio do mp4 que o MPT já entregou, dentro do
`postprocess`, e **só registrar**: a lista de pausas, a grade de cortes de 4s, e
um número — a distância média entre cada corte e a pausa mais próxima.

Nada muda de comportamento. O que se ganha é transformar "acho que os cortes
estão desalinhados" em um número medido, com o custo de algumas linhas num
módulo que já é nosso. É a regra da casa: medir antes de mexer.

**Só isso já vale a rodada.** Se o desalinhamento médio for pequeno, M2 e M3
morrem aqui e economizamos o trabalho.

> **Implementado** — `worker/ritmo.py`, spec em `specs/ritmo-medir-desalinhamento.md`.
>
> Uma coisa que o M1 já ensinou antes mesmo de rodar em vídeo real: o MPT mistura
> **trilha sonora contínua** (`mpt.py:184`, `bgm_volume: 0.15`), então na pausa o
> nível não cai a zero — cai até o piso da música. Medido em bancada, esse piso
> ficou a **4,5 dB** do limiar de detecção. Passou, mas por pouco.
>
> Isso tem consequência para o **M3**: se a narração for gerada isolada (`/audio`),
> ela vem sem trilha e o problema evapora — mais um argumento a favor de gerar o
> áudio antes, além do alinhamento. E tem consequência para o **M2**: mexer no
> `bgm_volume` é uma alavanca barata que ninguém tinha considerado.

### M2 — Afinar o metrônomo (barato, reversível)

Parar de cravar `4` e derivar: `duração estimada ÷ nº de linhas do roteiro`.
Cinco linhas em 10s dão **2s por plano**, não 4 — uma troca de plano por batida
retórica, que é o que o roteiro já promete.

Uma função pura em `mpt.py` e uma variável no `.env`. O corte continua numa
grade, mas numa grade com o **período** certo.

**Limite honesto:** alinha a *frequência*, não a *fase*. Os cortes passam a ser
tantos quanto as linhas, mas ainda não caem onde as linhas terminam.

### M3 — Áudio primeiro de verdade (a mudança estrutural)

A tese do vídeo, aplicada:

1. gerar **só a narração**, antes do vídeo;
2. `silencedetect` nela → a lista de cortes de verdade;
3. montar sobre essa lista.

O § 5 do documento mestre lista `POST /api/v1/audio` entre os endpoints "etapas
isoladas — não usamos, o Cowork já escreve o roteiro". Esse motivo justifica
dispensar `/scripts`; **não** justifica dispensar `/audio`. É o endpoint que essa
tese pede.

**A bifurcação que precisa ser decidida, não escondida:** o MPT aceita um escalar
`video_clip_duration`, não uma lista de cortes. Então M3 termina em (a) o MPT
aceitar tempo por cena — desconhecido, **verificar no `/openapi.json` antes**,
que é a regra que o próprio § 5 escreveu ("confirme os endpoints reais no
`/docs` — não confie em memória") — ou (b) a montagem passar a ser nossa, em
ffmpeg, a partir dos clipes + narração.

(b) é trabalho real e move uma responsabilidade do MPT para cá. O músculo existe
— o `postprocess` já opera um filtergraph de cinco estágios com ordem causal
justificada — mas é uma rodada inteira, não um ajuste. **Não começar M3 antes de
M1 dar o número.**

### M4 — Deixar a retenção julgar

Temos o que o autor do vídeo não tem: `metricas.retencao_media_pct` (R11), já
consumida pelo relatório (R12) e pelo gerador (R13). Então isto não precisa ser
acreditado — pode ser testado. Publicar um lote com a cadência atual e um com a
alinhada, comparar retenção.

**Ressalva que fica escrita:** a 3 vídeos/dia a amostra leva semanas, e a
retenção também se move com o hook — o confundimento é real e não some com boa
vontade. É justamente por isso que o número do M1 importa: é o indicador que se
lê **hoje**, enquanto a retenção não chega.

## 6. O que NÃO importar, e por quê

- **ElevenLabs pago** — viola "o auto só usa sistemas gratuitos/locais" (decisão
  do dono, 2026-08-04). E a voz própria já está enfileirada no backlog como voice
  clone **local** (XTTS/Coqui). O passo 2 do vídeo já tem resposta nossa.
- **Google Flow + Zappy Flow** — extensão de navegador operada à mão. Não roda
  headless, não cabe num loop diário, e `pexels` (R6) já resolve variedade de
  footage a custo zero.
- **FoziScribe** — pagar/depender de SaaS para o que o `silencedetect` faz
  offline, e ainda plantar uma dependência de rede no caminho do render.
- **"Pesquisar tópicos virais, otimizar título e tags"** — é a camada de pauta,
  que já existe com `titulo`, `descricao` e `hashtags`.

## 7. Onde isto encosta na arquitetura

Em nada do contrato. M1 e M2 são internos ao worker; M3 muda **quem** monta, e
segue dentro do worker, entregando o mesmo `pauta → mp4`. Sem estado novo, sem
migration, sem tocar RLS, e o gate humano continua sendo o gate.

Que a tese do vídeo caiba inteira dentro de uma fronteira de módulo é a melhor
notícia desta análise — e é consequência da divisão que a Sprint 2 já tinha feito.

## 8. Achado de passagem (não é do vídeo)

`worker/config.py:313` tem `MPT_VOZ` com padrão **`pt-BR-AntonioNeural-Male`**,
enquanto `mpt_video_language` na linha 316 tem padrão `en-US` e o canal virou
en-US na R5. O `worker/.env.example:39` está certo (`en-US-GuyNeural-Male`), então
quem tem `.env` configurado não é afetado — mas **quem rodar sem `MPT_VOZ`
definido narra um roteiro em inglês com voz brasileira**, e o único sintoma é o
vídeo pronto soando errado. Padrão que envelheceu na R5 e ficou. Correção de uma
linha, fora do escopo desta análise.
