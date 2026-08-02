"""Publishers — um módulo por plataforma.

Regra do pacote: **nenhum publisher importa o Supabase.** Ele recebe um pedido
pronto e devolve um resultado; quem lê e escreve no banco é o `db.py`, e quem
orquestra é o `publicar.py`. Sem isso, cada plataforma nova traria sua própria
opinião sobre a tabela e o contrato deixaria de ser único.

Sprint 4: youtube. Sprint 5: tiktok.
"""
