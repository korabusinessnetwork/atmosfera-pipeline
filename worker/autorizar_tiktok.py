"""Autoriza o worker no TikTok. Roda UMA vez, à mão, por você.

Fora do `main.py` pelo mesmo motivo do `autorizar_youtube.py` — mas aqui o ADR-05
sai ainda mais barato: **este script não abre porta nenhuma.**

O TikTok exige que o `redirect_uri` seja HTTPS e esteja registrado no portal;
*"Localhost and HTTP are not permitted"*. Ou seja, o truque do Google (subir um
servidor efêmero em 127.0.0.1 e esperar o callback) simplesmente não existe aqui.
O que sobra é melhor: o navegador te manda para uma URL sua, você copia a barra
de endereços inteira e cola de volta no terminal. Nem por três segundos há algo
escutando no PC.

Antes de rodar, no portal de desenvolvedor do TikTok (é você quem faz):

  1. Crie o app.
  2. Adicione o produto **Content Posting API** e peça o escopo `video.upload`.
     **Não peça `video.publish`** — é o do direct post, que a auditoria trava em
     SELF_ONLY, e pedir escopo que não vamos usar é pedir permissão a mais numa
     tela de consentimento.
  3. Registre a **Redirect URI** — HTTPS, estática, exatamente igual à que vai
     no `.env`. Se você não tiver domínio, serve qualquer página https que seja
     sua; ela nunca precisa funcionar, só receber o redirect com o `code` na
     barra de endereços.
  4. Copie Client key e Client secret para o `worker/.env`:
     `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`.

Depois:

    cd worker && uv run autorizar_tiktok.py

Nenhum token é impresso — nem no sucesso, nem no erro.

**Prazo:** o access_token dura 24h e o worker renova sozinho. O refresh_token
dura 365 dias, e cada renovação devolve um novo. Se o app for revogado ou o ano
passar, o worker para com `AutorizacaoAusente` e o conserto é rodar isto de novo.
"""

from __future__ import annotations

import secrets
import sys

from config import ConfigInvalida, carregar
from publishers import tiktok


def main() -> int:
    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2

    faltando = [
        nome
        for nome, valor in (
            ("TIKTOK_CLIENT_KEY", cfg.tiktok_client_key),
            ("TIKTOK_CLIENT_SECRET", cfg.tiktok_client_secret),
            ("TIKTOK_REDIRECT_URI", cfg.tiktok_redirect_uri),
        )
        if not valor
    ]
    if faltando:
        print(
            f"falta preencher no worker/.env: {', '.join(faltando)}\n"
            "As três saem do portal de desenvolvedor do TikTok, no seu app.\n"
            "O passo a passo está no cabeçalho deste arquivo.",
            file=sys.stderr,
        )
        return 2

    if not cfg.tiktok_redirect_uri.startswith("https://"):
        # Falha aqui e não depois: o TikTok recusa com uma tela genérica de
        # "algo deu errado" e a causa não aparece em lugar nenhum.
        print(
            f"TIKTOK_REDIRECT_URI precisa começar com https:// (está "
            f"{cfg.tiktok_redirect_uri.split(':')[0]}://...).\n"
            "O TikTok não aceita http nem localhost, mesmo em desenvolvimento.",
            file=sys.stderr,
        )
        return 2

    if cfg.tiktok_token.is_file():
        print(f"já existe um token em {cfg.tiktok_token}.")
        resposta = input("Sobrescrever e autorizar de novo? [s/N] ").strip().lower()
        if resposta not in ("s", "sim", "y", "yes"):
            print("nada feito.")
            return 0

    # Anti-CSRF: volta na URL de retorno e é conferido antes da troca. Sem isso,
    # colar uma URL de outra origem conectaria outra conta sem ninguém notar.
    state = secrets.token_urlsafe(24)
    url = tiktok.url_de_autorizacao(cfg.tiktok_client_key, cfg.tiktok_redirect_uri, state)

    print("\n1. Abra este link no navegador (logado na conta do TikTok do canal):\n")
    print(url)
    print(
        "\n2. Autorize. O TikTok vai te jogar para o seu redirect_uri — a página\n"
        "   pode dar 404, tudo bem, o que importa é a barra de endereços.\n"
        "3. Copie a barra de endereços INTEIRA e cole aqui.\n"
    )

    retorno = input("URL de retorno: ").strip()
    if not retorno:
        print("nada colado — nada feito.", file=sys.stderr)
        return 1

    try:
        codigo = tiktok.codigo_da_url(retorno, state)
    except tiktok.AutorizacaoAusente as erro:
        print(f"não deu: {erro}", file=sys.stderr)
        return 1

    sessao = tiktok.criar_sessao()
    try:
        token = tiktok.trocar_codigo(
            codigo,
            cfg.tiktok_client_key,
            cfg.tiktok_client_secret,
            cfg.tiktok_redirect_uri,
            sessao,
        )
    except Exception as erro:  # noqa: BLE001
        # Só classe e mensagem: o corpo do POST leva o client_secret, e algumas
        # exceções do requests carregam a requisição inteira junto.
        print(f"troca do código falhou: {type(erro).__name__}: {erro}", file=sys.stderr)
        return 1
    finally:
        sessao.close()

    tiktok.gravar_token(token, cfg.tiktok_token)

    print(f"\npronto. token salvo em {cfg.tiktok_token}")
    print(f"escopo concedido: {token.escopo}")
    if tiktok.ESCOPO not in token.escopo:
        print(
            f"AVISO: o escopo {tiktok.ESCOPO} não veio na resposta. O upload vai\n"
            "falhar com erro de permissão. Confira o produto Content Posting API\n"
            "no portal e autorize de novo.",
            file=sys.stderr,
        )
    print("esse arquivo é uma credencial: já está no .gitignore, não o compartilhe.")
    if "OneDrive" in str(cfg.tiktok_token):
        print(
            "\naviso: esse caminho está dentro do OneDrive, então o token vai\n"
            "sincronizar para a nuvem da Microsoft. Para evitar, aponte\n"
            "TIKTOK_TOKEN no worker/.env para uma pasta fora da sincronizada."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
