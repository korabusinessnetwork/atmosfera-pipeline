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
) -> str:
    """Insere uma pauta pronta de origem 'ollama'. Devolve o id.

    `status` e `origem` são carimbados aqui, não recebidos: o produtor não
    escolhe — é a mesma disciplina da `pauta_nova` do painel, que fixa os dois
    no servidor. E é isso que o trigger `t_pautas_auto_enfileirar` espera para
    enfileirar sozinho até o gate.

    Campos opcionais só entram se vierem preenchidos: hook e título vazios são
    legítimos (o postprocess não desenha a cartela; o YouTube cai para o tema).
    """
    linha: dict[str, Any] = {
        "org_id": org_id,
        "tema": tema,
        "roteiro": roteiro,
        "status": "pronta",
        "origem": "ollama",
    }
    if hook:
        linha["hook"] = hook
    if titulo:
        linha["titulo"] = titulo
    if descricao:
        linha["descricao"] = descricao

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
