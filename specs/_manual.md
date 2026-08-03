# Passos manuais acumulados

Tudo que só uma pessoa pode fazer — credencial, tela de consentimento, caixa de
e-mail, painel de terceiro. O loop **não** interrompe para pedir nenhum destes;
ele anota aqui e segue. A lista é entregue de uma vez no fim, como o dono pediu.

Ordem de leitura: o que destrava mais coisa primeiro.

---

## 1. Footage de verdade em `MoneyPrinterTurbo/storage/local_videos/`

**Por quê:** os três clipes que estão lá (`atm-teste-01/02/03.mp4`) são pretos —
o pixel mais claro do frame inteiro fica em 36–41 de 255. Não é "material
escuro": um clipe cinematográfico escuro ainda tem highlight passando de 200.
Enquanto isso não mudar, todo vídeo renderizado é tela preta com legenda, e a
graduação da Sprint 3 não pode ser julgada.

**O que fazer:** soltar arquivos `.mp4` verticais na pasta. Nenhuma linha de
código muda. Nome de arquivo, não caminho — o MPT resolve tudo contra essa pasta
e descarta em silêncio o que escapar.

---

## 2. OAuth do YouTube (item 9b do § 8)

**Por quê:** o worker publica no YouTube, mas nenhum vídeo subiu ainda. O
consentimento do Google exige uma pessoa na tela; credencial não passa por mim.

**O que fazer**, em `console.cloud.google.com`:

1. Ativar a **YouTube Data API v3**.
2. Tela de consentimento: tipo **Externo**, e o seu e-mail em **Usuários de teste**.
3. Criar ID de cliente OAuth do tipo **App para computador**.
4. Baixar o JSON e salvar como `worker/client_secret.json`.

Depois:

```bash
cd worker && uv run autorizar_youtube.py
```

Abre o navegador, você aprova, o script grava `worker/token.json` (gitignored).

**Armadilha de 7 dias:** enquanto o app estiver como *Testing*, o refresh token
expira toda semana e o worker para de publicar com `AutorizacaoAusente` — sem
barulho, só some vídeo. Publicar o app (mesmo sem verificação, para uso próprio)
remove o prazo. Isso morde na Sprint 7, quando o worker subir sozinho no boot.

---

## 3. Deploy do painel na Vercel + primeiro login (item 10b do § 8)

**Por quê:** o painel está pronto e compila, mas ninguém logou. O magic link cai
numa caixa de e-mail que é sua.

1. Vercel: importar o repositório com **Root Directory = `painel`**.
2. Variáveis: `NEXT_PUBLIC_SUPABASE_URL` e `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
   **Só a anon.** A `service_role` não entra na Vercel em hipótese nenhuma.
3. Supabase → Authentication → URL Configuration: **Site URL** com o domínio da
   Vercel, e **Redirect URLs** incluindo `https://<domínio>/auth/confirm`.
   Sem isso o link chega e não vira sessão.
4. Abrir no celular, pedir o magic link, confirmar que a fila aparece.

Opcional: trocar o template de e-mail para `{{ .TokenHash }}`. Não é necessário —
`/auth/confirm` aceita `code` e `token_hash`.

---

## 4. App do TikTok (Sprint 5)

**Por quê:** o worker sabe conversar com a API, mas o app precisa existir e ser
autorizado por você. E há um limite que o código não consegue contornar.

1. Criar o app no portal de desenvolvedor do TikTok.
2. Pedir o escopo **`video.upload`** (rascunho/inbox). **Não** `video.publish`:
   cliente não auditado é forçado a `SELF_ONLY` em direct post, o que renderiza
   um vídeo que ninguém vê.
3. Registrar a **redirect URI**, que precisa ser **HTTPS e estática** —
   localhost e HTTP são recusados pelo TikTok.
4. Preencher no `worker/.env`: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`,
   `TIKTOK_REDIRECT_URI`.
5. Rodar `uv run autorizar_tiktok.py` e colar de volta a URL para onde o TikTok
   te redirecionou.

**O que a API não faz por você:** o rótulo de conteúdo gerado por IA. O endpoint
de rascunho aceita só `source_info` — legenda, privacidade e o toggle de IA são
escolhidos no app, na hora de postar. **Ligue o toggle de "conteúdo gerado por
IA" em cada rascunho.** Sem rótulo, a política das duas plataformas prevê
remoção do conteúdo.

---

## 5. Higiene do OneDrive

`worker/` está dentro do OneDrive, então `token.json`, `tiktok_token.json` e
`.env` — que carrega a `service_role` — sincronizam para a nuvem da Microsoft.
Se isso não te agrada, aponte `YOUTUBE_TOKEN`/`TIKTOK_TOKEN` para fora da pasta
sincronizada. Vale excluir `painel/node_modules` da sincronização também: são
dezenas de milhares de arquivos que o OneDrive tenta versionar sem motivo.
