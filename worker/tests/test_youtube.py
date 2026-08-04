"""Testes do publisher do YouTube — sem rede, sem OAuth, sem canal.

Quase tudo aqui é função pura, e é de propósito: a parte do upload que dá para
errar sem perceber não é o HTTP, é o **metadado**. Um título de 101 caracteres
ou um `<` vindo do roteiro devolvem 400 depois de a cota já ter sido debitada —
1.600 unidades, um sexto do dia, gastas para nada.

Os dois testes que valem mais que os outros:
  · `test_rotulo_de_ia_sempre_presente` — omitir dá remoção do conteúdo (§ 7).
  · `test_dia_de_cota_e_do_pacifico` — contar no fuso errado permitiria 12
    uploads dentro do mesmo dia do YouTube, e o excedente falha calado.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from publishers import youtube

BRT = timezone(timedelta(hours=-3))
PT = ZoneInfo("America/Los_Angeles")


# ------------------------------------------------------------------ cota ----
def test_teto_sai_da_aritmetica_da_cota():
    # Não é número escolhido: 10.000 unidades/dia ÷ 1.600 por insert.
    assert youtube.TETO_DIARIO == 6
    assert youtube.COTA_DIARIA // youtube.CUSTO_INSERT == youtube.TETO_DIARIO


@pytest.mark.parametrize(
    "enviados,esperado",
    [(0, 6), (1, 5), (5, 1), (6, 0), (7, 0), (99, 0)],
)
def test_vagas_nunca_ficam_negativas(enviados, esperado):
    # Negativo viraria `range(-1)` silencioso em quem chama — e pior, um número
    # negativo somado adiante daria vaga de volta.
    assert youtube.vagas_restantes(enviados) == esperado


def test_dia_de_cota_e_do_pacifico_nao_do_seu():
    """23h de Brasília ainda é o dia anterior no Pacífico.

    Este é o teste que impede o bug de contagem: às 23h de 2/ago em BRT são 19h
    de 2/ago em PT — mesmo dia lá. Mas à 1h de 3/ago em BRT são 21h de 2/ago em
    PT, **ainda o dia 2**. Contando por dia local, os uploads das duas horas
    cairiam em janelas diferentes e o worker liberaria 12 num único dia de cota.
    """
    noite = datetime(2026, 8, 2, 23, 0, tzinfo=BRT)
    madrugada = datetime(2026, 8, 3, 1, 0, tzinfo=BRT)

    assert youtube.inicio_do_dia_de_cota(noite) == youtube.inicio_do_dia_de_cota(
        madrugada
    )
    # E a virada é meia-noite no Pacífico, não em Brasília.
    assert youtube.inicio_do_dia_de_cota(noite).astimezone(PT).hour == 0


def test_dia_de_cota_vira_de_fato_na_meia_noite_do_pacifico():
    antes = datetime(2026, 8, 2, 23, 59, tzinfo=PT)
    depois = datetime(2026, 8, 3, 0, 1, tzinfo=PT)
    assert youtube.inicio_do_dia_de_cota(antes) != youtube.inicio_do_dia_de_cota(depois)
    assert youtube.inicio_do_dia_de_cota(depois) - youtube.inicio_do_dia_de_cota(
        antes
    ) == timedelta(days=1)


def test_dia_de_cota_sai_em_utc():
    # Quem consome isso é `db.contar_enviados_desde`, que serializa para o
    # Postgres. UTC evita depender de como o postgrest interpreta o offset.
    inicio = youtube.inicio_do_dia_de_cota(datetime(2026, 8, 2, 12, tzinfo=BRT))
    assert inicio.tzinfo is timezone.utc


# ----------------------------------------------------------------- slots ----
def test_primeiro_slot_respeita_o_atraso_minimo():
    agora = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    # publishAt no passado é recusado pela API, e o upload em si leva tempo.
    assert youtube.proximo_slot(agora, None, 30, 180) == agora + timedelta(minutes=30)


def test_slot_seguinte_espaca_a_partir_do_ultimo_agendado():
    agora = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    ultimo = datetime(2026, 8, 2, 18, 0, tzinfo=timezone.utc)
    assert youtube.proximo_slot(agora, ultimo, 30, 180) == ultimo + timedelta(hours=3)


def test_agendamento_antigo_nao_puxa_o_slot_para_o_passado():
    # Fila parada há dias: o último agendado é velho, mas publishAt tem que
    # continuar no futuro. Vence o atraso mínimo, não o espaçamento.
    agora = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    antigo = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
    assert youtube.proximo_slot(agora, antigo, 30, 180) == agora + timedelta(minutes=30)


def test_rfc3339_e_o_formato_que_a_api_espera():
    momento = datetime(2026, 8, 2, 15, 30, 0, tzinfo=BRT)
    assert youtube._rfc3339(momento) == "2026-08-02T18:30:00Z"


# ------------------------------------------------------------- metadados ----
def test_rotulo_de_ia_sempre_presente():
    """§ 7: o rótulo é obrigatório e a consequência de omitir é remoção."""
    corpo = youtube.montar_corpo({"titulo": "x"}, _quando(), "22")
    assert corpo["status"]["containsSyntheticMedia"] is True


def test_sobe_privado_com_agendamento():
    # `publishAt` só é aceito com privacidade `private` — os dois andam juntos.
    # E é o que o ADR-06 pede: nada sobe público direto.
    quando = _quando()
    corpo = youtube.montar_corpo({"titulo": "x"}, quando, "22")
    assert corpo["status"]["privacyStatus"] == "private"
    assert corpo["status"]["publishAt"] == youtube._rfc3339(quando)


def test_publico_infantil_e_declarado():
    corpo = youtube.montar_corpo({"titulo": "x"}, _quando(), "22")
    assert corpo["status"]["selfDeclaredMadeForKids"] is False


def test_setas_do_roteiro_nao_derrubam_o_upload():
    """`<` e `>` devolvem 400 — e quem escreve a pauta é um LLM."""
    corpo = youtube.montar_corpo(
        {"titulo": "hook -> corpo <b>", "descricao": "a <br> b"}, _quando(), "22"
    )
    assert "<" not in corpo["snippet"]["title"]
    assert ">" not in corpo["snippet"]["title"]
    assert "<" not in corpo["snippet"]["description"]


def test_titulo_longo_e_cortado_no_limite():
    corpo = youtube.montar_corpo({"titulo": "a" * 300}, _quando(), "22")
    assert len(corpo["snippet"]["title"]) == youtube.LIMITE_TITULO


def test_titulo_cai_para_o_tema_e_depois_para_o_padrao():
    # A pauta pode vir sem título: o Cowork escreve, e escrita de LLM falha.
    # Subir sem título nenhum é pior que subir com um genérico.
    assert (
        youtube.montar_corpo({"tema": "Disciplina"}, _quando(), "22")["snippet"]["title"]
        == "Disciplina"
    )
    assert youtube.montar_corpo({}, _quando(), "22")["snippet"]["title"] == "Atmosfera"


def test_tags_saem_sem_cerquilha_e_sem_repetir():
    # `snippet.tags` não usa `#`: o caractere só consome o limite de 500.
    tags = youtube.montar_tags(["#mindset", "#Mindset", "#disciplina", "", "#"])
    assert tags == ["mindset", "disciplina"]


def test_tags_param_no_limite_de_caracteres():
    # Distintas de propósito: repetidas o corte viria da deduplicação, e o teste
    # passaria sem nunca exercitar o limite de 500.
    tags = youtube.montar_tags([f"#{n:03d}{'a' * 97}" for n in range(20)])
    assert tags  # não corta tudo
    assert sum(len(t) for t in tags) <= youtube.LIMITE_TAGS_CHARS


def test_descricao_leva_no_maximo_quinze_hashtags():
    """Passando de 15 o YouTube ignora TODAS, não só o excedente."""
    hashtags = [f"#tag{n}" for n in range(40)]
    descricao = youtube.montar_descricao("corpo", hashtags)
    assert descricao.count("#") == youtube.MAX_HASHTAGS


def test_descricao_longa_e_cortada():
    corpo = youtube.montar_corpo({"descricao": "a" * 9000}, _quando(), "22")
    assert len(corpo["snippet"]["description"]) <= youtube.LIMITE_DESCRICAO


def test_pauta_sem_hashtags_nao_quebra():
    corpo = youtube.montar_corpo(
        {"titulo": "x", "descricao": None, "hashtags": None}, _quando(), "22"
    )
    assert corpo["snippet"]["tags"] == []
    assert corpo["snippet"]["description"] == ""


def test_idioma_declarado_como_en_us():
    # Canal virou en-US (Rodada 5): o metadado de idioma acompanha o áudio.
    corpo = youtube.montar_corpo({"titulo": "x"}, _quando(), "22")
    assert corpo["snippet"]["defaultLanguage"] == "en-US"
    assert corpo["snippet"]["defaultAudioLanguage"] == "en-US"


# ----------------------------------------------------------------- escopo ----
def test_escopo_e_o_minimo_que_resolve():
    """Os outros escopos dão escrita no canal inteiro — inclusive apagar vídeo."""
    assert youtube.ESCOPOS == ["https://www.googleapis.com/auth/youtube.upload"]


# ------------------------------------------------------------ credenciais ----
def test_token_ausente_diz_o_comando_que_resolve(tmp_path):
    with pytest.raises(youtube.AutorizacaoAusente) as erro:
        youtube.carregar_credenciais(tmp_path / "token.json")
    assert "autorizar_youtube.py" in str(erro.value)


def test_token_malformado_nao_vira_traceback_de_json(tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    with pytest.raises(youtube.AutorizacaoAusente):
        youtube.carregar_credenciais(token)


def test_carregar_credenciais_default_e_so_upload(tmp_path):
    """O coletor (Rodada 11) passa ESCOPOS_TODOS; o default segue só upload, para
    o publisher não alargar o que precisa. Zero regressão no upload."""
    import inspect

    assert inspect.signature(youtube.carregar_credenciais).parameters[
        "escopos"
    ].default == youtube.ESCOPOS
    # e passar o escopo de analytics não muda o caminho de token ausente
    with pytest.raises(youtube.AutorizacaoAusente):
        youtube.carregar_credenciais(tmp_path / "x.json", youtube.ESCOPOS_TODOS)


def test_client_secret_ausente_explica_onde_pegar(tmp_path):
    with pytest.raises(youtube.ConfigYoutube) as erro:
        youtube.autorizar(tmp_path / "nao-existe.json", tmp_path / "token.json")
    assert "Desktop app" in str(erro.value)


# ------------------------------------------------------------------ erro ----
def test_erro_http_nao_arrasta_a_uri_de_upload():
    """A URI do upload resumable leva `upload_id` — credencial de sessão.

    `str(HttpError)` inclui a URI inteira. Gravar isso em `publicacoes.erro_msg`
    colocaria a credencial no banco e, de lá, na tela do painel.
    """
    from googleapiclient.errors import HttpError

    resposta = type("R", (), {"status": 503, "reason": "Service Unavailable"})()
    erro = HttpError(resposta, b'{"error": {"message": "backend error"}}')
    erro.uri = "https://youtube.googleapis.com/upload/...&upload_id=SEGREDO"

    texto = youtube.descrever_erro(erro)
    assert "SEGREDO" not in texto
    assert "503" in texto


def test_erro_comum_vira_classe_mais_mensagem():
    texto = youtube.descrever_erro(OSError("disco cheio"))
    assert texto == "OSError: disco cheio"


# ---------------------------------------------------------------- upload ----
class _Requisicao:
    """Imita `videos().insert(...)`: devolve pedaços até responder."""

    def __init__(self, erros: list[Exception], resposta: dict):
        self.erros = list(erros)
        self.resposta = resposta
        self.chamadas = 0

    def next_chunk(self):
        self.chamadas += 1
        if self.erros:
            raise self.erros.pop(0)
        return None, self.resposta


def _montar_servico(monkeypatch, requisicao, inserts: list):
    class _Videos:
        def insert(self, **kwargs):
            inserts.append(kwargs)
            return requisicao

    class _Servico:
        def videos(self):
            return _Videos()

    monkeypatch.setattr(youtube, "build", lambda *a, **k: _Servico())
    monkeypatch.setattr(youtube, "MediaFileUpload", lambda *a, **k: object())


def _http_erro(status: int):
    from googleapiclient.errors import HttpError

    resposta = type("R", (), {"status": status, "reason": "erro"})()
    return HttpError(resposta, b"{}")


@pytest.fixture
def mp4(tmp_path):
    arquivo = tmp_path / "video.mp4"
    arquivo.write_bytes(b"mp4-de-mentira")
    return arquivo


def test_upload_devolve_id_e_url(monkeypatch, mp4):
    requisicao = _Requisicao([], {"id": "abc123"})
    inserts: list = []
    _montar_servico(monkeypatch, requisicao, inserts)

    quando = _quando()
    corpo = youtube.montar_corpo({"titulo": "x"}, quando, "22")
    resultado = youtube.enviar(None, mp4, corpo, dormir=lambda _s: None)

    assert resultado.external_id == "abc123"
    assert resultado.url == "https://www.youtube.com/watch?v=abc123"
    assert resultado.agendado_para == quando.replace(microsecond=0)


def test_retry_retoma_a_sessao_e_nao_refaz_o_insert(monkeypatch, mp4):
    """O ponto do teste é o `len(inserts) == 1`.

    Retomar o `next_chunk()` reaproveita a mesma sessão e não cobra cota de
    novo. Recriar o insert cobraria mais 1.600 unidades E criaria um segundo
    vídeo no canal — a mesma armadilha da Sprint 2, aqui com fatura.
    """
    requisicao = _Requisicao([_http_erro(503), _http_erro(500)], {"id": "ok"})
    inserts: list = []
    _montar_servico(monkeypatch, requisicao, inserts)

    dormidas: list[float] = []
    resultado = youtube.enviar(
        None, mp4, youtube.montar_corpo({}, _quando(), "22"), dormir=dormidas.append
    )

    assert resultado.external_id == "ok"
    assert len(inserts) == 1
    assert requisicao.chamadas == 3
    assert dormidas == [2, 4]  # backoff exponencial


def test_erro_de_cliente_nao_e_retentado(monkeypatch, mp4):
    """403 é cota estourada ou permissão — repetir só queima o que sobrou."""
    from googleapiclient.errors import HttpError

    requisicao = _Requisicao([_http_erro(403)], {"id": "nunca"})
    _montar_servico(monkeypatch, requisicao, [])

    with pytest.raises(HttpError):
        youtube.enviar(
            None, mp4, youtube.montar_corpo({}, _quando(), "22"), dormir=lambda _s: None
        )
    assert requisicao.chamadas == 1


def test_retry_desiste_depois_do_teto(monkeypatch, mp4):
    from googleapiclient.errors import HttpError

    requisicao = _Requisicao([_http_erro(503)] * 10, {"id": "nunca"})
    _montar_servico(monkeypatch, requisicao, [])

    with pytest.raises(HttpError):
        youtube.enviar(
            None, mp4, youtube.montar_corpo({}, _quando(), "22"), dormir=lambda _s: None
        )
    assert requisicao.chamadas == youtube.MAX_RETRY_PEDACO + 1


def test_upload_nao_notifica_inscritos(monkeypatch, mp4):
    # O vídeo entra privado: não há a quem notificar no instante do insert.
    requisicao = _Requisicao([], {"id": "x"})
    inserts: list = []
    _montar_servico(monkeypatch, requisicao, inserts)

    youtube.enviar(None, mp4, youtube.montar_corpo({}, _quando(), "22"))
    assert inserts[0]["notifySubscribers"] is False
    assert inserts[0]["part"] == "snippet,status"


def test_arquivo_sumido_falha_antes_de_gastar_cota(tmp_path):
    with pytest.raises(FileNotFoundError):
        youtube.enviar(None, tmp_path / "nao-existe.mp4", {})


def _quando() -> datetime:
    return datetime(2026, 8, 2, 18, 30, tzinfo=timezone.utc)
