"""Testes do ciclo de publicação — contabilidade de cota e conciliação.

O `db` é dublado inteiro, não o Supabase: o que está sob teste aqui é
**quantas vezes a API do YouTube é chamada e o que fica escrito depois**, e
imitar o encadeamento do postgrest só acrescentaria ruído entre a asserção e o
que ela quer provar. O `db.py` de verdade tem a sua própria cobertura no
`test_ciclo.py`, contra o fake de Supabase.

A cota é o eixo. Cada `videos.insert` custa 1.600 das 10.000 unidades do dia:
seis chances, e a sétima falha calada até a virada. Por isso quase todo teste
daqui termina contando `banco.enviados` — o número de vezes que a API foi
realmente chamada — em vez de olhar só o `Resumo`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import db
import publicar
from config import Config
from publishers import youtube

LOG = logging.getLogger("teste")
ORG = UUID("0f927960-fa0d-4694-84da-366e8aaaed46")

# Meio-dia do Pacífico: longe da virada da cota, para nenhum teste depender de
# em que ponto do dia ele roda.
AGORA = datetime(2026, 8, 2, 19, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- fake ----
class BancoFake:
    """Substitui o módulo `db` inteiro e registra tudo que foi escrito."""

    def __init__(self, *, aprovados, pauta, publicacoes=None, enviados_hoje=0):
        self.aprovados = aprovados
        self.pauta = pauta
        self.publicacoes = publicacoes or {}
        self.enviados_hoje = enviados_hoje

        self.videos: list[tuple[str, str, dict]] = []
        self.reservas: list[str] = []
        self.concluidas: list[tuple[str, str, str]] = []
        self.falhas: list[tuple[str, str]] = []
        self.enviados: list[Path] = []  # uma entrada = uma chamada à API

    # -- o que `publicar.py` chama --
    def listar_aprovados(self, _sb, limite):
        return self.aprovados[:limite]

    def buscar_pauta(self, _sb, _pauta_id):
        return self.pauta

    def marcar(self, _sb, video_id, status, **campos):
        self.videos.append((video_id, status, campos))

    def contar_enviados_desde(self, _sb, _plataforma, _desde):
        return self.enviados_hoje

    def buscar_publicacao(self, _sb, video_id, _plataforma):
        return self.publicacoes.get(video_id)

    def ultimo_agendamento(self, _sb, _plataforma):
        return None

    def reservar_envio(self, _sb, _org, video_id, _plataforma, _agora):
        self.reservas.append(video_id)
        return f"pub-{video_id}"

    def concluir_publicacao(self, _sb, pub_id, external_id, url, _agendado):
        self.concluidas.append((pub_id, external_id, url))

    def falhar_publicacao(self, _sb, pub_id, erro):
        self.falhas.append((pub_id, str(erro)))

    # -- leitura para as asserções --
    def status_de(self, video_id: str) -> list[str]:
        return [s for vid, s, _ in self.videos if vid == video_id]


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
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
        youtube_token=tmp_path / "token.json",
        publicar_lote=10,
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


PAUTA = {"titulo": "Disciplina", "descricao": "linha", "hashtags": ["#mindset"]}


@pytest.fixture
def montar(monkeypatch):
    """Instala o banco falso e um upload que sempre dá certo."""

    def _montar(*, aprovados, pauta=PAUTA, publicacoes=None, enviados_hoje=0):
        banco = BancoFake(
            aprovados=aprovados,
            pauta=pauta,
            publicacoes=publicacoes,
            enviados_hoje=enviados_hoje,
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

        def enviar(_cred, arquivo, corpo):
            banco.enviados.append(arquivo)
            return youtube.Publicacao(
                external_id=f"yt{len(banco.enviados)}",
                url=f"https://www.youtube.com/watch?v=yt{len(banco.enviados)}",
                agendado_para=datetime.fromisoformat(
                    corpo["status"]["publishAt"].replace("Z", "+00:00")
                ),
            )

        monkeypatch.setattr(youtube, "enviar", enviar)
        return banco

    return _montar


# ------------------------------------------------------------ caminhos ----
def test_fila_vazia_nao_toca_em_oauth(cfg, montar, monkeypatch):
    """Fila vazia é o caso comum — o worker acorda a cada 30s.

    Se o OAuth fosse carregado antes de olhar a fila, um worker sem token
    imprimiria um warning a cada meio minuto, 2.880 por dia, sobre uma
    publicação que não existia para fazer.
    """
    banco = montar(aprovados=[])
    monkeypatch.setattr(
        youtube,
        "carregar_credenciais",
        lambda _p: pytest.fail("não devia tocar em OAuth com a fila vazia"),
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert resumo == publicar.Resumo()
    assert banco.videos == []


def test_caminho_feliz_escreve_nas_duas_tabelas(cfg, montar, mp4):
    video = _video(mp4)
    banco = montar(aprovados=[video])

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert resumo == publicar.Resumo(publicados=1)
    assert banco.enviados == [mp4]
    # `publicando` antes de chamar a API, `publicado` depois: quem olhar o
    # painel no meio do upload vê o estado certo.
    assert banco.status_de(video["id"]) == ["publicando", "publicado"]
    assert banco.concluidas == [(f"pub-{video['id']}", "yt1", "https://www.youtube.com/watch?v=yt1")]


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
    banco = montar(aprovados=[_video(mp4) for _ in range(3)], enviados_hoje=6)

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
    montar(aprovados=[_video(mp4)], enviados_hoje=6)
    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert resumo.houve_trabalho is False  # o loop dorme
    assert resumo.houve_movimento is True  # mas registra o motivo


def test_teto_corta_o_lote_no_meio(cfg, montar, mp4):
    """Quatro já foram hoje: sobram duas vagas para cinco aprovados."""
    videos = [_video(mp4) for _ in range(5)]
    banco = montar(aprovados=videos, enviados_hoje=4)

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert len(banco.enviados) == 2
    assert resumo == publicar.Resumo(publicados=2, adiados=3)
    # Os três excedentes continuam intocados em `aprovado`, prontos para a
    # virada da cota — nada de marcá-los como erro.
    tocados = {vid for vid, _, _ in banco.videos}
    assert tocados == {v["id"] for v in videos[:2]}


def test_falha_de_upload_gasta_a_vaga(cfg, montar, mp4, monkeypatch):
    """A chamada saiu e voltou 500: a cota foi debitada do mesmo jeito."""
    videos = [_video(mp4) for _ in range(2)]
    banco = montar(aprovados=videos, enviados_hoje=5)  # uma vaga só

    def explode(_cred, _arquivo, _corpo):
        banco.enviados.append(_arquivo)
        raise OSError("deu ruim")

    monkeypatch.setattr(youtube, "enviar", explode)
    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert len(banco.enviados) == 1
    assert resumo == publicar.Resumo(adiados=1, falhas=1)


def test_video_invalido_nao_gasta_vaga(cfg, montar, mp4):
    """Arquivo sumido morre antes da API — a vaga fica para o próximo.

    Se `invalido` decrementasse a vaga, um vídeo com o mp4 apagado consumiria
    1.600 unidades sem nunca ter falado com o Google.
    """
    perdido = _video(mp4) | {"arquivo_path": str(mp4.parent / "sumiu.mp4")}
    bom = _video(mp4)
    banco = montar(aprovados=[perdido, bom], enviados_hoje=5)  # uma vaga só

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.enviados == [mp4]  # o segundo passou
    assert resumo == publicar.Resumo(publicados=1, falhas=1)
    assert banco.status_de(perdido["id"]) == ["erro"]


def test_pauta_sumida_tambem_e_invalida(cfg, montar, mp4):
    video = _video(mp4)
    banco = montar(aprovados=[video], pauta=None)

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.enviados == []
    assert banco.reservas == []  # nem reservou cota
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
        publicacoes={
            video["id"]: {
                "id": "pub-x",
                "status": "erro",
                "external_id": None,
                "enviado_em": (AGORA - timedelta(hours=2)).isoformat(),
            }
        },
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.enviados == []
    assert resumo == publicar.Resumo(adiados=1)


def test_falha_de_ontem_pode_tentar_de_novo(cfg, montar, mp4):
    video = _video(mp4)
    banco = montar(
        aprovados=[video],
        publicacoes={
            video["id"]: {
                "id": "pub-x",
                "status": "erro",
                "external_id": None,
                "enviado_em": (AGORA - timedelta(days=2)).isoformat(),
            }
        },
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert banco.enviados == [mp4]
    assert resumo == publicar.Resumo(publicados=1)


def test_upload_que_ja_subiu_so_fecha_o_estado(cfg, montar, mp4):
    """O processo morreu entre o upload e o `marcar`.

    Reenviar criaria um SEGUNDO vídeo no canal e gastaria mais 1.600 unidades.
    O `unique (video_id, plataforma)` guarda o banco; isto guarda o canal.
    """
    video = _video(mp4)
    banco = montar(
        aprovados=[video],
        publicacoes={
            video["id"]: {
                "id": "pub-x",
                "status": "enviado",
                "external_id": "ytantigo",
                "enviado_em": AGORA.isoformat(),
            }
        },
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
        publicacoes={
            ja_no_ar["id"]: {
                "id": "pub-x",
                "status": "enviado",
                "external_id": "ytantigo",
                "enviado_em": AGORA.isoformat(),
            }
        },
        enviados_hoje=5,  # uma vaga, que o primeiro consome
    )

    resumo = publicar.publicar_aprovados(None, cfg, LOG, AGORA)

    assert len(banco.enviados) == 1  # só o primeiro chamou a API
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
    assert banco.falhas == [(f"pub-{video['id']}", "OSError: rede caiu")]
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
    monkeypatch.setattr(
        youtube, "enviar", lambda *a: (_ for _ in ()).throw(erro)
    )

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
