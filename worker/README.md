# worker

Roda no PC local. Puxa da fila, renderiza, publica. **Nunca abre porta** — só
sai daqui em direção ao Supabase (ADR-05).

Estado atual: **Sprint 1** — render FAKE. Sem MPT, sem ffmpeg, sem upload.

## Rodar

```bash
uv sync              # instala Python 3.11 e as dependências
uv run pytest        # 27 testes, nenhum precisa de rede
uv run main.py --uma-vez   # um ciclo e sai
uv run main.py       # loop até Ctrl-C
```

O `uv` baixa o Python 3.11 sozinho — não precisa instalar nada antes.

## Antes do primeiro run

`worker/.env` precisa de `SUPABASE_SERVICE_ROLE_KEY` (Dashboard > Project
Settings > API Keys > service_role). O resto já vem preenchido.

Essa chave **ignora RLS no banco inteiro**. Vive só aqui: nunca no painel,
nunca na Vercel, nunca no git.

Para ter o que consumir:

```bash
supabase db query --linked -f ../supabase/seeds/dev_seed.sql
```

## Arquivos

| arquivo | papel |
|---|---|
| `main.py` | o loop e as invariantes |
| `db.py` | camada de serviços — nenhuma chamada ao banco fora daqui |
| `render.py` | Sprint 1 fake; a Sprint 2 troca `renderizar()` pelo cliente do MPT |
| `config.py` | lê o `.env` e falha cedo, nomeando a variável que faltou |
| `log.py` | logging JSON — nunca passar chave ou token como campo |

## Invariantes (não quebrar)

1. **O loop não morre.** Exceção é logada, o loop segue.
2. **Vídeo travado sempre solta.** Falhou → solta o lock; morreu o processo →
   `destravar_orfaos` solta depois. Fila não empaca.
3. **Só tráfego de saída.** Nenhuma porta, nenhum servidor, nenhum callback.

`tests/test_ciclo.py` existe para a 2 não morrer sem ninguém perceber.
