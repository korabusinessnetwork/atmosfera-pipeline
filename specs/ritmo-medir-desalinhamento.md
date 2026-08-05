# Spec — M1: medir o desalinhamento entre corte e pausa

## 1. Escopo

O primeiro movimento da fórmula de `docs/formula-ritmo-e-montagem.md`: **medir,
sem mudar nada**. Descobrir, por vídeo renderizado, o quanto os cortes do MPT
caem longe das pausas da narração — e registrar o número.

Quatro peças:

1. `worker/ritmo.py` — módulo novo: roda `silencedetect` + `volumedetect` sobre
   o áudio do mp4, parseia, e calcula o desalinhamento contra a grade de cortes.
2. Ligação em `worker/main.py::processar`, **degradável**: mede o bruto e loga.
   Nunca levanta, nunca muda o estado do vídeo.
3. CLI `uv run ritmo.py <arquivo.mp4>` para medir vídeo que já está em disco,
   sem re-renderizar.
4. `worker/tests/test_ritmo.py` — sem ffmpeg, sem rede, sem arquivo de vídeo.

## 2. Fora de escopo

- **Mudar o corte.** M2 (derivar `video_clip_duration`) e M3 (áudio primeiro)
  não são esta rodada. Se esta medida disser que o desalinhamento é pequeno,
  M2 e M3 morrem — e é para isso que ela existe.
- **Gravar métrica no banco.** Nenhuma migration, nenhuma coluna, nenhuma
  política. O número vai para o log, que é onde ele precisa estar para decidir a
  próxima rodada. Persistir antes de saber se a medida serve seria tabela nova
  para dado que talvez se prove inútil. RLS fica em **41 ✅** por construção.
- **Corrigir o `MPT_VOZ` pt-BR** (§ 8 do documento da fórmula). É bug real e é
  de uma linha, mas é outro assunto — entra sozinho, não de carona.
- **Detectar pausa sem depender do limiar** (envelope de loudness, minimos
  locais). Ver § 6: pode ser necessário, e é justamente o que a medida vai dizer.

## 3. A trilha sonora, e o que a bancada disse sobre ela

`worker/mpt.py:184-185` manda `"bgm_type": "random"` e `"bgm_volume": 0.15`. O
MPT mistura **trilha sonora contínua** por baixo da narração. Durante uma pausa
da fala o nível não cai a zero — cai até o piso da trilha. Se esse piso ficar
acima do limiar, `silencedetect` não acha pausa nenhuma, nunca.

**Previ que isso mataria a medida. Medi, e não mata — por pouco.** Ensaio com
ffmpeg 7.0.2, narração sintética com pausas em 2–3s e 6–6,5s, trilha somada a
0,15:

| Janela de pausa (2,2–2,8s) | `max_volume` |
|---|---|
| sem trilha | **−91,0 dB** |
| com trilha a 0,15 | **−34,5 dB** |

O mecanismo é real e levanta o piso em ~56 dB. Mas ficou **4,5 dB abaixo** do
limiar padrão de −30 dB, e as duas pausas foram detectadas normalmente.

O que fica, então, não é "o problema não existe" — é que a **margem é fina** e o
ensaio não é o mix real do MPT (não sei a normalização dele, nem se ele abaixa a
música sob a fala). Consequências de desenho, ambas mantidas:

1. `RITMO_RUIDO_DB` é **configurável**, porque 4,5 dB de folga é o tipo de número
   que vira zero quando o material muda.
2. `volumedetect` viaja junto de **toda** medida. Um `pausas: 0` sem o nível ao
   lado é indistinguível de bug de ffmpeg, e alguém gastaria uma tarde
   procurando defeito onde há trilha sonora.

**Honestidade que fica escrita:** isto foi medido contra áudio sintético, não
contra saída do MPT — não tenho MPT nem render real neste ambiente. O ensaio
prova o mecanismo e dimensiona a margem; não prova o comportamento no vídeo de
verdade. Quem rodar o worker com `RITMO_MEDIR=true` descobre em um vídeo.

## 4. Arquivos afetados

| Arquivo | O quê |
|---|---|
| `worker/ritmo.py` | **novo** — puras (parse + métrica) + processo (ffmpeg) + CLI |
| `worker/main.py` | **modificado** — chamada degradável em `processar` |
| `worker/config.py` | **modificado** — `RITMO_MEDIR`, `RITMO_RUIDO_DB`, `RITMO_PAUSA_MIN_SEG` |
| `worker/.env.example` | **modificado** — as três variáveis, com nota |
| `worker/tests/test_ritmo.py` | **novo** |
| `worker/tests/test_ciclo.py` e afins | **modificado** se `Config` novo quebrar montagem |

## 5. Critérios de aceite

1. `ritmo.py` separa puras de processo, no padrão do repo (`# ---- puras`).
2. `parsear_silencios` entende o formato real do `silencedetect`
   (`silence_start: X` / `silence_end: Y | silence_duration: Z`), incluindo
   silêncio que começa e **não fecha** antes do fim do arquivo.
3. `parsear_volume` extrai `mean_volume` e `max_volume`; ausência vira `None`,
   não exceção.
4. `grade_de_cortes(duracao, clip_seg)` devolve os instantes de troca de plano
   do MPT, sem o 0 e sem nada `>= duracao`.
5. `desalinhamento` devolve média, máximo e quantos cortes caem **dentro** de um
   silêncio. Com zero pausas, devolve `None` nas distâncias — e não divide por
   zero.
6. `medir()` **nunca levanta**: qualquer tropeço (ffmpeg ausente, rc≠0, vídeo sem
   faixa de áudio, saída ilegível) vira `None` + `warning`.
7. O comando do ffmpeg **não** passa `-loglevel error` (ver § 6) e usa
   `-f null -`, sem escrever arquivo.
8. `processar` chama a medida **depois** do `mpt.gerar` e **antes** do
   `descartar_bruto`, e uma exceção ali não impede o vídeo de chegar a
   `aguardando_aprovacao`.
9. `RITMO_MEDIR=false` desliga a medida inteira — nenhum processo de ffmpeg extra.
10. Suíte do worker **verde**, com os testes novos. Nenhum teste novo precisa de
    ffmpeg, rede, chave ou arquivo de vídeo.
11. Zero arquivos em `supabase/` — RLS segue **41 ✅** por construção.
12. Nenhum segredo, caminho absoluto de máquina ou URL assinada em log ou arquivo
    versionado.

## 6. Edge cases conhecidos

- **`-loglevel error` engoliria a medida.** O `silencedetect` e o `volumedetect`
  escrevem em nível **info**, no stderr. O `_rodar` do `postprocess` passa
  `-loglevel error` porque lá o stderr só interessa quando falha; aqui o stderr
  **é o resultado**. Por isso `ritmo.py` tem o próprio runner em vez de reusar o
  do `postprocess` — não é duplicação por desatenção, é requisito oposto.
- **Trilha sonora mascarando a pausa** (§ 3). Esperado. A medida reporta e segue.
- **Vídeo sem faixa de áudio** — `-map 0:a:0` falha, `rc≠0`, vira `None`.
- **Vídeo mais curto que um clipe** — grade vazia, nada a alinhar, sem erro.
- **Silêncio que não fecha** — o `silencedetect` emite `silence_start` sem o
  `silence_end` quando o arquivo acaba em silêncio; fechamos na duração.
- **Locale decimal** — o ffmpeg emite ponto; o parse não depende de `locale`.
- **Custo.** Uma passada de decode a mais por vídeo. Num mp4 de ~10s é
  desprezível perto dos ~2,5 min do MPT, mas é medida no log (`ms`) para não
  virar suposição.

## 7. Definição de "aprovado sem ressalvas"

Os 12 critérios em **sim**, suíte verde, nenhum arquivo em `supabase/`, a medida
provadamente degradável (teste que força o ffmpeg a falhar e verifica que
`processar` conclui), e o comando do ffmpeg conferido contra o formato real do
filtro — não contra memória.

## 8. Resultado da review

✅ **Aprovado**, 12/12. Portões: **541 testes do worker verdes** (eram 510; +31),
7 skips inalterados · zero arquivos em `supabase/`, RLS **41 ✅** por construção ·
`pyproject.toml`/`uv.lock` intocados.

**Provado contra ffmpeg real (7.0.2), não só em teste.** Os três desfechos saíram
de execução de verdade sobre áudio sintetizado na hora:

| Cenário | Resultado |
|---|---|
| Narração com pausas em 2–3s e 6–6,5s | `pausas: 2`, desalinhamento médio **1,611s**, máximo 1,742s, `exit 0` |
| Mesmo áudio, limiar em −40 dB (piso da trilha por cima) | `pausas: 0`, aviso de pausa mascarada disparado, `exit 0` |
| `--ffmpeg` inexistente | `medir()` devolveu `None`, WARNING, `exit 1`, sem stack trace |

O terceiro saiu de um engano meu de shell e vale mais por isso: a degradação foi
exercitada sem ser encenada.

## 9. Aprendizados

- **A previsão do § 3 estava forte demais, e medir a corrigiu.** Escrevi que a
  trilha do MPT tornaria a pausa indetectável ("no mix não existe silêncio"). A
  bancada disse outra coisa: a trilha levanta o piso da pausa de −91 dB para
  −34,5 dB — mecanismo real, 56 dB de efeito — mas parou **4,5 dB antes** do
  limiar, e as pausas foram detectadas. O achado verdadeiro não é "não dá para
  medir", é "a margem é fina". Ter escrito a previsão como fato teria plantado
  no repositório uma frase confiante e errada, do tipo que ninguém revisa depois
  porque parece decidida.
- **O limiar virou variável por causa desses 4,5 dB, não por gosto de
  configurabilidade.** Fosse constante, o dia em que uma trilha mais alta
  cruzasse o limiar produziria `pausas: 0` em todo vídeo — e o sintoma seria
  "o ffmpeg parou de funcionar".
- **Requisito oposto justifica runner duplicado.** `postprocess._rodar` passa
  `-loglevel error`, porque lá o stderr só importa quando o ffmpeg falha. Aqui o
  stderr **é** o resultado: `silencedetect`/`volumedetect` escrevem em *info*.
  Reusar aquele runner devolveria stderr vazio em todo vídeo saudável e o
  sintoma seria "nunca há pausa" — indistinguível do caso da trilha. Virou o
  teste `test_nao_silencia_a_propria_medida`, porque a regressão é muda.
- **Número que duas partes precisam concordar vira constante, e o acordo vira
  teste.** O `4` de `video_clip_duration` estava cravado em `montar_corpo`; a
  medida compara contra essa grade. Com o número em dois lugares, o M2 (que vai
  justamente mudar a cadência) faria a medida comparar contra uma grade que o
  render não usa mais — e ela mentiria com cara de estar certa. Virou
  `mpt.CLIP_SEG` mais um teste que afirma a igualdade.
- **`None` e `0.0` não são a mesma resposta.** Sem pausa, o desalinhamento é
  `None`, não zero: zero diria "perfeitamente alinhado", que é o oposto exato do
  que aconteceu. Mesma família do `ciclo_em` nulo da Sprint 7.
