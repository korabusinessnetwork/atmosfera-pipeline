# worker

Roda no PC local. Puxa da fila, renderiza, publica. **Nunca abre porta** — só
sai daqui em direção ao Supabase (ADR-05).

Estado atual: **Sprint 2** — render de verdade pelo MoneyPrinterTurbo.
Sem upload ainda (Sprints 4 e 5).

## Rodar

```bash
uv sync              # instala Python 3.11 e as dependências
uv run pytest        # 56 testes, nenhum precisa de rede, chave ou MPT de pé
uv run main.py --uma-vez   # um ciclo e sai
uv run main.py       # loop até Ctrl-C
```

O `uv` baixa o Python 3.11 sozinho — não precisa instalar nada antes.

## Antes do primeiro run

**1. O MPT precisa estar de pé** — o worker renderiza através dele:

```bash
pwsh scripts/mpt-up.ps1
```

E precisa haver footage em `MoneyPrinterTurbo/storage/local_videos/`. Só desse
diretório: o MPT resolve todo material contra ele e descarta o resto **sem
avisar**. Por isso o worker manda nome de arquivo, nunca caminho.

**2. `worker/.env`** — copie de `.env.example` e preencha
`SUPABASE_SERVICE_ROLE_KEY` (Dashboard > Project Settings > API Keys). O resto
tem padrão que funciona.

Essa chave **ignora RLS no banco inteiro**. Vive só aqui: nunca no painel,
nunca na Vercel, nunca no git.

**3. Para ter o que consumir:**

```bash
supabase db query --linked -f ../supabase/seeds/dev_seed.sql
```

## Arquivos

| arquivo | papel |
|---|---|
| `main.py` | o loop e as invariantes |
| `db.py` | camada de serviços — nenhuma chamada ao banco fora daqui |
| `mpt.py` | cliente do MoneyPrinterTurbo — é o render |
| `render.py` | nome e lugar do mp4 de saída (a Sprint 4 usa para achar o arquivo) |
| `config.py` | lê o `.env` e falha cedo, nomeando a variável que faltou |
| `log.py` | logging JSON — nunca passar chave ou token como campo |

## Invariantes (não quebrar)

1. **O loop não morre.** Exceção é logada, o loop segue.
2. **Vídeo travado sempre solta.** Falhou → solta o lock; morreu o processo →
   `destravar_orfaos` solta depois. Fila não empaca.
3. **Só tráfego de saída.** Nenhuma porta, nenhum servidor, nenhum callback.

`tests/test_ciclo.py` existe para a 2 não morrer sem ninguém perceber.

## Se o render falhar

`state = -1` do MPT não é retentado aqui de propósito — o vídeo volta para a
fila e quem conta reincidência é o `tentativas < 3` do `claim_proximo_video`.
Retentar nos dois lugares daria 9 tentativas. A causa real fica em
`videos.erro_msg`, com a etapa do MPT que quebrou.

`RemoteDisconnected` durante o polling é normal e já está tratado: o uvicorn
fecha conexão ociosa no mesmo ritmo do polling, e a sessão retenta GET (nunca
POST — repetir o POST criaria uma segunda task do mesmo vídeo).
