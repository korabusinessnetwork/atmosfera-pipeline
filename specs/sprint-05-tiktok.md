# Sprint 5 — TikTok (rascunho na caixa de entrada)

Rodada 1 do ciclo. Fonte: `ATMOSFERA_PIPELINE.md` § 5, Sprint 5, item 11 do § 8.

## 1. Escopo

Publicar no TikTok pelo endpoint de **rascunho** (`/v2/post/publish/inbox/video/init/`,
escopo `video.upload`), integrado ao ciclo de publicação que hoje só fala com o
YouTube: o worker sobe o mp4 para a caixa de entrada do app e o dono finaliza o
post pelo celular.

## 2. Fora de escopo

- **Direct post** (`/v2/post/publish/video/init/`). Cliente não auditado tem todo
  conteúdo forçado a `SELF_ONLY` pelo servidor — o pipeline "funcionaria" e
  geraria zero views. É a razão de existir desta sprint, não um atalho que
  deixamos para depois.
- Auditoria do Content Posting API (backlog, § 9).
- Ler métricas do TikTok — a Sprint 5 escreve, não lê.
- Migration. O schema já cobre: `publish_id` cabe em `publicacoes.external_id`,
  `url` fica nula num rascunho (não existe endereço para post não postado) e
  `plataforma in ('youtube','tiktok')` já está no check da tabela.
- Criar o app no portal do TikTok e autorizar o OAuth — passo humano, vai para
  `specs/_manual.md`.

## 3. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `worker/publishers/tiktok.py` | novo — cliente da API, sem conhecer Supabase |
| `worker/autorizar_tiktok.py` | novo — OAuth one-shot, sem abrir porta |
| `worker/publicar.py` | reescrito — de uma plataforma para duas |
| `worker/config.py` | `tiktok_token`, `tiktok_client_key/secret`, `tiktok_redirect_uri` |
| `worker/db.py` | `concluir_publicacao` com `url`/`agendado_para` opcionais |
| `worker/.env.example` | seção TikTok (sem segredo — o arquivo é commitado) |
| `worker/tests/test_tiktok.py` | novo |
| `worker/tests/test_publicar.py` | atualizado para o formato de duas plataformas |
| `.gitignore` | `worker/tiktok_token.json` |
| `painel/app/(painel)/historico/page.tsx` | aviso do rótulo de IA nos rascunhos |
| `ATMOSFERA_PIPELINE.md` | § 3 (árvore), § 8 (item 11), bloco "Entregue (item 11)" |

## 4. Critérios de aceite

1. **Só o endpoint de rascunho é chamado.** Nenhuma referência a
   `/post/publish/video/init/` no código. O escopo pedido é `video.upload`.
2. **O corpo do init leva só `source_info`.** A documentação do endpoint de
   inbox não aceita `post_info`, `is_aigc`, `privacy_level` nem `title`; mandar
   campo inventado é erro silencioso ou 400.
3. **A aritmética de pedaço segue a regra do TikTok:** `total_chunk_count` é
   `video_size ÷ chunk_size` **arredondado para baixo**, o último pedaço absorve
   o resto, mínimo 5 MB, máximo 64 MB (último até 128 MB), teto de 1000 pedaços,
   e arquivo abaixo de 5 MB vai inteiro num pedaço só.
4. **Teto de 6 requisições por minuto por token** respeitado por espaçamento
   real entre chamadas de init, com relógio e sono injetáveis (teste não dorme).
5. **Teto de 5 rascunhos pendentes por 24 h** contado em janela móvel a partir de
   `publicacoes.enviado_em`, plataforma `tiktok`.
6. **Nenhum segredo vaza para o banco, para o log ou para exceção.** Nem
   `access_token`, nem a `upload_url` pré-assinada que o init devolve. Vale para
   `repr` do token e para a mensagem gravada em `publicacoes.erro_msg`.
7. **Retry só no que é idempotente.** `PUT` de uma faixa de bytes pode repetir;
   `POST /init` nunca — repetir cria um segundo rascunho e queima uma das cinco
   vagas de 24 h.
8. **`videos.status` é escrito num lugar só.** As funções de plataforma escrevem
   apenas em `publicacoes`; quem move o vídeo é uma única função, uma vez por
   vídeo, depois das duas plataformas.
9. **Plataforma sem credencial não trava a fila.** Falta de app/token é
   diferente de falta de vaga: a primeira faz a plataforma sair da conta do
   vídeo, a segunda adia. Sem isso, com o TikTok nunca configurado, todo vídeo
   publicado no YouTube voltaria para `aprovado` e o lote entupiria.
10. **Adiar não conta como trabalho.** Um ciclo que só adiou deixa o `main.loop`
    dormir; caso contrário o worker varre o Supabase em milissegundos por horas.
11. **O OAuth não abre porta no PC** (ADR-05). O redirect do TikTok é HTTPS
    estático e registrado — localhost é recusado por eles —, então o fluxo é
    colar de volta a URL de retorno, e o `state` é conferido contra CSRF.
12. **O rótulo de conteúdo de IA está endereçado.** A API de rascunho não aceita
    `is_aigc`; então o worker registra no log que falta marcar, o painel avisa
    quem for postar, e o passo entra em `specs/_manual.md`.
13. **`uv run pytest` verde**, com os testes novos cobrindo os critérios 3, 4, 6,
    7 e 11 — e sem nenhum teste que precise de rede, chave ou app do TikTok.
14. **RLS 20 ✅ e advisors `No issues found`** — não deve mudar nada, e a sprint
    tem de provar que não mudou.
15. **`npm run build --prefix painel` limpa**, já que o histórico foi tocado.

## 5. Edge cases conhecidos

- Arquivo menor que 5 MB (um pedaço), e arquivo com resto — 12 MB em pedaços de
  5 MB dá **2** pedaços, não 3.
- Token vencido no meio do lote; refresh token vencido (365 dias) → falta
  credencial, não falha de rede.
- Rede caindo durante o refresh → adia, não desliga a plataforma.
- Vídeo já enviado ao YouTube e sem vaga no TikTok → volta para `aprovado`.
- Vídeo já enviado ao YouTube e TikTok desligado → fecha como `publicado`, com
  log dizendo qual canal ficou de fora.
- Processo morto entre o upload e a escrita do estado → o ciclo seguinte fecha o
  vídeo sem chamar a API de novo.
- `arquivo_path` apontando para arquivo que sumiu; pauta apagada com vídeo vivo.
- O TikTok respondendo `FAILED` com `fail_reason` (formato, duração, spam).

## 6. Definição de "aprovado sem ressalvas"

Os 15 critérios respondidos "sim" com evidência em linha de código; pytest verde
com o número real de testes; RLS 20 ✅; advisors limpo; build do painel limpo;
nenhum TODO novo; e o que depende de credencial humana registrado em
`specs/_manual.md` em vez de fingido como pronto.

---

## 7. Resultado da review — 2026-08-02

**✅ aprovado sem ressalvas.** 15 de 15 critérios com evidência em linha.
**216 testes** (eram 158) · RLS **20 ✅ / 0 ❌** · advisors `No issues found` ·
`next build` limpo, `/historico` continua dinâmica.

*Este projeto ainda não tem `memory/` — o `/aprender` registra aqui, no próprio
spec, como manda a skill. A base de memória é criada pela `fundacao-de-projeto`,
que é sobra da Sprint 0.*

### O que a rodada corrigiu

**Critério 8 — um docstring que exagerava a invariante.** `publicar.py` dizia que
`_fechar_video` era "a ÚNICA escrita em `videos.status`", e são três:
`_invalidar`, a marca `publicando` do `_ciclo` e ele. O comportamento estava
certo — as três nunca se cruzam no mesmo vídeo, porque as duas primeiras rodam
antes de existir desfecho de plataforma — mas a frase enganaria quem chegasse
depois, e num projeto document-first isso é defeito. Os dois docstrings foram
reescritos para a regra verdadeira (*função de plataforma não escreve em
`videos`; a orquestração escreve*) e a regra virou
`test_so_a_orquestracao_escreve_em_videos`, que lê a árvore do próprio
`publicar.py` com `ast` e cobra o nome da função que envolve cada `db.marcar`.

### O que ensinou, e não seria óbvio na próxima vez

- **Invariante que vale "por construção" precisa de teste estrutural, não de
  cenário.** Um `db.marcar(..., "erro")` acrescentado dentro de `_enviar_tiktok`
  passaria em todos os 35 testes de comportamento e apagaria o `publicado` que o
  YouTube tinha acabado de merecer. `ast.walk` + nome da função-mãe custa 15
  linhas e falha na hora em que a chamada aparece no lugar errado.
- **A resposta do TikTok é `{data, error}`, sempre — menos em `/oauth/token/`.**
  Quatro testes vermelhos antes de o dublê aprender isso. `_corpo_json()`
  desembrulha num lugar só.
- **`total_chunk_count` é `//`, nunca `ceil`.** 12 MB em pedaços de 5 MB dão 2, e
  o último carrega 7 MB. `ceil` é recusado — depois do init, com a vaga gasta.
- **O TikTok recusar localhost fez a ADR-05 sair de graça.** O redirect tem de
  ser HTTPS estático registrado, então o servidor efêmero que o YouTube exigiu
  aqui nem existe: o script imprime o link e lê a URL de retorno colada.

### O que ficou de fora, de propósito

- Nada subiu para o TikTok, e o aviso do painel nunca foi visto renderizado
  (`/historico` está atrás de sessão). App do portal e OAuth em
  `specs/_manual.md` § 4 — item 11b do § 8.
- Ler métrica do TikTok e a auditoria do Content Posting API continuam no
  backlog (§ 9 do documento mestre), como o escopo previa.
