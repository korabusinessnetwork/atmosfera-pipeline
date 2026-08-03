"""Testes do publisher do TikTok.

Nenhum precisa de rede, de app registrado ou de token — a `Sessao` é um
protocolo justamente para o dublê caber aqui.

Três coisas concentram quase todas as asserções, porque são as três que custam
caro quando quebram:

1. **A aritmética de pedaço.** O TikTok manda `total_chunk_count` ser divisão
   inteira (`//`), não `ceil`. Errar aí não dá erro de código: dá upload recusado
   depois de já ter gasto uma das cinco vagas de 24 horas.
2. **Segredo em mensagem.** A `upload_url` do init é pré-assinada e o `requests`
   a coloca dentro do `str()` da exceção. De lá ela iria para
   `publicacoes.erro_msg` e para a tela do painel.
3. **Retry no lugar errado.** `PUT` de faixa de bytes repete à vontade; o
   `POST /init` repetido cria um segundo rascunho e queima outra vaga.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from publishers import tiktok

AGORA = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
MB = 1024 * 1024


# ------------------------------------------------------------- dublês ----
class RespostaFake:
    def __init__(self, corpo=None, status_code=200, texto=None):
        self._corpo = corpo
        self.status_code = status_code
        self._texto = texto

    def json(self):
        if self._texto is not None:
            raise ValueError("não é json")
        return self._corpo


class SessaoFake:
    """Registra cada chamada e devolve respostas roteirizadas."""

    def __init__(self, respostas=None, puts=None):
        self.respostas = dict(respostas or {})
        self.puts = list(puts or [])
        self.chamadas: list[tuple[str, str, dict]] = []

    def post(self, url, **kwargs):
        self.chamadas.append(("POST", url, kwargs))
        resposta = self.respostas.get(url)
        if resposta is None:
            raise AssertionError(f"POST inesperado para {url}")
        if isinstance(resposta, list):
            return resposta.pop(0)
        if isinstance(resposta, BaseException):
            raise resposta
        return resposta

    def put(self, url, **kwargs):
        self.chamadas.append(("PUT", url, kwargs))
        if self.puts:
            proxima = self.puts.pop(0)
            if isinstance(proxima, BaseException):
                raise proxima
            return proxima
        return RespostaFake(status_code=201)

    def get(self, url, **kwargs):  # pragma: no cover - o módulo não usa GET
        raise AssertionError("o publisher do TikTok não faz GET")


def _token(expira_em_horas: float = 24) -> tiktok.Token:
    return tiktok.Token(
        access_token="act.SEGREDO-DO-ACCESS",
        refresh_token="rft.SEGREDO-DO-REFRESH",
        expira_em=AGORA + timedelta(hours=expira_em_horas),
        refresh_expira_em=AGORA + timedelta(days=365),
        open_id="open-123",
    )


@pytest.fixture
def mp4(tmp_path: Path) -> Path:
    arquivo = tmp_path / "video.mp4"
    arquivo.write_bytes(b"x" * 2048)
    return arquivo


# ------------------------------------------------- 1. rascunho, não post ----
def test_so_o_endpoint_de_rascunho_existe_no_modulo():
    """Direct post é o que a auditoria trava em SELF_ONLY — não pode estar aqui.

    Não é paranoia de teste: as duas URLs diferem por uma palavra (`inbox`), e
    trocar uma pela outra num refactor renderizaria vídeos que ninguém vê, sem
    erro nenhum aparecer. Varrer as constantes e não o texto do arquivo é de
    propósito: o cabeçalho do módulo CITA o endpoint de direct post para
    explicar por que ele não é usado, e um grep cru brigaria com a documentação.
    """
    assert tiktok.ESCOPO == "video.upload"
    assert tiktok.URL_INIT_INBOX.endswith("/post/publish/inbox/video/init/")

    endpoints = [
        valor
        for nome, valor in vars(tiktok).items()
        if nome.startswith("URL_") and isinstance(valor, str)
    ]
    assert endpoints  # pega o dia em que renomearem o prefixo
    assert all(not e.endswith("/post/publish/video/init/") for e in endpoints)


def test_corpo_do_init_leva_so_source_info():
    """O endpoint de inbox não aceita `post_info` — nem legenda, nem `is_aigc`."""
    corpo = tiktok.montar_corpo_init(tiktok.Plano(tamanho=2048, chunk_size=2048, total_chunk_count=1))

    assert set(corpo) == {"source_info"}
    assert corpo["source_info"] == {
        "source": "FILE_UPLOAD",
        "video_size": 2048,
        "chunk_size": 2048,
        "total_chunk_count": 1,
    }


# --------------------------------------------- 3. aritmética de pedaço ----
def test_arquivo_pequeno_vai_inteiro_num_pedaco():
    """O caso normal deste pipeline: os mp4 do worker têm ~5 MB."""
    plano = tiktok.planejar_upload(3 * MB)

    assert plano.total_chunk_count == 1
    assert plano.chunk_size == 3 * MB
    assert list(plano.faixas()) == [(0, 3 * MB - 1)]


def test_doze_megas_dao_dois_pedacos_e_nao_tres():
    """A regra que pega desprevenido: `//`, não `ceil`.

    12 MB ÷ 5 MB = 2,4. Arredondando para cima daria um terceiro pedaço de 2 MB,
    abaixo do mínimo de 5 MB, e o TikTok recusaria o upload inteiro — depois de
    o init já ter reservado uma das cinco vagas.
    """
    plano = tiktok.planejar_upload(12 * MB)

    assert plano.chunk_size == 5 * MB
    assert plano.total_chunk_count == 2

    faixas = list(plano.faixas())
    assert faixas == [(0, 5 * MB - 1), (5 * MB, 12 * MB - 1)]
    # O último absorve o resto: 7 MB, mais que o chunk_size. É o que a doc chama
    # de "final chunk pode passar do chunk_size", e o teto dele é 128 MB.
    ultimo_primeiro, ultimo_ultimo = faixas[-1]
    assert ultimo_ultimo - ultimo_primeiro + 1 == 7 * MB
    assert ultimo_ultimo - ultimo_primeiro + 1 <= tiktok.CHUNK_ULTIMO_MAX


@pytest.mark.parametrize(
    "tamanho",
    [1, 5 * MB - 1, 5 * MB, 5 * MB + 1, 12 * MB, 64 * MB, 700 * MB, 3 * 1024 * MB],
)
def test_as_faixas_cobrem_o_arquivo_inteiro_sem_buraco(tamanho):
    """Invariante que vale para qualquer tamanho: soma das faixas == arquivo."""
    plano = tiktok.planejar_upload(tamanho)
    faixas = list(plano.faixas())

    assert len(faixas) == plano.total_chunk_count <= tiktok.MAX_CHUNKS
    assert faixas[0][0] == 0
    assert faixas[-1][1] == tamanho - 1
    assert sum(fim - inicio + 1 for inicio, fim in faixas) == tamanho
    # Sem sobreposição: cada faixa começa onde a anterior terminou.
    for (_, fim_anterior), (inicio, _) in zip(faixas, faixas[1:]):
        assert inicio == fim_anterior + 1
    # Todo pedaço não-final respeita a janela de 5 MB a 64 MB.
    for inicio, fim in faixas[:-1]:
        assert tiktok.CHUNK_MIN <= fim - inicio + 1 <= tiktok.CHUNK_MAX


def test_arquivo_vazio_e_arquivo_gigante_morrem_antes_da_api():
    """Validar aqui é economia de vaga: a recusa deles vem depois do upload."""
    with pytest.raises(tiktok.ArquivoInvalido):
        tiktok.planejar_upload(0)
    with pytest.raises(tiktok.ArquivoInvalido, match="4 GB"):
        tiktok.planejar_upload(tiktok.TAMANHO_MAX + 1)


def test_validar_arquivo_recusa_extensao_e_arquivo_sumido(tmp_path: Path, mp4: Path):
    assert tiktok.validar_arquivo(mp4) == (2048, "video/mp4")

    with pytest.raises(tiktok.ArquivoInvalido, match="não encontrado"):
        tiktok.validar_arquivo(tmp_path / "nao-existe.mp4")

    avi = tmp_path / "video.avi"
    avi.write_bytes(b"x")
    with pytest.raises(tiktok.ArquivoInvalido, match="não é aceita"):
        tiktok.validar_arquivo(avi)


# ------------------------------------------------------ 4. 6 req/min ----
def test_ritmo_espaca_as_chamadas_sem_dormir_de_verdade():
    """6 requisições por minuto por token = 10 segundos entre elas.

    Relógio e sono injetados: o teste prova o espaçamento em milissegundos, e
    ninguém tem coragem de manter um teste que leva 10 s por chamada.
    """
    relogio = [0.0]
    dormidas: list[float] = []

    def dormir(seg):
        dormidas.append(seg)
        relogio[0] += seg

    ritmo = tiktok.Ritmo(agora=lambda: relogio[0], dormir=dormir)

    ritmo.esperar()  # primeira: passa direto
    assert dormidas == []

    ritmo.esperar()  # colada na anterior: espera o intervalo inteiro
    assert dormidas == [pytest.approx(10.0)]

    relogio[0] += 30  # tempo passou sozinho — nada a esperar
    ritmo.esperar()
    assert len(dormidas) == 1


def test_intervalo_sai_do_limite_publicado():
    assert tiktok.LIMITE_REQ_MIN == 6
    assert tiktok.INTERVALO_MIN_SEG == 60 / 6
    assert tiktok.TETO_24H == 5


# ------------------------------------------------------ 6. sem vazamento ----
def test_repr_do_token_nao_carrega_credencial():
    """Um `log.info(extra={"token": token})` ou um traceback despejaria tudo."""
    texto = repr(_token())

    assert "SEGREDO-DO-ACCESS" not in texto
    assert "SEGREDO-DO-REFRESH" not in texto
    assert "open-123" in texto  # o que é útil para depurar continua lá


def test_descrever_erro_nao_devolve_a_url_pre_assinada():
    """`str(RequestException)` traz a URL da requisição — e ela É a credencial.

    Quem tem a `upload_url` grava bytes na nossa sessão de upload. Gravá-la em
    `publicacoes.erro_msg` a colocaria no banco e de lá na tela do painel.
    """
    url = "https://open-upload.tiktokapis.com/upload/?upload_token=SEGREDO"
    erro = requests.ConnectionError(f"HTTPSConnectionPool: falha em {url}")

    mensagem = tiktok.descrever_erro(erro)

    assert "SEGREDO" not in mensagem
    assert url not in mensagem
    assert "ConnectionError" in mensagem  # dá para depurar sem o segredo


def test_descrever_erro_de_dict_mantem_o_log_id():
    mensagem = tiktok.descrever_erro(
        {"code": "spam_risk_too_many_posts", "message": "limite", "log_id": "2026abc"}
    )

    assert "spam_risk_too_many_posts" in mensagem
    assert "log_id 2026abc" in mensagem


def test_token_malformado_nao_ecoa_o_conteudo_do_arquivo(tmp_path: Path):
    """O corpo do JSON é o token — a mensagem de erro não pode citá-lo."""
    caminho = tmp_path / "tiktok_token.json"
    caminho.write_text('{"access_token": "act.SEGREDO"}', encoding="utf-8")

    with pytest.raises(tiktok.AutorizacaoAusente) as capturado:
        tiktok.ler_token(caminho)

    assert "SEGREDO" not in str(capturado.value)
    assert "autorizar_tiktok.py" in str(capturado.value)


def test_falha_de_pedaco_nao_cita_a_url_de_upload(mp4: Path):
    """Nem a exceção que sobe depois de esgotar as tentativas."""
    url = "https://open-upload.tiktokapis.com/upload/?upload_token=SEGREDO"
    plano = tiktok.planejar_upload(2048)
    sessao = SessaoFake(puts=[requests.ConnectionError(f"falha em {url}")] * 9)

    with pytest.raises(tiktok.TikTokIndisponivel) as capturado:
        tiktok.enviar_pedacos(url, mp4, plano, "video/mp4", sessao, dormir=lambda _: None)

    assert "SEGREDO" not in str(capturado.value)


# ------------------------------------------------ 7. retry no lugar certo ----
def test_a_sessao_nunca_retenta_post():
    """O `POST /init` repetido cria um SEGUNDO rascunho e come outra vaga.

    O `urllib3` retenta métodos idempotentes por padrão — e POST não está na
    lista dele, mas GET/PUT/DELETE estão. Aqui só GET fica: o PUT dos pedaços é
    retentado à mão, onde dá para garantir que é a mesma faixa na mesma sessão.
    """
    sessao = tiktok.criar_sessao()
    politica = sessao.get_adapter("https://open.tiktokapis.com").max_retries

    assert politica.allowed_methods == frozenset({"GET"})
    sessao.close()


def test_pedaco_e_retentado_na_mesma_faixa_de_bytes(tmp_path: Path):
    """503 no meio do upload: repete a MESMA faixa, não pula nem duplica."""
    arquivo = tmp_path / "v.mp4"
    arquivo.write_bytes(bytes(range(10)))
    plano = tiktok.Plano(tamanho=10, chunk_size=4, total_chunk_count=2)
    sessao = SessaoFake(
        puts=[
            RespostaFake(status_code=503),  # primeira faixa tropeça
            RespostaFake(status_code=201),  # e vai na segunda tentativa
            RespostaFake(status_code=201),
        ]
    )

    tiktok.enviar_pedacos(
        "https://upload.example/x", arquivo, plano, "video/mp4", sessao, dormir=lambda _: None
    )

    faixas = [c[2]["headers"]["Content-Range"] for c in sessao.chamadas]
    assert faixas == ["bytes 0-3/10", "bytes 0-3/10", "bytes 4-9/10"]
    # O último pedaço leva o resto da divisão: 6 bytes, não 4.
    corpos = [c[2]["data"] for c in sessao.chamadas]
    assert corpos == [bytes(range(0, 4)), bytes(range(0, 4)), bytes(range(4, 10))]
    assert sessao.chamadas[-1][2]["headers"]["Content-Length"] == "6"


def test_pedaco_recusado_com_4xx_nao_e_retentado(mp4: Path):
    """400 é decisão deles. Repetir só queima tempo e o resultado é o mesmo."""
    plano = tiktok.planejar_upload(2048)
    sessao = SessaoFake(puts=[RespostaFake(status_code=400)])

    with pytest.raises(tiktok.EnvioRecusado):
        tiktok.enviar_pedacos(
            "https://upload.example/x", mp4, plano, "video/mp4", sessao, dormir=lambda _: None
        )

    assert len(sessao.chamadas) == 1


# ------------------------------------------------ 11. OAuth sem abrir porta ----
def test_url_de_autorizacao_nao_aponta_para_localhost():
    """O TikTok recusa http e localhost — e isso deixa o ADR-05 mais fácil.

    Sem callback local não existe porta escutando nem por três segundos, ao
    contrário do fluxo de desktop do Google.
    """
    url = tiktok.url_de_autorizacao("chave-do-app", "https://exemplo.com/tiktok", "st4te")

    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/?")
    assert "scope=video.upload" in url
    assert "response_type=code" in url
    assert "state=st4te" in url
    assert "127.0.0.1" not in url and "localhost" not in url


def test_codigo_da_url_confere_o_state():
    """Sem o `state`, uma URL plantada conectaria outra conta sem ninguém ver."""
    boa = "https://exemplo.com/tiktok?code=abc123%2A&state=st4te"

    assert tiktok.codigo_da_url(boa, "st4te") == "abc123*"

    with pytest.raises(tiktok.AutorizacaoAusente, match="state"):
        tiktok.codigo_da_url(boa, "outro-state")


def test_codigo_da_url_explica_o_que_falta():
    with pytest.raises(tiktok.AutorizacaoAusente, match="INTEIRA"):
        tiktok.codigo_da_url("https://exemplo.com/tiktok", "st4te")

    with pytest.raises(tiktok.AutorizacaoAusente, match="recusou"):
        tiktok.codigo_da_url(
            "https://exemplo.com/tiktok?error=access_denied"
            "&error_description=usuario+cancelou&state=st4te",
            "st4te",
        )


# --------------------------------------------------------------- token ----
def test_token_grava_e_le_de_volta(tmp_path: Path):
    caminho = tmp_path / "sub" / "tiktok_token.json"
    original = _token()

    tiktok.gravar_token(original, caminho)

    assert tiktok.ler_token(caminho) == original
    assert json.loads(caminho.read_text(encoding="utf-8"))["open_id"] == "open-123"


def test_garantir_token_nao_renova_o_que_ainda_vale(tmp_path: Path):
    caminho = tmp_path / "t.json"
    tiktok.gravar_token(_token(expira_em_horas=20), caminho)
    sessao = SessaoFake()  # qualquer chamada aqui vira AssertionError

    token = tiktok.garantir_token(caminho, "chave", "segredo", sessao, AGORA)

    assert token.access_token == "act.SEGREDO-DO-ACCESS"
    assert sessao.chamadas == []


def test_garantir_token_renova_perto_do_vencimento_e_grava(tmp_path: Path):
    """O refresh devolve um refresh_token NOVO e mata o antigo.

    Perder o retorno custaria uma reautorização manual, então grava na hora.
    """
    caminho = tmp_path / "t.json"
    tiktok.gravar_token(_token(expira_em_horas=0.05), caminho)  # 3 min: dentro da margem
    sessao = SessaoFake(
        {
            tiktok.URL_TOKEN: RespostaFake(
                {
                    "access_token": "act.NOVO",
                    "refresh_token": "rft.NOVO",
                    "expires_in": 86400,
                    "refresh_expires_in": 31536000,
                    "scope": "video.upload",
                    "open_id": "open-123",
                }
            )
        }
    )

    token = tiktok.garantir_token(caminho, "chave", "segredo", sessao, AGORA)

    assert token.access_token == "act.NOVO"
    assert token.expira_em == AGORA + timedelta(seconds=86400)
    assert tiktok.ler_token(caminho).refresh_token == "rft.NOVO"
    # form-urlencoded, não JSON — é o que a doc do /oauth/token/ pede.
    corpo = sessao.chamadas[0][2]["data"]
    assert corpo["grant_type"] == "refresh_token"


def test_refresh_vencido_pede_reautorizacao(tmp_path: Path):
    caminho = tmp_path / "t.json"
    velho = tiktok.Token(
        access_token="a",
        refresh_token="r",
        expira_em=AGORA - timedelta(days=1),
        refresh_expira_em=AGORA - timedelta(days=1),
    )
    tiktok.gravar_token(velho, caminho)

    with pytest.raises(tiktok.AutorizacaoAusente, match="autorizar_tiktok.py"):
        tiktok.garantir_token(caminho, "chave", "segredo", SessaoFake(), AGORA)


def test_sem_client_key_e_falta_de_credencial_e_nao_de_rede(tmp_path: Path):
    """`publicar.py` trata os dois casos de forma oposta — a classe importa."""
    with pytest.raises(tiktok.AutorizacaoAusente, match="TIKTOK_CLIENT_KEY"):
        tiktok.garantir_token(tmp_path / "t.json", "", "", SessaoFake(), AGORA)


def test_credencial_recusada_no_refresh_vira_autorizacao_ausente(tmp_path: Path):
    """400 do /oauth/token/ é sempre credencial, nunca rede.

    Se virasse `TikTokIndisponivel`, o `publicar.py` adiaria para sempre em vez
    de desligar o canal — e a fila entupiria esperando algo que só uma pessoa
    resolve.
    """
    caminho = tmp_path / "t.json"
    tiktok.gravar_token(_token(expira_em_horas=0), caminho)
    sessao = SessaoFake(
        {
            tiktok.URL_TOKEN: RespostaFake(
                {"error": {"code": "invalid_grant", "message": "expirado"}},
                status_code=400,
            )
        }
    )

    with pytest.raises(tiktok.AutorizacaoAusente):
        tiktok.garantir_token(caminho, "chave", "segredo", sessao, AGORA)


# --------------------------------------------------------------- envio ----
def _sessao_do_caminho_feliz(estado=tiktok.ESTADO_NA_CAIXA):
    """O envelope do TikTok é `{data, error}` — nada útil mora na raiz."""
    return SessaoFake(
        {
            tiktok.URL_INIT_INBOX: RespostaFake(
                {
                    "data": {
                        "publish_id": "v_inbox_file~1234",
                        "upload_url": "https://upload.example/?token=SEGREDO",
                    },
                    "error": {"code": "ok", "log_id": "2026abc"},
                }
            ),
            tiktok.URL_STATUS: RespostaFake({"data": {"status": estado}}),
        }
    )


def test_enviar_percorre_init_upload_status(mp4: Path):
    sessao = _sessao_do_caminho_feliz()
    ritmo = tiktok.Ritmo(agora=lambda: 0.0, dormir=lambda _: None)

    resultado = tiktok.enviar(_token(), mp4, sessao=sessao, ritmo=ritmo, dormir=lambda _: None)

    assert resultado == tiktok.Publicacao(
        external_id="v_inbox_file~1234", estado=tiktok.ESTADO_NA_CAIXA
    )
    assert [c[0] for c in sessao.chamadas] == ["POST", "PUT", "POST"]

    init = sessao.chamadas[0]
    assert init[1] == tiktok.URL_INIT_INBOX
    assert init[2]["headers"]["Authorization"] == "Bearer act.SEGREDO-DO-ACCESS"
    assert set(init[2]["json"]) == {"source_info"}


def test_ainda_processando_nao_e_erro(mp4: Path):
    """O upload já terminou; falta o TikTok transcodificar e notificar.

    Tratar isso como falha marcaria `erro` num vídeo que vai chegar ao celular
    dois minutos depois.
    """
    sessao = _sessao_do_caminho_feliz(estado="PROCESSING_UPLOAD")
    ritmo = tiktok.Ritmo(agora=lambda: 0.0, dormir=lambda _: None)

    resultado = tiktok.enviar(_token(), mp4, sessao=sessao, ritmo=ritmo, dormir=lambda _: None)

    assert resultado.estado == "PROCESSING_UPLOAD"
    assert resultado.external_id == "v_inbox_file~1234"


def test_failed_carrega_o_motivo(mp4: Path):
    sessao = SessaoFake(
        {
            tiktok.URL_INIT_INBOX: RespostaFake(
                {"data": {"publish_id": "p1", "upload_url": "https://upload.example/?t=S"}}
            ),
            tiktok.URL_STATUS: RespostaFake(
                {"data": {"status": "FAILED", "fail_reason": "file_format_check_failed"}}
            ),
        }
    )
    ritmo = tiktok.Ritmo(agora=lambda: 0.0, dormir=lambda _: None)

    with pytest.raises(tiktok.EnvioRecusado, match="file_format_check_failed"):
        tiktok.enviar(_token(), mp4, sessao=sessao, ritmo=ritmo, dormir=lambda _: None)


def test_rate_limit_vira_indisponivel_e_nao_recusa(mp4: Path):
    """429 volta a valer no próximo ciclo; recusa de conteúdo, não."""
    sessao = SessaoFake(
        {
            tiktok.URL_INIT_INBOX: RespostaFake(
                {"error": {"code": "rate_limit_exceeded", "message": "devagar"}},
                status_code=429,
            )
        }
    )

    with pytest.raises(tiktok.TikTokIndisponivel):
        tiktok.iniciar(_token(), tiktok.planejar_upload(2048), sessao)


def test_erro_de_conteudo_vira_recusa(mp4: Path):
    sessao = SessaoFake(
        {
            tiktok.URL_INIT_INBOX: RespostaFake(
                {"error": {"code": "spam_risk_too_many_posts", "message": "limite"}},
                status_code=400,
            )
        }
    )

    with pytest.raises(tiktok.EnvioRecusado, match="spam_risk_too_many_posts"):
        tiktok.iniciar(_token(), tiktok.planejar_upload(2048), sessao)


def test_resposta_nao_json_nao_derruba_o_worker():
    sessao = SessaoFake({tiktok.URL_INIT_INBOX: RespostaFake(texto="<html>502</html>")})

    with pytest.raises(tiktok.TikTokIndisponivel):
        tiktok.iniciar(_token(), tiktok.planejar_upload(2048), sessao)


def test_init_sem_publish_id_e_recusa_explicita():
    """200 com envelope pela metade. Sem isso, o `upload_url` vazio viraria um
    `PUT ""` e o erro apareceria três camadas adiante."""
    sessao = SessaoFake({tiktok.URL_INIT_INBOX: RespostaFake({"data": {"publish_id": "p1"}})})

    with pytest.raises(tiktok.EnvioRecusado, match="upload_url"):
        tiktok.iniciar(_token(), tiktok.planejar_upload(2048), sessao)
