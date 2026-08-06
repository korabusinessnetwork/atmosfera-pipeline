"""Camada de serviços do Supabase. Nenhuma chamada ao banco fora daqui.

Regra da casa (CLAUDE.md): toda chamada ao backend passa pela camada de
serviços. Quando o schema mudar, muda um arquivo — e a Sprint 2 confirmou:
trocar o render fake pelo MPT não encostou em nada aqui.

O cliente usa a `service_role`, que **ignora RLS por design**. É por isso que
essa chave vive só no `.env` local: no painel ela dissolveria o multi-tenant.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from supabase import Client, create_client

from config import Config

log = logging.getLogger("worker.db")

# Campos explícitos, nunca `select *` (CLAUDE.md § Segurança). Aqui vale
# menos por sigilo e mais por contrato: se alguém somar coluna em `pautas`,
# o worker não passa a arrastar dado que não pediu.
CAMPOS_PAUTA = "id, tema, roteiro, hook, titulo, descricao, hashtags, status, prioridade"

# `videos.erro_msg` é text sem limite, mas traceback de HTTP passa de 10 KB e
# quem lê isso é o painel, no celular. 500 chars mostram a causa e param aí.
LIMITE_ERRO = 500


def truncar_erro(mensagem: str, limite: int = LIMITE_ERRO) -> str:
    """Corta a mensagem de erro no limite, sinalizando que houve corte."""
    texto = " ".join(str(mensagem).split())
    if len(texto) <= limite:
        return texto
    return texto[: limite - 1] + "…"


def criar_cliente(cfg: Config) -> Client:
    return create_client(cfg.supabase_url, cfg.supabase_service_role_key)


# ============================================================ pauta local (R4)

# Estados de um vídeo que ainda não passou pelo gate humano. É o que o produtor
# de pauta local conta para não afogar a fila: pauta nova em cima de trabalho
# que ninguém aprovou só empurra o gargalo, e o gargalo nunca foi renderizar.
FILA_VIVA = ("na_fila", "renderizando", "aguardando_aprovacao")


def inserir_pauta(
    sb: Client,
    org_id: str,
    tema: str,
    roteiro: str,
    hook: str | None = None,
    titulo: str | None = None,
    descricao: str | None = None,
    origem: str = "ollama",
    categoria: str | None = None,
) -> str:
    """Insere uma pauta pronta de produtor de máquina. Devolve o id.

    `status` é carimbado aqui, não recebido: o produtor não escolhe — é a mesma
    disciplina da `pauta_nova` do painel, que fixa no servidor. E é isso que o
    trigger `t_pautas_auto_enfileirar` espera para enfileirar sozinho até o gate.

    `origem` tem default 'ollama' (o produtor local, Rodada 4) para não mudar
    nenhuma chamada existente; o produtor Gemini (Rodada 20) passa 'gemini'. O
    check `pautas_origem_check` recusa qualquer valor fora do vocabulário, então
    um typo aqui falha no banco, não vira categoria fantasma.

    `categoria` (Rodada 21) é o NOME da categoria que dirigiu a geração, gravado
    como snapshot — não FK. Vazia/None é estado normal (pauta genérica), e é o
    que toda chamada anterior a esta rodada produz.

    Campos opcionais só entram se vierem preenchidos: hook e título vazios são
    legítimos (o postprocess não desenha a cartela; o YouTube cai para o tema).
    """
    linha: dict[str, Any] = {
        "org_id": org_id,
        "tema": tema,
        "roteiro": roteiro,
        "status": "pronta",
        "origem": origem,
    }
    if hook:
        linha["hook"] = hook
    if titulo:
        linha["titulo"] = titulo
    if descricao:
        linha["descricao"] = descricao
    if categoria:
        linha["categoria"] = categoria

    resposta = sb.table("pautas").insert(linha).execute()
    return resposta.data[0]["id"]


def contar_fila_viva(sb: Client, org_id: str) -> int:
    """Vídeos desta org ainda não decididos pelo gate humano.

    Filtra por org — ao contrário do `claim_proximo_video`, que atende a fila
    inteira — porque o produtor local é de UM tenant: ele tem o `ORG_ID` do
    `.env` e a pergunta é sobre a própria fila, não a do vizinho.
    """
    resposta = (
        sb.table("videos")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .in_("status", list(FILA_VIVA))
        .execute()
    )
    return int(resposta.count or 0)


def claim_proximo_video(sb: Client, worker_id: str) -> dict[str, Any] | None:
    """Trava o próximo vídeo da fila para este worker.

    A atomicidade está no `for update skip locked` dentro da RPC — dois
    workers na mesma fila nunca pegam o mesmo registro. Não replicar essa
    lógica aqui: o banco é o contrato.
    """
    resposta = sb.rpc("claim_proximo_video", {"p_worker": worker_id}).execute()
    return resposta.data[0] if resposta.data else None


def buscar_pauta(sb: Client, pauta_id: str) -> dict[str, Any] | None:
    resposta = (
        sb.table("pautas").select(CAMPOS_PAUTA).eq("id", pauta_id).limit(1).execute()
    )
    return resposta.data[0] if resposta.data else None


def marcar(sb: Client, video_id: str, status: str, **campos: Any) -> None:
    """Move o vídeo de estado. `status` é sempre explícito — nada implícito."""
    sb.table("videos").update({"status": status, **campos}).eq("id", video_id).execute()


def listar_aguardando(sb: Client, org_id: str, limite: int) -> list[dict[str, Any]]:
    """Vídeos desta org parados no gate humano, com arquivo no disco (Rodada 16).

    O QC local só consegue inspecionar o que tem `arquivo_path`: sem o mp4 no PC
    não há frame para olhar. Filtra por org (o revisor é de UM tenant, o do `.env`)
    e por `aguardando_aprovacao` — é exatamente a fila que o gate humano enxerga, e
    a única de onde `reprovar_video` aceita reprovar.
    """
    resposta = (
        sb.table("videos")
        .select("id, org_id, arquivo_path")
        .eq("org_id", org_id)
        .eq("status", "aguardando_aprovacao")
        .not_.is_("arquivo_path", "null")
        .order("created_at")
        .limit(limite)
        .execute()
    )
    return resposta.data or []


def reprovar_qc(sb: Client, video_id: str, motivo: str) -> None:
    """Reprova um vídeo pelo QC, reusando a RPC do gate (Rodada 16).

    Delega para `reprovar_video` (abaixo) — a MESMA RPC da Sprint 6 — para o
    `sb.rpc("reprovar_video")` viver num lugar só. A RPC carrega a invariante de
    devolver a pauta para `pronta` quando não sobra vídeo vivo dela; duplicar isso
    em Python seria ter a regra do gate em dois lugares. O `service_role` recebeu
    `execute` na migration `qc_reprovar`.

    O motivo vai para `videos.erro_msg` (a RPC trunca em 500), a mesma coluna que o
    painel já mostra — o humano vê "[QC] legenda cortada" no lugar de um sumiço mudo.
    """
    reprovar_video(sb, video_id, motivo)


# ============================================================ verbos do MCP (R17)
# Invólucros finos sobre as MESMAS RPCs/selects do painel (Sprint 6). O servidor
# MCP local (`mcp_server.py`) os expõe como ferramentas para controle por linguagem
# natural. Nenhum faz `update` cru de status — a transição é sempre da RPC, que
# carrega a guarda no corpo (`where status = 'aguardando_aprovacao'` + P0002). É a
# regra "reusar a RPC, nunca duplicar a máquina de estados" do gate.


def listar_pendentes(sb: Client, org_id: str, limite: int) -> list[dict[str, Any]]:
    """Vídeos no gate humano, com tema/hook da pauta para o humano decidir por NL.

    Diferente de `listar_aguardando` (que o QC usa e traz só o caminho do arquivo),
    aqui embutimos `tema`/`hook` da pauta: quem controla por linguagem natural precisa
    reconhecer o vídeo pelo assunto, não por um uuid. Org-escopado explicitamente — a
    service_role ignora RLS, então o tenant é filtro na query, como em toda leitura aqui.
    """
    resposta = (
        sb.table("videos")
        .select("id, duracao_seg, arquivo_path, pautas(tema, hook)")
        .eq("org_id", org_id)
        .eq("status", "aguardando_aprovacao")
        .order("created_at")
        .limit(limite)
        .execute()
    )
    return resposta.data or []


def listar_pautas_prontas(sb: Client, org_id: str, limite: int) -> list[dict[str, Any]]:
    """Pautas prontas para enfileirar render, maior prioridade primeiro."""
    resposta = (
        sb.table("pautas")
        .select("id, tema, hook, prioridade")
        .eq("org_id", org_id)
        .eq("status", "pronta")
        .order("prioridade", desc=True)
        .order("created_at")
        .limit(limite)
        .execute()
    )
    return resposta.data or []


def aprovar_video(sb: Client, video_id: str) -> list[dict[str, Any]]:
    """Chama a RPC `aprovar_video` (aguardando_aprovacao -> aprovado). Levanta em P0002."""
    return sb.rpc("aprovar_video", {"p_video_id": video_id}).execute().data or []


def reprovar_video(
    sb: Client, video_id: str, motivo: str | None = None
) -> list[dict[str, Any]]:
    """Chama a RPC `reprovar_video` (aguardando_aprovacao -> reprovado). Motivo opcional."""
    return (
        sb.rpc("reprovar_video", {"p_video_id": video_id, "p_motivo": motivo})
        .execute()
        .data
        or []
    )


def enfileirar_pauta(sb: Client, pauta_id: str) -> list[dict[str, Any]]:
    """Chama a RPC `enfileirar_pauta` (pauta pronta -> em_producao + videos.na_fila)."""
    return sb.rpc("enfileirar_pauta", {"p_pauta_id": pauta_id}).execute().data or []


def concluir_render(
    sb: Client,
    video_id: str,
    arquivo_path: str,
    preview_url: str | None = None,
    thumb_url: str | None = None,
    duracao_seg: float | None = None,
) -> None:
    """Render terminou: solta o lock e entrega para o gate humano (ADR-06).

    **`preview_url` guarda o CAMINHO no Storage, não uma URL assinada.** Duas
    razões, e as duas são de segurança e não de estilo:

    1. URL assinada expira. Gravada aqui, ela apodrece: o vídeo fica na fila
       esperando aprovação por horas e o painel abre um player quebrado.
    2. URL assinada É a credencial — quem tem o link lê o arquivo, logado ou
       não. Persistir isso numa coluna é guardar bearer token em texto plano,
       e o CLAUDE.md proíbe até *logar* URL assinada.

    O painel assina a sua própria, na hora, com o JWT do usuário; a política
    `atmosfera_preview_org` é quem autoriza. Sprint 6: não usar este valor
    direto no `src` do `<video>`.
    """
    campos: dict[str, Any] = {
        "arquivo_path": arquivo_path,
        "erro_msg": None,
        "locked_by": None,
        "locked_at": None,
    }
    # Só escreve o que existe: se o upload para o Storage falhar, o vídeo ainda
    # está pronto no disco e aprovável — não é motivo para apagar coluna.
    if preview_url is not None:
        campos["preview_url"] = preview_url
    if thumb_url is not None:
        campos["thumb_url"] = thumb_url
    if duracao_seg is not None:
        campos["duracao_seg"] = duracao_seg

    marcar(sb, video_id, "aguardando_aprovacao", **campos)


def falhar(sb: Client, video_id: str, erro: BaseException | str) -> None:
    """Marca erro e SOLTA o lock.

    Soltar é o ponto: sem isso o registro fica `renderizando` para sempre e a
    fila trava num vídeo morto. `claim_proximo_video` só reconsidera quem tem
    `tentativas < 3`, então três falhas param de verdade — não é loop infinito.
    """
    marcar(
        sb,
        video_id,
        "erro",
        erro_msg=truncar_erro(str(erro)),
        locked_by=None,
        locked_at=None,
    )


def destravar_orfaos(sb: Client, minutos: int) -> int:
    """Devolve à fila o que ficou travado por worker que morreu."""
    resposta = sb.rpc("destravar_orfaos", {"p_minutos": minutos}).execute()
    return int(resposta.data or 0)


# ============================================================ publicação (S4)


def listar_aprovados(sb: Client, limite: int) -> list[dict[str, Any]]:
    """Vídeos que passaram pelo gate humano e ainda não foram publicados.

    Sem filtro de org, igual ao `claim_proximo_video`: o worker atende a fila
    inteira e cada linha carrega o seu próprio `org_id` (é o que o
    `postprocess` já faz com o caminho no Storage).
    """
    resposta = (
        sb.table("videos")
        .select("id, org_id, pauta_id, arquivo_path")
        .eq("status", "aprovado")
        .order("created_at")
        .limit(limite)
        .execute()
    )
    return resposta.data or []


def contar_enviados_desde(sb: Client, plataforma: str, desde: datetime) -> int:
    """Uploads já feitos nesta janela — a base do teto diário.

    Conta `enviado_em`, e não `created_at`/`updated_at`, porque o que interessa
    é quando a cota foi gasta (ver a migration `publicacao_enviado_em`).

    De propósito **sem filtro de org**: a cota é do projeto no Google Cloud, não
    do tenant. Duas orgs neste worker compartilham o mesmo `token.json` e,
    portanto, o mesmo teto — somar as duas é a leitura correta, e no pior caso
    erra para menos, que é o lado seguro.
    """
    resposta = (
        sb.table("publicacoes")
        .select("id", count="exact")
        .eq("plataforma", plataforma)
        .gte("enviado_em", desde.isoformat())
        .execute()
    )
    return int(resposta.count or 0)


def buscar_publicacao(
    sb: Client, video_id: str, plataforma: str
) -> dict[str, Any] | None:
    resposta = (
        sb.table("publicacoes")
        .select("id, status, external_id, url, enviado_em, agendado_para, erro_msg")
        .eq("video_id", video_id)
        .eq("plataforma", plataforma)
        .limit(1)
        .execute()
    )
    return resposta.data[0] if resposta.data else None


def ultimo_agendamento(sb: Client, plataforma: str) -> datetime | None:
    """Maior `publishAt` já marcado — o ponto de partida do próximo slot."""
    resposta = (
        sb.table("publicacoes")
        .select("agendado_para")
        .eq("plataforma", plataforma)
        .not_.is_("agendado_para", "null")
        .order("agendado_para", desc=True)
        .limit(1)
        .execute()
    )
    if not resposta.data:
        return None
    return datetime.fromisoformat(resposta.data[0]["agendado_para"])


def reservar_envio(
    sb: Client, org_id: str, video_id: str, plataforma: str, agora: datetime
) -> str:
    """Marca a cota como gasta **antes** de gastá-la. Devolve o id da linha.

    A ordem é deliberada e não é pessimismo. Se o processo morrer no meio do
    upload, a cota foi embora do mesmo jeito — mas a linha não teria registro
    disso, e no ciclo seguinte o worker acharia que tem uma vaga a mais do que
    tem. Reservar antes erra para menos uma vaga; reservar depois erra para
    mais, e o excedente falha calado até a virada do dia.

    `status` continua `pendente`: quem ainda não teve resposta da API não está
    `enviado`. Quem contabiliza cota é `enviado_em`, não o status.
    """
    resposta = (
        sb.table("publicacoes")
        .upsert(
            {
                "org_id": org_id,
                "video_id": video_id,
                "plataforma": plataforma,
                "status": "pendente",
                "enviado_em": agora.isoformat(),
                "erro_msg": None,
            },
            on_conflict="video_id,plataforma",
        )
        .execute()
    )
    return resposta.data[0]["id"]


def concluir_publicacao(
    sb: Client,
    publicacao_id: str,
    external_id: str,
    url: str | None = None,
    agendado_para: datetime | None = None,
) -> None:
    """Upload aceito. `enviado` e não `publicado`: o vídeo ainda não está no ar.

    No YouTube ele sobe privado e vira público sozinho no `publishAt`. No TikTok
    ele vira rascunho na caixa de entrada e espera você postar pelo app. Nos dois
    casos `enviado` é a verdade: saiu das nossas mãos, não está público. Quem
    carimba `publicado` é quem confirmar isso depois — hoje ninguém confirma, e
    inventar o carimbo aqui faria a tabela mentir sobre o que está no ar.

    `url` e `agendado_para` são opcionais porque o rascunho do TikTok não tem
    nenhum dos dois: não existe endereço para um post que ainda não foi postado.
    Só o que vier preenchido é escrito — mandar `None` explícito apagaria o que a
    linha já tinha numa reconciliação.
    """
    campos: dict[str, Any] = {
        "status": "enviado",
        "external_id": external_id,
        "erro_msg": None,
    }
    if url is not None:
        campos["url"] = url
    if agendado_para is not None:
        campos["agendado_para"] = agendado_para.isoformat()

    sb.table("publicacoes").update(campos).eq("id", publicacao_id).execute()


def falhar_publicacao(
    sb: Client, publicacao_id: str, erro: BaseException | str
) -> None:
    """Registra a falha sem apagar `enviado_em`: a cota foi gasta de qualquer jeito."""
    sb.table("publicacoes").update(
        {"status": "erro", "erro_msg": truncar_erro(str(erro))}
    ).eq("id", publicacao_id).execute()


# ============================================================ batimento (S7)


def registrar_batimento(
    sb: Client,
    org_id: str,
    maquina: str,
    worker: str,
    ciclos: int,
    erros_seguidos: int,
    ciclou: bool = False,
) -> None:
    """Bate: uma linha por máquina, atualizada por upsert.

    **Nenhum carimbo de tempo sai daqui.** A RPC usa o `now()` do banco para
    `visto_em`, `ciclo_em` e `subiu_em`. Se o worker mandasse o próprio relógio,
    um PC dez minutos adiantado se declararia saudável para sempre — e é
    justamente o PC esquecido, que ninguém olha, o mais provável de estar com o
    relógio à deriva.

    O que vai daqui são contadores, e só contadores. Texto de exceção fica em
    `videos.erro_msg`/`publicacoes.erro_msg`, que passaram por `descrever_erro`
    exatamente para não carregar credencial; copiar mensagem crua para cá seria
    superfície de vazamento nova sem informação nova.
    """
    sb.rpc(
        "bater",
        {
            "p_org": org_id,
            "p_maquina": maquina,
            "p_worker": worker,
            "p_ciclos": ciclos,
            "p_erros": erros_seguidos,
            "p_ciclou": ciclou,
        },
    ).execute()


def ler_batimentos(sb: Client) -> list[dict[str, Any]]:
    """Estado de cada máquina, com o atraso já calculado pelo banco.

    Vem de `saude_workers()` e não de um `select` na tabela porque a conta que
    interessa — há quantos segundos essa máquina não dá sinal — precisa do
    `now()` do banco, e o PostgREST não expõe `now()`. Feita aqui, ela usaria o
    relógio de quem pergunta, que é o mesmo relógio suspeito da linha acima.
    """
    resposta = sb.rpc("saude_workers", {}).execute()
    return resposta.data or []


# ============================================================ relatório (R10)
#
# Leituras do relatório semanal local (aposentou o Cowork). Todas filtram por
# `org_id` — o relatório é de UM tenant, o do `.env` — e todas trazem a pauta
# embutida (`pautas(tema, hook)`) numa consulta só, em vez de N+1 buscas. Campos
# explícitos, nunca `select *`: o relatório mostra hook e link, não arrasta o
# roteiro inteiro nem coluna que alguém somar depois.

# Vídeo criado na janela, com a pauta embutida — a base dos "números da semana".
CAMPOS_VIDEO_SEMANA = "status, created_at, pautas(tema, hook)"

# Vídeo decidido na janela (reprovado ou erro): o motivo mora em `erro_msg`, mas
# significa coisas diferentes conforme o status — por isso a consulta é por status.
CAMPOS_VIDEO_DECIDIDO = "status, erro_msg, tentativas, updated_at, pautas(tema, hook)"

# Publicação da janela, com a pauta pela cadeia video→pauta.
CAMPOS_PUBLICACAO_SEMANA = (
    "plataforma, status, url, publicado_em, agendado_para, erro_msg, "
    "videos(pautas(tema, hook))"
)


def videos_da_semana(sb: Client, org_id: str, desde: datetime) -> list[dict[str, Any]]:
    """Vídeos criados na janela, para os números por estado. Só leitura."""
    resposta = (
        sb.table("videos")
        .select(CAMPOS_VIDEO_SEMANA)
        .eq("org_id", org_id)
        .gte("created_at", desde.isoformat())
        .order("created_at")
        .execute()
    )
    return resposta.data or []


def videos_decididos(
    sb: Client, org_id: str, desde: datetime, status: str
) -> list[dict[str, Any]]:
    """Vídeos que entraram em `status` (reprovado|erro) dentro da janela.

    Filtra por `updated_at` porque o que importa é *quando foi decidido*, não
    quando nasceu — um vídeo antigo reprovado esta semana conta nesta semana.
    """
    resposta = (
        sb.table("videos")
        .select(CAMPOS_VIDEO_DECIDIDO)
        .eq("org_id", org_id)
        .eq("status", status)
        .gte("updated_at", desde.isoformat())
        .order("updated_at")
        .execute()
    )
    return resposta.data or []


def publicacoes_da_semana(
    sb: Client, org_id: str, desde: datetime
) -> list[dict[str, Any]]:
    """Publicações criadas na janela, com o hook pela cadeia video→pauta. Só leitura."""
    resposta = (
        sb.table("publicacoes")
        .select(CAMPOS_PUBLICACAO_SEMANA)
        .eq("org_id", org_id)
        .gte("created_at", desde.isoformat())
        .order("created_at")
        .execute()
    )
    return resposta.data or []


def pautas_por_status(sb: Client, org_id: str) -> list[str]:
    """Status de cada pauta viva da org — a base do gargalo 'pauta sem virar vídeo'."""
    resposta = (
        sb.table("pautas").select("status").eq("org_id", org_id).execute()
    )
    return [linha["status"] for linha in (resposta.data or [])]


def contar_videos_por_status(sb: Client, org_id: str, status: str) -> int:
    """Quantos vídeos da org estão AGORA em `status` (gargalo: aguardando, aprovado)."""
    resposta = (
        sb.table("videos")
        .select("id", count="exact")
        .eq("org_id", org_id)
        .eq("status", status)
        .execute()
    )
    return int(resposta.count or 0)


# ============================================================ métricas (R11)
#
# O coletor lê as publicações do YouTube e escreve o retrato de audiência que a
# Analytics API traz. Escrita com service_role (ignora RLS); o painel só lê a
# própria org (política `metricas_leitura`). Campos explícitos, como o resto.


def listar_publicacoes_youtube(sb: Client, org_id: str) -> list[dict[str, Any]]:
    """Publicações do YouTube desta org que têm `external_id` — o que dá para coletar.

    Filtra por org (o coletor é de UM tenant, o do `.env`) e exige `external_id`:
    rascunho sem id de vídeo, ou publicação de outra plataforma, não tem métrica no
    YouTube para puxar. `id` é o que a métrica referencia (FK `publicacao_id`).
    """
    resposta = (
        sb.table("publicacoes")
        .select("id, external_id, plataforma")
        .eq("org_id", org_id)
        .eq("plataforma", "youtube")
        .not_.is_("external_id", "null")
        .order("created_at")
        .execute()
    )
    return resposta.data or []


# Ranking de retenção (Rodada 12): parte de `metricas` e embute a pauta pela
# cadeia publicação→vídeo→pauta, numa consulta só. Campos explícitos: o relatório
# mostra hook, link e retenção, não arrasta roteiro nem coluna somada depois.
CAMPOS_HOOK_RETENCAO = (
    "retencao_media_pct, views, "
    "publicacoes(url, videos(pautas(tema, hook)))"
)


def hooks_por_retencao(
    sb: Client, org_id: str, limite: int
) -> list[dict[str, Any]]:
    """Publicações da org com métrica, da maior retenção para a menor. Só leitura.

    Parte de `metricas` (a coisa que se ranqueia) e sobe até a pauta pelo embed.
    Ordena por `retencao_media_pct` desc com nulos por último — um Short sem
    retenção não deve encabeçar o ranking à toa. Filtra por org como todas as
    leituras do relatório.
    """
    resposta = (
        sb.table("metricas")
        .select(CAMPOS_HOOK_RETENCAO)
        .eq("org_id", org_id)
        .order("retencao_media_pct", desc=True, nullsfirst=False)
        .limit(limite)
        .execute()
    )
    return resposta.data or []


# ================================================ produção e categorias (R21)
#
# O relógio da produção automática e as categorias que dirigem a geração. Escrita
# com service_role — pelo worker (que carimba o slot) e pelo painel LOCAL
# (`controle.py`, que roda no PC ao lado, com o mesmo `.env`). O painel web só lê
# (políticas `configuracao_producao_leitura` / `categorias_leitura`).
#
# Nenhuma destas funções levanta por "não tem linha": org sem config é o estado de
# uma instalação nova, e quem decide o padrão é o `producao.py`, num lugar só.

CAMPOS_CONFIG_PRODUCAO = "id, ativa, horarios, fuso, ultimo_slot, pausada_motivo"
CAMPOS_CATEGORIA = "id, nome, padrao"


def ler_config_producao(sb: Client, org_id: str) -> dict[str, Any] | None:
    """Config da produção automática desta org, ou None se nunca foi salva.

    None é estado normal (instalação nova), não erro: quem traduz ausência em
    padrões é `producao.config_efetiva`, para o default viver num lugar só.
    """
    resposta = (
        sb.table("configuracao_producao")
        .select(CAMPOS_CONFIG_PRODUCAO)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    return resposta.data[0] if resposta.data else None


def salvar_config_producao(
    sb: Client, org_id: str, ativa: bool, horarios: list[int], fuso: str | None = None
) -> None:
    """Grava liga/desliga e horários. Upsert em `org_id` (a tabela tem unique).

    NÃO toca `ultimo_slot` nem `pausada_motivo`: quem os escreve é o worker, ao
    cumprir ou ao pausar um slot. Se esta função os zerasse, salvar a config às
    8h05 faria o slot das 8h ser gerado de novo — a tela do dono não deve poder
    duplicar produção sem querer.

    O check `configuracao_producao_horarios_validos` recusa lista vazia ou hora
    fora de 0–23; validar aqui também seria ter a regra em dois lugares, mas quem
    chama valida ANTES para dar mensagem humana em vez de erro do Postgres.
    """
    linha: dict[str, Any] = {
        "org_id": org_id,
        "ativa": ativa,
        "horarios": horarios,
    }
    if fuso:
        linha["fuso"] = fuso
    sb.table("configuracao_producao").upsert(linha, on_conflict="org_id").execute()


def carimbar_slot(sb: Client, org_id: str, slot: str) -> None:
    """Marca o slot como cumprido e limpa a pausa. Chamado após gerar com sucesso.

    Limpar `pausada_motivo` aqui (e só aqui) é o que faz o aviso do painel sumir
    sozinho quando a produção volta a funcionar — sem uma segunda ação humana
    para "reconhecer" um alarme que já passou.
    """
    (
        sb.table("configuracao_producao")
        .upsert(
            {"org_id": org_id, "ultimo_slot": slot, "pausada_motivo": None},
            on_conflict="org_id",
        )
        .execute()
    )


def marcar_pausa(sb: Client, org_id: str, slot: str, motivo: str) -> None:
    """Registra por que o slot não gerou — e carimba o slot mesmo assim.

    Carimbar na falha é deliberado: sem isso, um Gemini sem cota faria o worker
    tentar de novo a cada 30s até a virada do dia, queimando rate limit e enchendo
    o log. O slot fica gasto, o motivo fica visível no painel, e o próximo horário
    tenta de novo naturalmente.

    `motivo` é truncado pela mesma razão que `videos.erro_msg`: quem lê é uma tela,
    e mensagem de exceção crua pode carregar mais do que se quer mostrar.
    """
    (
        sb.table("configuracao_producao")
        .upsert(
            {
                "org_id": org_id,
                "ultimo_slot": slot,
                "pausada_motivo": truncar_erro(motivo, 300),
            },
            on_conflict="org_id",
        )
        .execute()
    )


def listar_categorias(sb: Client, org_id: str) -> list[dict[str, Any]]:
    """Categorias da org, a padrão primeiro e o resto em ordem alfabética."""
    resposta = (
        sb.table("categorias")
        .select(CAMPOS_CATEGORIA)
        .eq("org_id", org_id)
        .order("padrao", desc=True)
        .order("nome")
        .execute()
    )
    return resposta.data or []


def categoria_padrao(sb: Client, org_id: str) -> str | None:
    """Nome da categoria padrão desta org, ou None se nenhuma foi marcada.

    None é estado normal: sem padrão a produção automática gera genérico, que é
    melhor que não gerar — falta de categoria não é motivo para parar a esteira.
    """
    resposta = (
        sb.table("categorias")
        .select("nome")
        .eq("org_id", org_id)
        .eq("padrao", True)
        .limit(1)
        .execute()
    )
    return resposta.data[0]["nome"] if resposta.data else None


def criar_categoria(sb: Client, org_id: str, nome: str) -> str:
    """Cria uma categoria. Devolve o id.

    `padrao` não é parâmetro: nasce falsa e vira padrão por
    `definir_categoria_padrao`, que é quem sabe desmarcar a anterior. Deixar as
    duas coisas na criação convidaria a criar uma segunda padrão sem passar pelo
    lugar que garante a exclusividade.
    """
    resposta = (
        sb.table("categorias")
        .insert({"org_id": org_id, "nome": nome.strip()})
        .execute()
    )
    return resposta.data[0]["id"]


def remover_categoria(sb: Client, org_id: str, categoria_id: str) -> None:
    """Apaga a categoria. As pautas já geradas mantêm a etiqueta (é snapshot)."""
    (
        sb.table("categorias")
        .delete()
        .eq("org_id", org_id)
        .eq("id", categoria_id)
        .execute()
    )


def definir_categoria_padrao(sb: Client, org_id: str, categoria_id: str) -> None:
    """Marca uma categoria como padrão, desmarcando a anterior.

    Duas escritas, e a ORDEM importa: desmarca todas antes de marcar a nova. Na
    ordem inversa, o índice `categorias_uma_padrao_por_org` recusaria a segunda
    padrão e a operação falharia sempre que já houvesse uma. Não é transação — o
    PostgREST não a expõe —, então a janela entre as duas escritas é uma org com
    zero padrão, que o `categoria_padrao` já trata (gera genérico). O contrário
    (duas padrões) é que seria ambíguo, e o índice o impede.
    """
    (
        sb.table("categorias")
        .update({"padrao": False})
        .eq("org_id", org_id)
        .eq("padrao", True)
        .execute()
    )
    (
        sb.table("categorias")
        .update({"padrao": True})
        .eq("org_id", org_id)
        .eq("id", categoria_id)
        .execute()
    )


def limpar_fila(sb: Client, org_id: str) -> tuple[int, int]:
    """Apaga os vídeos não publicados e recria um `na_fila` por pauta atingida.

    Devolve `(apagados, recriados)`. A RPC é uma só porque as duas metades têm de
    ser atômicas: apagar sem recriar deixaria pautas em `em_producao` sem vídeo
    nenhum apontando para elas — órfãs e invisíveis no painel.

    `aprovado`, `publicando` e `publicado` ficam de fora (a lista mora na RPC, não
    aqui — a guarda é do banco, como em toda transição deste projeto).
    """
    resposta = sb.rpc("limpar_fila", {"p_org": org_id}).execute()
    linha = (resposta.data or [{}])[0]
    return int(linha.get("apagados", 0)), int(linha.get("recriados", 0))


def upsert_metrica(
    sb: Client,
    org_id: str,
    publicacao_id: str,
    plataforma: str,
    *,
    views: int | None = None,
    minutos_assistidos: float | None = None,
    duracao_media_seg: float | None = None,
    retencao_media_pct: float | None = None,
    curtidas: int | None = None,
    coletado_em: datetime | None = None,
) -> None:
    """Grava (ou reescreve) o retrato de audiência de uma publicação.

    Upsert em `publicacao_id` (o `unique` da tabela): coletar de novo reescreve o
    retrato anterior em vez de empilhar cópias. Só campos explícitos — os valores
    vêm da Analytics API, e `None` é legítimo (métrica que a resposta não trouxe).
    """
    linha: dict[str, Any] = {
        "org_id": org_id,
        "publicacao_id": publicacao_id,
        "plataforma": plataforma,
        "views": views,
        "minutos_assistidos": minutos_assistidos,
        "duracao_media_seg": duracao_media_seg,
        "retencao_media_pct": retencao_media_pct,
        "curtidas": curtidas,
    }
    if coletado_em is not None:
        linha["coletado_em"] = coletado_em.isoformat()

    sb.table("metricas").upsert(linha, on_conflict="publicacao_id").execute()
