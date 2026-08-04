"""Testes do ciclo de publicação — contabilidade de vaga e conciliação.

O `db` é dublado inteiro, não o Supabase: o que está sob teste aqui é **quantas
vezes cada API é chamada e o que fica escrito depois**, e imitar o encadeamento
do postgrest só acrescentaria ruído entre a asserção e o que ela quer provar. O
`db.py` de verdade tem a sua própria cobertura no `test_ciclo.py`, contra o fake
de Supabase.

A vaga é o eixo, e desde a Sprint 5 são **duas contabilidades diferentes**:

| | YouTube | TikTok |
|---|---|---|
| teto | 6 uploads | 5 rascunhos pendentes |
| janela | dia do Pacífico | 24h **móveis** |
| custo de estourar | 1.600 un/upload, falha calada | 429 no meio do upload |

Por isso quase todo teste daqui termina contando `banco.enviados` — o número de
vezes que cada API foi realmente chamada — em vez de olhar só o `Resumo`.

**O teste que mais importa é o `test_tiktok_desligado_nao_prende_o_video`.** Sem
ele, um TikTok não configurado devolveria todo vídeo já publicado no YouTube para
`aprovado`, para sempre: o lote de tamanho fixo encheria de zumbis e a fila
pararia calada, com todos os componentes reportando sucesso.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import db
import publicar
from config import Config
from publishers import tiktok, youtube

LOG = logging.getLogger("teste")
ORG = UUID("0f927960-fa0d-4694-84da-366e8aaaed46")

# Meio-dia do Pacífico: longe da virada da cota, para nenhum teste depender de
# em que ponto do dia ele roda.
AGORA = datetime(2026, 8, 2, 19, 0, tzinfo=timezone.utc)

YT, TT = publicar.YOUTUBE, publicar.TIKTOK


# ---------------------------------------------------------------- fake ----
class BancoFake:
    """Substitui o módulo `db` inteiro e registra tudo que foi escrito.

    As publicações são indexadas por `(video_id, plataforma)` porque é essa a
    chave real: `unique (video_id, plataforma)` na tabela. Indexar só por vídeo
    esconderia justamente os casos que a Sprint 5 introduziu — subiu num canal,
    não subiu no outro.
    """

    def __init__(self, *, aprovados, pauta, publicacoes=None, enviados=None):
        self.aprovados = aprovados
        self.pauta = pauta
        self.publicacoes = publicacoes or {}
        self.contagem = enviados or {}

        self.videos: list[tuple[str, str, dict]] = []
        self.reservas: list[tuple[str, str]] = []
        self.concluidas: list[tuple[str, str, str | None]] = []
        self.falhas: list[tuple[str, str]] = []
        self.enviados: list[tuple[str, Path]] = []  # uma entrada = uma chamada à API

    # -- o que `publicar.py` chama --
    def listar_aprovados(self, _sb, limite):
        return self.aprovados[:limite]

    def buscar_pauta(self, _sb, _pauta_id):
        return self.pauta

    def marcar(self, _sb, video_id, status, **campos):
        self.videos.append((video_id, status, campos))

    def contar_enviados_desde(self, _sb, plataforma, _desde):
        return self.contagem.get(plataforma, 0)

    def buscar_publicacao(self, _sb, video_id, plataforma):
        return self.publicacoes.get((video_id, plataforma))

    def ultimo_agendamento(self, _sb, _plataforma):
        return None

    def reservar_envio(self, _sb, _org, video_id, plataforma, _agora):
        self.reservas.append((plataforma, video_id))
        return f"pub-{plataforma}-{video_id}"

    def concluir_publicacao(self, _sb, pub_id, external_id, url=None, agendado_para=None):
        self.concluidas.append((pub_id, external_id, url))

    def falhar_publicacao(self, _sb, pub_id, erro):
        self.falhas.append((pub_id, str(erro)))

    # -- leitura para as asserções --
    def status_de(self, video_id: str) -> list[str]:
        return [s for vid, s, _ in self.videos if vid == video_id]

    def chamadas(self, plataforma: str) -> list[Path]:
        return [arq for p, arq in self.enviados if p == plataforma]


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    """TikTok DESLIGADO por padrão — é o estado de quem ainda não criou o app.

    Deixar o padrão assim faz cada teste de TikTok ligá-lo explicitamente, o que
    mantém honesto o outro lado: os testes de YouTube provam mesmo que a
    plataforma nova não mudou o comportamento antigo.
    """
    return Config(
        supabase_url="https://exemplo.supabase.co",
        supabase_service_role_key="nao-e-uma-chave",
        org_id=ORG,
        poll_seg=30,
        orfaos_minutos=45,
        output_dir=tmp_path,
        mpt_url="http://127.0.0.1:8080",
        mpt_timeout_seg=1200,
        mpt_voz="pt-BR-AntonioNeural-Male",
        mpt_fonte="MicrosoftYaHeiBold.ttc",
        mpt_video_source="local",
        mpt_video_language="en-US",
        youtube_token=tmp_path / "token.json",
        publicar_lote=10,
    )


@pytest.fixture
def cfg_tt(cfg: Config) -> Config:
    """O mesmo, com o TikTok configurado."""
    return dataclasses.replace(
        cfg,
        tiktok_client_key="chave-do-app",
        tiktok_client_secret="nao-e-um-secret",
        tiktok_redirect_uri="https://exemplo.com/tiktok",
    )


@pytest.fixture
def mp4(tmp_path: Path) -> Path:
    arquivo = tmp_path / "pending" / "video.mp4"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_bytes(b"mp4-de-mentira")
    return arquivo


def _video(mp4: Path) -> dict:
    return {
        "id": str(uuid4()),
        "org_id": str(ORG),
        "pauta_id": str(uuid4()),
        "arquivo_path": str(mp4),
    }


def _publicacao(status: str, external_id=None, quando=AGORA) -> dict:
    return {
        "id": "pub-antiga",
        "status": status,
        "external_id": external_id,
        "enviado_em": quando.isoformat(),
    }


PAUTA = {"titulo": "Disciplina", "descricao": "linha", "hashtags": ["#mindset"]}

TOKEN_TT = tiktok.Token(
    access_token="act.nao-e-um-token",
    refresh_token="rft.nao-e-um-token",
    expira_em=AGORA + timedelta(hours=20),
    refresh_expira_em=AGORA + timedelta(days=300),
)


class SessaoFake:
    """Só precisa saber se foi fechada — nenhuma requisição passa por aqui."""

    def __init__(self):
        self.fechada = False

    def close(self):
        self.fechada = True


@pytest.fixture
def montar(monkeypatch):
    """Instala o banco falso e um envio que sempre dá certo nas duas pontas."""

    def _montar(*, aprovados, pauta=PAUTA, publicacoes=None, enviados=None):
        banco = BancoFake(
            aprovados=aprovados, pauta=pauta, publicacoes=publicacoes, enviados=enviados
        )
        for nome in (
            "listar_aprovados",
            "buscar_pauta",
            "marcar",
            "contar_enviados_desde",
            "buscar_publicacao",
            "ultimo_agendamento",
            "reservar_envio",
            "concluir_publicacao",
            "falhar_publicacao",
        ):
            monkeypatch.setattr(db, nome, getattr(banco, nome))

        monkeypatch.setattr(youtube, "carregar_credenciais", lambda _p: "credencial")

        def enviar_yt(_cred, arquivo, corpo):
            banco.enviados.append((YT, arquivo))
            n = len(banco.chamadas(YT))
            return youtube.Publicacao(
                external_id=f"yt{n}",
                url=f"https://www.youtube.com/watch?v=yt{n}",
                agendado_para=datetime.fromisoformat(
                    corpo["status"]["publishAt"].replace("Z", "+00:00")
                ),
            )

        monkeypatch.setattr(youtube, "enviar", enviar_yt)

        def enviar_tt(_token, arquivo, **_kwargs):
            banco.enviados.append((TT, arquivo))
            return tiktok.Publicacao(
                external_id=f"tt{len(banco.chamadas(TT))}",
                estado=tiktok.ESTADO_NA_CAIXA,
            )

        monkeypatch.setattr(tiktok, "enviar", enviar_tt)
        monkeypatch.setattr(tiktok, "garantir_token", lambda *a, **k: TOKEN_TT)
        banco.sessao = SessaoFake()
        monkeypatch.setattr(tiktok, "criar_sessao", lambda *a, **k: banco.sessao)
        return banco

    return _montar


# ------------------------------------------------------------ estrutura ----
def test_so_a_orquestracao_escreve_em_videos():
    """Nenhuma função de plataforma toca em `videos.status`. Lido da árvore.

    A regra do módulo é que `_enviar_youtube` e `_enviar_tiktok` escrevem só em
    `publicacoes`; quem move o vídeo é a orquestração. Ela vale por construção
    hoje, e é justo o tipo de coisa que uma linha nova quebra sem barulho — um
    `db.marcar(..., "erro")` dentro do envio do TikTok pareceria zelo e apagaria
    o `publicado` que o YouTube tinha acabado de merecer.

    Por isso o teste não exercita comportamento: ele varre o `publicar.py` com o
    `ast` e cobra o nome da função que envolve cada `db.marcar`. Falha na hora em
    que a chamada aparece no lugar errado, sem depender de alguém ter imaginado o
    cenário que a expõe.
    """
    arvore = ast.parse(inspect.getsource(publicar))
    permitidas = {"_invalidar", "_fechar_video", "_ciclo"}

    escritoras = {
        funcao.name
        for funcao in ast.walk(arvore)
        if isinstance(funcao, ast.FunctionDef)
        for no in ast.walk(funcao)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == "marcar"
    }

    assert escritoras == permitidas


# ------------------------------------------------------------ caminhos ----
def test_fila_vazia_nao_toca_em_oauth(cfg_tt, montar, monkeypatch):
    """Fila vazia é o caso comum — o worker acorda a cada 30s.

    Se o OAuth fosse carregado antes de olhar a fila, um worker sem token
    imprimiria um warning a cada meio minuto, 2.880 por dia, sobre uma
    publicação que não existia para fazer. Vale para as duas plataformas.
    """
    banco = montar(aprovados=[])
    monkeypatch.setattr(
        youtube,
        "carregar_credenciais",
        lambda _p: pytest.fail("não devia tocar em OAuth com a fila vazia"),
    )
    monkeypatch.setattr(
        tiktok,
        "garantir_token",
        lambda *a, **k: pytest.fail("nem no token do tiktok"),
    )

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert resumo == publicar.Resumo()
    assert banco.videos == []


def test_caminho_feliz_escreve_nas_duas_tabelas(cfg, montar, mp4):
    video = _video(mp4)
    banco = montar(aprovados=[video])

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert resumo == publicar.Resumo(publicados=1)
    assert banco.chamadas(YT) == [mp4]
    # `publicando` antes de chamar a API, `publicado` depois: quem olhar o
    # painel no meio do upload vê o estado certo.
    assert banco.status_de(video["id"]) == ["publicando", "publicado"]
    assert banco.concluidas == [
        (f"pub-youtube-{video['id']}", "yt1", "https://www.youtube.com/watch?v=yt1")
    ]


def test_reserva_de_cota_vem_antes_do_upload(cfg, montar, mp4, monkeypatch):
    """`enviado_em` é carimbado antes da chamada, não depois.

    Se o processo morrer no meio do upload, a cota foi gasta de qualquer jeito.
    Reservando antes, o ciclo seguinte erra para menos uma vaga; reservando
    depois, erraria para mais — e o excedente falha calado até a virada.
    """
    ordem: list[str] = []
    banco = montar(aprovados=[_video(mp4)])
    reservar, enviar = banco.reservar_envio, youtube.enviar

    def reservar_espiao(*a):
        ordem.append("reserva")
        return reservar(*a)

    def enviar_espiao(*a):
        ordem.append("upload")
        return enviar(*a)

    monkeypatch.setattr(db, "reservar_envio", reservar_espiao)
    monkeypatch.setattr(youtube, "enviar", enviar_espiao)
    publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert ordem == ["reserva", "upload"]


# ------------------------------------------------------------ teto/cota ----
def test_teto_atingido_adia_o_lote_inteiro(cfg, montar, mp4):
    banco = montar(aprovados=[_video(mp4) for _ in range(3)], enviados={YT: 6})

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert resumo == publicar.Resumo(adiados=3)
    assert banco.enviados == []
    assert banco.videos == []  # ninguém sai de `aprovado`


def test_adiar_nao_conta_como_trabalho(cfg, montar, mp4):
    """O bug que este teste existe para impedir é um loop quente.

    Com o teto estourado, todo ciclo devolve o lote como adiado. Se isso
    contasse como trabalho, o `main.loop` pularia o sono e varreria o banco em
    milissegundos, por horas, até a virada da cota.
    """
    montar(aprovados=[_video(mp4)], enviados={YT: 6})
    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert resumo.houve_trabalho is False  # o loop dorme
    assert resumo.houve_movimento is True  # mas registra o motivo


def test_teto_corta_o_lote_no_meio(cfg, montar, mp4):
    """Quatro já foram hoje: sobram duas vagas para cinco aprovados."""
    videos = [_video(mp4) for _ in range(5)]
    banco = montar(aprovados=videos, enviados={YT: 4})

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert len(banco.chamadas(YT)) == 2
    assert resumo == publicar.Resumo(publicados=2, adiados=3)
    # Os três excedentes continuam intocados em `aprovado`, prontos para a
    # virada da cota — nada de marcá-los como erro.
    tocados = {vid for vid, _, _ in banco.videos}
    assert tocados == {v["id"] for v in videos[:2]}


def test_falha_de_upload_gasta_a_vaga(cfg, montar, mp4, monkeypatch):
    """A chamada saiu e voltou 500: a cota foi debitada do mesmo jeito."""
    videos = [_video(mp4) for _ in range(2)]
    banco = montar(aprovados=videos, enviados={YT: 5})  # uma vaga só

    def explode(_cred, arquivo, _corpo):
        banco.enviados.append((YT, arquivo))
        raise OSError("deu ruim")

    monkeypatch.setattr(youtube, "enviar", explode)
    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert len(banco.chamadas(YT)) == 1
    assert resumo == publicar.Resumo(adiados=1, falhas=1)


def test_video_invalido_nao_gasta_vaga(cfg, montar, mp4):
    """Arquivo sumido morre antes da API — a vaga fica para o próximo.

    Se `invalido` decrementasse a vaga, um vídeo com o mp4 apagado consumiria
    1.600 unidades sem nunca ter falado com o Google.
    """
    perdido = _video(mp4) | {"arquivo_path": str(mp4.parent / "sumiu.mp4")}
    bom = _video(mp4)
    banco = montar(aprovados=[perdido, bom], enviados={YT: 5})  # uma vaga só

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.chamadas(YT) == [mp4]  # o segundo passou
    assert resumo == publicar.Resumo(publicados=1, falhas=1)
    assert banco.status_de(perdido["id"]) == ["erro"]


def test_pauta_sumida_tambem_e_invalida(cfg, montar, mp4):
    video = _video(mp4)
    banco = montar(aprovados=[video], pauta=None)

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.enviados == []
    assert banco.reservas == []  # nem reservou cota
    assert resumo == publicar.Resumo(falhas=1)


def test_pauta_sumida_barra_o_tiktok_tambem(cfg_tt, montar, mp4):
    """O rascunho não leva metadado nenhum — poderia subir sem pauta.

    Não sobe: pauta ausente com vídeo vivo é corrupção de banco (o
    `on delete cascade` teria levado o vídeo junto), e publicar metade de um
    estado inconsistente é pior que parar.
    """
    banco = montar(aprovados=[_video(mp4)], pauta=None)

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.enviados == []
    assert resumo == publicar.Resumo(falhas=1)


# ---------------------------------------------------------- reentrância ----
def test_retentativa_no_mesmo_dia_e_adiada(cfg, montar, mp4):
    """Falhou às 10h? Espera a virada.

    Sem isto, o mesmo vídeo seria retentado a cada ciclo e levaria as seis
    vagas do dia em meia hora — todas no mesmo mp4 quebrado.
    """
    video = _video(mp4)
    banco = montar(
        aprovados=[video],
        publicacoes={(video["id"], YT): _publicacao("erro", quando=AGORA - timedelta(hours=2))},
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.enviados == []
    assert resumo == publicar.Resumo(adiados=1)


def test_falha_de_ontem_pode_tentar_de_novo(cfg, montar, mp4):
    video = _video(mp4)
    banco = montar(
        aprovados=[video],
        publicacoes={(video["id"], YT): _publicacao("erro", quando=AGORA - timedelta(days=2))},
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.chamadas(YT) == [mp4]
    assert resumo == publicar.Resumo(publicados=1)


def test_upload_que_ja_subiu_so_fecha_o_estado(cfg, montar, mp4):
    """O processo morreu entre o upload e o `marcar`.

    Reenviar criaria um SEGUNDO vídeo no canal e gastaria mais 1.600 unidades.
    O `unique (video_id, plataforma)` guarda o banco; isto guarda o canal.
    """
    video = _video(mp4)
    banco = montar(
        aprovados=[video],
        publicacoes={(video["id"], YT): _publicacao("enviado", "ytantigo")},
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.enviados == []
    assert banco.status_de(video["id"]) == ["publicado"]
    assert resumo == publicar.Resumo(publicados=1)


def test_fechar_estado_passa_mesmo_depois_de_acabar_a_vaga(cfg, montar, mp4):
    """Fechar estado é escrita no banco, não chamada de API — o teto não vale.

    A vaga única é consumida pelo primeiro vídeo. O segundo já tinha subido: se
    o guard de vaga o barrasse junto com os outros, ele ficaria preso em
    `aprovado` sem nada a fazer, esperando cota de que não precisa.
    """
    primeiro, ja_no_ar = _video(mp4), _video(mp4)
    banco = montar(
        aprovados=[primeiro, ja_no_ar],
        publicacoes={(ja_no_ar["id"], YT): _publicacao("enviado", "ytantigo")},
        enviados={YT: 5},  # uma vaga, que o primeiro consome
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert len(banco.chamadas(YT)) == 1  # só o primeiro chamou a API
    assert banco.status_de(ja_no_ar["id"]) == ["publicado"]
    assert resumo == publicar.Resumo(publicados=2)


# ------------------------------------------------------------ sem token ----
def test_sem_token_adia_em_vez_de_derrubar_o_loop(cfg, montar, mp4, monkeypatch):
    """Sem OAuth o worker ainda renderiza. Derrubar o loop seria pior."""

    def sem_token(_p):
        raise youtube.AutorizacaoAusente("rode: uv run autorizar_youtube.py")

    banco = montar(aprovados=[_video(mp4), _video(mp4)])
    monkeypatch.setattr(youtube, "carregar_credenciais", sem_token)

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert resumo == publicar.Resumo(adiados=2)
    assert resumo.houve_trabalho is False
    assert banco.videos == []  # nada muda de estado


# ---------------------------------------------------------------- erro ----
def test_falha_marca_video_como_erro_e_registra_na_publicacao(
    cfg, montar, mp4, monkeypatch
):
    """`erro`, e não de volta para `aprovado`.

    Publicação que quebra é coisa que uma pessoa precisa ver (§ "nada é
    silencioso"). Voltar para `aprovado` faria o worker retentar sozinho — e
    aí o gate humano vira decoração.
    """
    video = _video(mp4)
    banco = montar(aprovados=[video])
    monkeypatch.setattr(
        youtube, "enviar", lambda *a: (_ for _ in ()).throw(OSError("rede caiu"))
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.status_de(video["id"]) == ["publicando", "erro"]
    assert banco.falhas == [(f"pub-youtube-{video['id']}", "OSError: rede caiu")]
    assert resumo == publicar.Resumo(falhas=1)


def test_erro_gravado_no_banco_nao_carrega_a_uri_do_upload(
    cfg, montar, mp4, monkeypatch
):
    """A URI do upload resumable leva `upload_id` — credencial de sessão.

    `str(HttpError)` a inclui inteira. Este teste é o que impede a credencial
    de ir para `publicacoes.erro_msg` e de lá para a tela do painel.
    """
    from googleapiclient.errors import HttpError

    resposta = type("R", (), {"status": 500, "reason": "erro"})()
    erro = HttpError(resposta, b"{}")
    erro.uri = "https://youtube.googleapis.com/upload?upload_id=SEGREDO"

    video = _video(mp4)
    banco = montar(aprovados=[video])
    monkeypatch.setattr(youtube, "enviar", lambda *a: (_ for _ in ()).throw(erro))

    publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    gravado = banco.falhas[0][1]
    marcado = [c for vid, s, c in banco.videos if s == "erro"][0]["erro_msg"]
    assert "SEGREDO" not in gravado
    assert "SEGREDO" not in marcado


# ---------------------------------------------------------------- corpo ----
def test_metadado_enviado_tem_rotulo_de_ia_e_agendamento(cfg, montar, mp4, monkeypatch):
    """Amarra o corpo montado ao que sai de fato — os dois lados juntos.

    `test_youtube.py` prova que `montar_corpo` põe o rótulo; aqui se prova que
    é esse corpo que chega ao `enviar`, e não outro montado pelo caminho.
    """
    corpos: list[dict] = []
    montar(aprovados=[_video(mp4)])
    enviar_ok = youtube.enviar

    def espiao(cred, arquivo, corpo):
        corpos.append(corpo)
        return enviar_ok(cred, arquivo, corpo)

    monkeypatch.setattr(youtube, "enviar", espiao)
    publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    status = corpos[0]["status"]
    assert status["containsSyntheticMedia"] is True
    assert status["privacyStatus"] == "private"
    # O atraso mínimo empurra o publishAt para o futuro: publishAt no passado
    # é recusado pela API depois de a cota já ter sido debitada.
    assert datetime.fromisoformat(status["publishAt"].replace("Z", "+00:00")) > AGORA


# ============================================================== TikTok ====
def test_tiktok_desligado_nao_prende_o_video(cfg, montar, mp4):
    """O teste mais importante do arquivo, e o que quase não existiu.

    Com o TikTok sem configurar, a leitura ingênua ("só fecha quando as duas
    plataformas resolveram") devolveria o vídeo para `aprovado` depois de já ter
    subido no YouTube. No ciclo seguinte ele voltaria na fila, o `_decidir` o
    adiaria de novo, e assim para sempre: o lote de tamanho fixo encheria de
    zumbis e a fila pararia — com todo componente reportando sucesso.

    Plataforma desligada é `pulado`, e `pulado` não impede o fechamento.
    """
    video = _video(mp4)
    banco = montar(aprovados=[video])  # `cfg` sem TIKTOK_CLIENT_KEY

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.chamadas(TT) == []
    assert banco.status_de(video["id"]) == ["publicando", "publicado"]
    assert resumo == publicar.Resumo(publicados=1)


def test_as_duas_plataformas_no_caminho_feliz(cfg_tt, montar, mp4):
    video = _video(mp4)
    banco = montar(aprovados=[video])

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.chamadas(YT) == [mp4]
    assert banco.chamadas(TT) == [mp4]
    assert resumo == publicar.Resumo(publicados=1)
    assert banco.status_de(video["id"]) == ["publicando", "publicado"]

    # Duas linhas em `publicacoes`, uma por plataforma. O rascunho fecha sem
    # `url`: ele ainda não é um post, e inventar link daria 404 no painel.
    assert banco.concluidas == [
        (f"pub-youtube-{video['id']}", "yt1", "https://www.youtube.com/watch?v=yt1"),
        (f"pub-tiktok-{video['id']}", "tt1", None),
    ]


def test_publish_id_vai_para_external_id(cfg_tt, montar, mp4):
    """Sem coluna nova: o `publish_id` é o external_id do TikTok.

    É o que o painel usa para saber que o rascunho existe, e o que o
    `unique (video_id, plataforma)` protege de duplicar.
    """
    banco = montar(aprovados=[_video(mp4)])

    publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    tiktok_concluida = [c for c in banco.concluidas if "tiktok" in c[0]][0]
    assert tiktok_concluida[1] == "tt1"


def test_log_de_sucesso_avisa_que_falta_o_rotulo_de_ia(cfg_tt, montar, mp4, caplog):
    """A API de rascunho não aceita `is_aigc` — o toggle só existe no app.

    O log é o único lugar onde isso pode ser dito na hora em que acontece. Sem
    o rótulo, a política das duas plataformas prevê remoção do conteúdo.
    """
    montar(aprovados=[_video(mp4)])

    with caplog.at_level(logging.INFO):
        publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert any(getattr(r, "falta_marcar_ia", False) for r in caplog.records)


def test_teto_de_24h_do_tiktok_e_contado_separado(cfg_tt, montar, mp4):
    """Cinco rascunhos pendentes: o TikTok fecha, o YouTube segue.

    Os dois tetos são independentes. Compartilhar contador faria o vídeo parar
    de subir no YouTube por causa de um limite que é de outra plataforma.
    """
    video = _video(mp4)
    banco = montar(aprovados=[video], enviados={TT: tiktok.TETO_24H})

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.chamadas(YT) == [mp4]
    assert banco.chamadas(TT) == []
    # Subiu num canal e o outro só adiou: o vídeo NÃO fecha, volta para
    # `aprovado` e tenta o TikTok quando a janela de 24h andar.
    assert banco.status_de(video["id"]) == ["publicando", "aprovado"]
    assert resumo == publicar.Resumo(parciais=1)


def test_parcial_conta_como_trabalho(cfg_tt, montar, mp4):
    """Gastou vaga em algum lugar = houve trabalho, e o loop não pula o sono
    achando que o ciclo foi vazio."""
    montar(aprovados=[_video(mp4)], enviados={TT: tiktok.TETO_24H})

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert resumo.houve_trabalho is True


def test_janela_do_tiktok_e_movel_e_nao_o_dia_do_pacifico(
    cfg_tt, montar, mp4, monkeypatch
):
    """As duas contagens perguntam coisas diferentes ao banco.

    O YouTube conta desde a meia-noite de Los Angeles; o TikTok, 24 horas para
    trás a partir de agora. Trocar um pelo outro dá 429 no meio de um upload,
    depois de a vaga já ter sido gasta num rascunho que não chega.
    """
    janelas: dict[str, datetime] = {}
    banco = montar(aprovados=[_video(mp4)])
    contar = banco.contar_enviados_desde

    def espiao(sb, plataforma, desde):
        janelas[plataforma] = desde
        return contar(sb, plataforma, desde)

    monkeypatch.setattr(db, "contar_enviados_desde", espiao)
    publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert janelas[TT] == AGORA - timedelta(hours=tiktok.JANELA_HORAS)
    assert janelas[YT] != janelas[TT]
    assert janelas[YT] < AGORA


def test_tiktok_sem_token_desliga_o_canal_e_o_video_fecha(cfg_tt, montar, mp4, monkeypatch):
    """Falta credencial e só uma pessoa resolve: desligado, não adiado.

    Adiar aqui recriaria exatamente o bug do vídeo preso — a diferença entre os
    dois estados é o que impede a fila de entupir enquanto ninguém autoriza.
    """
    video = _video(mp4)
    banco = montar(aprovados=[video])
    monkeypatch.setattr(
        tiktok,
        "garantir_token",
        lambda *a, **k: (_ for _ in ()).throw(
            tiktok.AutorizacaoAusente("rode: uv run autorizar_tiktok.py")
        ),
    )

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.chamadas(TT) == []
    assert banco.status_de(video["id"]) == ["publicando", "publicado"]
    assert resumo == publicar.Resumo(publicados=1)


def test_tiktok_fora_do_ar_adia_e_nao_fecha(cfg_tt, montar, mp4, monkeypatch):
    """Rede caiu na renovação: isso passa sozinho.

    O oposto do teste acima, e a distinção é toda a questão. Aqui fechar o vídeo
    o marcaria como publicado no TikTok sem nunca ter subido — e como o estado
    é terminal, ninguém tentaria de novo.
    """
    video = _video(mp4)
    banco = montar(aprovados=[video])
    monkeypatch.setattr(
        tiktok,
        "garantir_token",
        lambda *a, **k: (_ for _ in ()).throw(tiktok.TikTokIndisponivel("timeout")),
    )

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.chamadas(YT) == [mp4]  # o YouTube não é afetado
    assert banco.status_de(video["id"]) == ["publicando", "aprovado"]
    assert resumo == publicar.Resumo(parciais=1)


def test_falha_no_tiktok_leva_o_video_para_erro(cfg_tt, montar, mp4, monkeypatch):
    """Um canal falhou: o vídeo é `erro`, mesmo com o outro publicado.

    `erro` é o estado que uma pessoa vê no painel. Fechar como `publicado`
    porque o YouTube deu certo esconderia a metade que não deu.
    """
    video = _video(mp4)
    banco = montar(aprovados=[video])
    monkeypatch.setattr(
        tiktok,
        "enviar",
        lambda *a, **k: (_ for _ in ()).throw(tiktok.EnvioRecusado("formato recusado")),
    )

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.chamadas(YT) == [mp4]  # o YouTube subiu antes
    assert banco.status_de(video["id"]) == ["publicando", "erro"]
    assert resumo == publicar.Resumo(falhas=1)
    # O tipo entra na frase de propósito: `EnvioRecusado` e `TikTokIndisponivel`
    # pedem coisas diferentes de quem lê o painel — refazer o vídeo num caso,
    # esperar no outro.
    assert banco.falhas == [
        (f"pub-tiktok-{video['id']}", "EnvioRecusado: formato recusado")
    ]


def test_erro_do_tiktok_no_banco_nao_carrega_a_upload_url(cfg_tt, montar, mp4, monkeypatch):
    """A `upload_url` do init é pré-assinada: quem a tem grava na nossa sessão.

    O `requests` a coloca dentro do `str()` da exceção, e daí ela iria para
    `publicacoes.erro_msg` e para a tela do painel. Mesma regra do `upload_id`
    do YouTube, outro segredo.
    """
    import requests

    url = "https://open-upload.tiktokapis.com/upload/?upload_token=SEGREDO"
    video = _video(mp4)
    banco = montar(aprovados=[video])
    monkeypatch.setattr(
        tiktok,
        "enviar",
        lambda *a, **k: (_ for _ in ()).throw(
            requests.ConnectionError(f"HTTPSConnectionPool: falha em {url}")
        ),
    )

    publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    gravado = banco.falhas[0][1]
    marcado = [c for vid, s, c in banco.videos if s == "erro"][0]["erro_msg"]
    assert "SEGREDO" not in gravado
    assert "SEGREDO" not in marcado


def test_rascunho_que_ja_existia_nao_sobe_de_novo(cfg_tt, montar, mp4):
    """Cinco rascunhos pendentes por 24h — duplicar queima uma vaga escassa."""
    video = _video(mp4)
    banco = montar(
        aprovados=[video],
        publicacoes={(video["id"], TT): _publicacao("enviado", "v_inbox_file~antigo")},
    )

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.chamadas(TT) == []
    assert banco.chamadas(YT) == [mp4]
    assert resumo == publicar.Resumo(publicados=1)


def test_video_ja_resolvido_nos_dois_canais_so_fecha(cfg_tt, montar, mp4):
    """O processo morreu depois dos dois envios, antes do `marcar`."""
    video = _video(mp4)
    banco = montar(
        aprovados=[video],
        publicacoes={
            (video["id"], YT): _publicacao("enviado", "ytantigo"),
            (video["id"], TT): _publicacao("enviado", "ttantigo"),
        },
    )

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.enviados == []
    assert banco.reservas == []
    assert banco.status_de(video["id"]) == ["publicado"]
    assert resumo == publicar.Resumo(publicados=1)


def test_os_dois_canais_fora_do_ar_adiam_sem_escrever(cfg_tt, montar, mp4, monkeypatch):
    """Nada de pé: o lote inteiro fica em `aprovado`, intocado.

    Fechar um vídeo sem ter publicado em lugar nenhum seria mentira gravada no
    banco, e o estado é terminal.
    """
    banco = montar(aprovados=[_video(mp4), _video(mp4)])
    monkeypatch.setattr(
        youtube,
        "carregar_credenciais",
        lambda _p: (_ for _ in ()).throw(youtube.AutorizacaoAusente("sem token")),
    )
    monkeypatch.setattr(
        tiktok,
        "garantir_token",
        lambda *a, **k: (_ for _ in ()).throw(tiktok.TikTokIndisponivel("timeout")),
    )

    resumo = publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.videos == []
    assert resumo == publicar.Resumo(adiados=2)


def test_a_sessao_http_do_ciclo_e_fechada(cfg_tt, montar, mp4):
    """Uma `Session` por ciclo, e o ciclo roda a cada 30s por semanas.

    Sem o `close`, são 2.880 pools de conexão por dia esperando o coletor de
    lixo num processo que não reinicia.
    """
    banco = montar(aprovados=[_video(mp4)])

    publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.sessao.fechada is True


def test_sessao_e_fechada_mesmo_quando_o_ciclo_explode(cfg_tt, montar, mp4, monkeypatch):
    banco = montar(aprovados=[_video(mp4)])
    monkeypatch.setattr(
        db, "buscar_publicacao", lambda *a: (_ for _ in ()).throw(RuntimeError("banco caiu"))
    )

    with pytest.raises(RuntimeError):
        publicar.publicar_aprovados(None, cfg_tt, LOG, AGORA)

    assert banco.sessao.fechada is True
