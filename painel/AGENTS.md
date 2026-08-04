<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## O que já foi lido nesses docs (Next 16.2)

Custa caro reaprender:

- **`proxy.ts`, não `middleware.ts`.** O arquivo foi renomeado. Um `middleware.ts`
  não dá erro — ele simplesmente não roda, e o sintoma (sessão que expira
  sozinha) parece problema do Supabase. Runtime é `nodejs` e não é configurável;
  `edge` saiu.
- **`cookies()`, `headers()`, `params` e `searchParams` são Promises.** O acesso
  síncrono foi removido, não depreciado.
- **`revalidatePath` continua, mas para dado dinâmico use `refresh()` de
  `next/cache`** dentro da Server Action. `revalidateTag` agora exige o segundo
  argumento (`cacheLife`).
- Turbopack é o padrão em `dev` e `build`; `next lint` não existe mais.

## Regras deste painel

- **Só a `anon` key.** `SUPABASE_SERVICE_ROLE_KEY` não entra aqui em hipótese
  nenhuma — ela ignora RLS no banco inteiro. Ver `lib/supabase/env.ts`.
- **Não filtrar por `org_id` na query.** As políticas de RLS já fazem isso.
  Repetir no cliente dá a impressão de que a proteção mora no painel.
- **`preview_url`/`thumb_url` guardam CAMINHO no Storage, não URL.** Assine na
  hora de exibir (`lib/storage.ts`). URL assinada expira e *é* a credencial do
  arquivo: nunca persistir, nunca logar.
- **Server Action é um POST alcançável direto.** Toda action confere a sessão
  dentro dela — o proxy protege URLs, e action não é URL.
- **Transição de estado é do banco.** O painel só chama `aprovar_video`,
  `reprovar_video`, `enfileirar_pauta` e `descartar_pauta`. `update` direto em
  `videos.status`/`pautas.status` é recusado pela política (e, no caso do
  descarte, pelo trigger `t_pautas_guarda_descarte`) e não deve ser tentado.
- **Mensagem de erro é escrita à mão.** `traduzir()` em `app/acoes.ts` mapeia
  SQLSTATE para uma frase; `error.message` do PostgREST nunca vai para a tela.
- Mobile-first de verdade: alvo de toque com no mínimo 48px de altura, navegação
  na base, `preload="metadata"` em vídeo.
