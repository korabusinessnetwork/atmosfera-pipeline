"""Autoriza o worker no YouTube. Roda UMA vez, à mão, por você.

Está fora do `main.py` de propósito. O fluxo OAuth de desktop abre um servidor
HTTP local para receber o callback do Google — e o worker é justamente o
processo que **nunca** abre porta (ADR-05). Aqui a porta vive alguns segundos,
em loopback, num processo separado que morre em seguida; o worker de 24h nem
carrega o código de servidor na memória (o import é preguiçoso).

Antes de rodar, no Google Cloud Console (é você quem faz, não o worker):

  1. Crie ou escolha um projeto.
  2. Ative a **YouTube Data API v3**.
  3. Tela de consentimento OAuth: tipo **Externo**, e adicione o seu próprio
     e-mail em *Usuários de teste* — sem isso o Google recusa o login.
  4. Credenciais → Criar credenciais → **ID do cliente OAuth** →
     tipo de aplicativo **App para computador**.
  5. Baixe o JSON e salve como `worker/client_secret.json`
     (ou aponte YOUTUBE_CLIENT_SECRET para onde você preferir).

Depois:

    cd worker && uv run autorizar_youtube.py

O navegador abre, você escolhe a conta do canal, aceita, e o `token.json`
aparece. Nada de token é impresso aqui — nem no sucesso, nem no erro.

**Dois escopos num consentimento só (Rodada 11):** este autorizador pede
`youtube.upload` **e** `yt-analytics.readonly` (leitura de métrica). Se você já
tinha um `token.json` só de upload, rode de novo e aprove — o novo token cobre os
dois, e é isso que liga o `coletar_metricas.py`. O upload nunca deixa de
funcionar: `carregar_credenciais` sem argumento segue pedindo só o escopo mínimo.

**Prazo que pega todo mundo:** enquanto o app estiver em *Testing* na tela de
consentimento, o Google expira o refresh token em **7 dias**. O worker vai
parar de publicar com `AutorizacaoAusente` e o conserto é rodar este script de
novo. Publicar o app (mesmo sem verificação, para uso próprio) remove o prazo.
"""

from __future__ import annotations

import sys

from config import ConfigInvalida, carregar
from publishers import youtube


def main() -> int:
    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2

    if not cfg.youtube_client_secret.is_file():
        print(
            f"client_secret não encontrado em {cfg.youtube_client_secret}\n"
            "Crie um ID de cliente OAuth do tipo 'App para computador' no Google\n"
            "Cloud Console, baixe o JSON e salve nesse caminho. As instruções\n"
            "completas estão no cabeçalho deste arquivo.",
            file=sys.stderr,
        )
        return 2

    if cfg.youtube_token.is_file():
        print(f"já existe um token em {cfg.youtube_token}.")
        resposta = input("Sobrescrever e autorizar de novo? [s/N] ").strip().lower()
        if resposta not in ("s", "sim", "y", "yes"):
            print("nada feito.")
            return 0

    print("abrindo o navegador — escolha a conta DO CANAL, não a pessoal.")
    try:
        youtube.autorizar(cfg.youtube_client_secret, cfg.youtube_token)
    except Exception as erro:  # noqa: BLE001
        # Sem traceback: a exceção do oauthlib pode carregar o corpo da resposta
        # do Google, e ali vem token. Só a classe e a mensagem curta.
        print(f"autorização falhou: {type(erro).__name__}: {erro}", file=sys.stderr)
        return 1

    print(f"pronto. token salvo em {cfg.youtube_token}")
    print("esse arquivo é uma credencial: já está no .gitignore, não o compartilhe.")
    if "OneDrive" in str(cfg.youtube_token):
        print(
            "\naviso: esse caminho está dentro do OneDrive, então o token vai\n"
            "sincronizar para a nuvem da Microsoft. Para evitar, aponte\n"
            "YOUTUBE_TOKEN no worker/.env para uma pasta fora da sincronizada."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
