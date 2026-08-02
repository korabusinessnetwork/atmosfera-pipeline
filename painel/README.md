# Painel — Atmosfera Pipeline

O gate humano. É aqui que um vídeo renderizado vira publicado, ou não.

Três telas, feitas para o celular:

1. **Fila** (`/`) — vídeos em `aguardando_aprovacao`, com preview e os botões
   Aprovar/Reprovar.
2. **Pautas** (`/pautas`) — o que o Cowork escreveu e ainda não virou render,
   com o botão de enfileirar.
3. **Histórico** (`/historico`) — uma linha por vídeo por plataforma.

## Rodar local

```bash
cp .env.local.example .env.local
```

Preencha `NEXT_PUBLIC_SUPABASE_URL` e `NEXT_PUBLIC_SUPABASE_ANON_KEY`
(Supabase → Settings → API → *anon public*). Sem as duas o app não sobe, e a
mensagem de erro diz exatamente isso — é de propósito.

```bash
npm install && npm run dev
```

## Deploy

Vercel, com **Root Directory = `painel`**. As mesmas duas variáveis em
Settings → Environment Variables.

Depois, em Supabase → Authentication → URL Configuration, a **Site URL** e a
lista de **Redirect URLs** precisam conter `https://<seu-domínio>/auth/confirm`.
Sem isso o magic link chega, é clicado e devolve para a tela de entrada sem
explicação nenhuma.

## Quem consegue entrar

Ninguém por convite automático. O e-mail precisa estar em `public.membros` com
um `org_id` — veja `supabase/seed_membros.example.sql`. Qualquer outro endereço
consegue *uma sessão* (o magic link é cadastro e login pela mesma porta), mas
sem `org_id` no JWT a RLS não devolve linha nenhuma e a tela avisa que falta
convite.

## Antes de mexer no código

Leia `AGENTS.md`. Este é o Next 16: o arquivo de middleware chama `proxy.ts`,
`cookies()` e `searchParams` são Promises, e a chave `service_role` não entra
aqui em hipótese nenhuma.
