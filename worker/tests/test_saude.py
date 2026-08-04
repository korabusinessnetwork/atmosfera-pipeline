"""Testes do health check. Sem rede, sem Supabase, sem chave.

`julgar()` não faz I/O e não olha para relógio nenhum — os atrasos chegam
calculados pelo banco. É o que torna esta suíte possível de rodar em qualquer
máquina, e é a mesma propriedade que faz o veredito sobreviver a um PC com a
hora errada. As duas coisas caem juntas: um julgamento testável e um julgamento
confiável são o mesmo desenho.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

import saude
from config import Config, ConfigInvalida

ORG = UUID("0f927960-fa0d-4694-84da-366e8aaaed46")

# Padrões do `.env.example`. Com eles: processo parado depois de 180s de
# silêncio, loop travado depois de 1830s sem fechar ciclo.
BATIMENTO = 60
TIMEOUT = 1200
POLL = 30

PARADO = saude.limite_processo(BATIMENTO)  # 180
TRAVADO = saude.limite_ciclo(TIMEOUT, POLL)  # 1830


def linha(**campos):
    base = {
        "maquina": "MAQUINA-TESTE",
        "worker": "MAQUINA-TESTE-1234",
        "subiu_em": "2026-08-02T10:00:00+00:00",
        "visto_em": "2026-08-02T10:05:00+00:00",  # 300s de pé no último carimbo
        "ciclo_em": "2026-08-02T10:04:30+00:00",
        "ciclos": 42,
        "erros_seguidos": 0,
        "atraso_seg": 10,
        "atraso_ciclo_seg": 40,
    }
    base.update(campos)
    return base


def julgar(**campos):
    return saude.julgar(linha(**campos), BATIMENTO, TIMEOUT, POLL)


# ------------------------------------------------------------- limites ------
def test_limite_de_processo_sai_da_constante_do_batimento():
    """Criterio 13: o número é derivado, não digitado. Mudar `BATIMENTO_SEG` no
    `.env` move o limite junto — senão dobrar o intervalo criaria um alarme
    permanente que ninguém pediu."""
    assert saude.limite_processo(60) == 60 * saude.FALHAS_TOLERADAS
    assert saude.limite_processo(120) == 120 * saude.FALHAS_TOLERADAS


def test_limite_de_ciclo_sai_do_timeout_do_mpt():
    """Um render legítimo pode levar `MPT_TIMEOUT_SEG`. Se o limite fosse fixo e
    alguém dobrasse o timeout, todo render longo viraria alarme — e alarme falso
    é como se desaprende a olhar para o alarme."""
    assert saude.limite_ciclo(1200, 30) == 1200 * saude.MARGEM_CICLO + 30
    assert saude.limite_ciclo(2400, 30) > saude.limite_ciclo(1200, 30)


def test_limite_de_ciclo_inclui_o_sono_da_fila_vazia():
    """Fila vazia é worker saudável dormindo `poll_seg` — não travamento."""
    assert saude.limite_ciclo(1200, 300) - saude.limite_ciclo(1200, 30) == 270


def test_o_limite_de_processo_e_menor_que_o_de_ciclo():
    """A ordem entre os dois é o desenho inteiro: máquina desligada aparece em
    ~3 min, loop travado espera o render mais longo possível terminar."""
    assert PARADO < TRAVADO


# ------------------------------------------------------------ vereditos -----
def test_sem_linha_e_sem_batimento():
    v = saude.julgar(None, BATIMENTO, TIMEOUT, POLL)
    assert v.codigo == saude.SEM_BATIMENTO == 1
    assert "nunca" in v.frase


def test_batendo_e_ciclando_e_saudavel():
    v = julgar()
    assert v.codigo == saude.SAUDAVEL == 0
    assert "MAQUINA-TESTE" in v.frase


def test_silencio_longo_e_processo_parado():
    v = julgar(atraso_seg=PARADO + 1)
    assert v.codigo == saude.PROCESSO_PARADO == 2
    assert "desligado" in v.frase or "caído" in v.frase


def test_no_limite_exato_ainda_esta_saudavel():
    """A comparação é `>`, não `>=`: uma batida que chega no segundo exato do
    limite chegou. Empate a favor do worker evita alarme por arredondamento."""
    assert julgar(atraso_seg=PARADO).codigo == saude.SAUDAVEL


def test_ciclo_velho_e_loop_travado():
    v = julgar(atraso_ciclo_seg=TRAVADO + 1)
    assert v.codigo == saude.LOOP_TRAVADO == 3
    assert "travado" in v.frase


def test_render_longo_nao_e_loop_travado():
    """O caso que justifica os dois sinais: um render de 20 min é ciclo aberto
    há 20 min, com a thread batendo normalmente. Isso é trabalho, não defeito."""
    v = julgar(atraso_ciclo_seg=TIMEOUT, atraso_seg=5)
    assert v.codigo == saude.SAUDAVEL


def test_processo_parado_ganha_de_loop_travado():
    """Com os dois estourados, o que se diz é "não bate" — é a causa provável, e
    "loop travado" mandaria alguém procurar no lugar errado."""
    v = julgar(atraso_seg=PARADO + 1, atraso_ciclo_seg=TRAVADO + 1)
    assert v.codigo == saude.PROCESSO_PARADO


# ----------------------------------------------------- travou na largada ----
def test_subiu_agora_e_ainda_nao_ciclou_e_saudavel():
    v = julgar(
        ciclo_em=None,
        atraso_ciclo_seg=None,
        subiu_em="2026-08-02T10:00:00+00:00",
        visto_em="2026-08-02T10:00:20+00:00",
        atraso_seg=5,
    )
    assert v.codigo == saude.SAUDAVEL
    assert "1º ciclo" in v.frase


def test_de_pe_ha_muito_sem_fechar_o_primeiro_ciclo_e_travado():
    """O ponto cego do Task Scheduler, e a razão de este script existir: o
    processo está vivo (a thread bate), então o agendador o dá por bom. Só o
    segundo sinal mostra que ele nunca trabalhou."""
    v = julgar(
        ciclo_em=None,
        atraso_ciclo_seg=None,
        subiu_em="2026-08-02T10:00:00+00:00",
        visto_em="2026-08-02T11:00:00+00:00",  # 1h de pé
        atraso_seg=5,  # batendo agora mesmo
    )
    assert v.codigo == saude.LOOP_TRAVADO
    assert "largada" in v.frase


def test_tempo_de_pe_nao_usa_o_relogio_local():
    """Dois carimbos do banco e um atraso do banco. Nada daqui."""
    assert (
        saude._tempo_de_pe(
            linha(
                subiu_em="2026-08-02T10:00:00+00:00",
                visto_em="2026-08-02T10:05:00+00:00",
            ),
            atraso=100,
        )
        == 400
    )


@pytest.mark.parametrize("ruim", [None, "", "ontem", 12345])
def test_tempo_de_pe_indecifravel_devolve_none(ruim):
    """Sem os carimbos não dá para acusar travamento — e chutar produziria um
    alarme que ninguém consegue confirmar."""
    assert saude._tempo_de_pe(linha(subiu_em=ruim), atraso=10) is None


def test_carimbo_ilegivel_nao_derruba_o_veredito():
    v = julgar(ciclo_em=None, atraso_ciclo_seg=None, subiu_em="quinta-feira")
    assert v.codigo == saude.SAUDAVEL


# ------------------------------------------------------- erros seguidos -----
def test_erros_seguidos_aparecem_mas_nao_mudam_o_veredito():
    """Worker que erra todo ciclo está de pé e girando; a causa mora em
    `videos.erro_msg`. Misturar as duas coisas seria juntar "o worker não
    responde" com "o MPT está sem material" — conversas diferentes, com pessoas
    diferentes."""
    v = julgar(erros_seguidos=9)
    assert v.codigo == saude.SAUDAVEL
    assert "9 erros seguidos" in v.frase


def test_sem_erros_a_frase_nao_ganha_ruido():
    assert "erros" not in julgar(erros_seguidos=0).frase


# ------------------------------------------------------------- formato ------
@pytest.mark.parametrize(
    "segundos,esperado",
    [
        (0, "0s"),
        (45, "45s"),
        (89, "89s"),
        (90, "1min"),
        (600, "10min"),
        (5399, "89min"),
        (5400, "1h30"),
        (11220, "3h07"),
    ],
)
def test_humano(segundos, esperado):
    assert saude._humano(segundos) == esperado


def test_humano_nao_mostra_tempo_negativo():
    """Só aconteceria com carimbos divergentes, mas "-3s" na tela faria quem lê
    duvidar do resto da linha."""
    assert saude._humano(-5) == "0s"


def test_escolher_acha_a_maquina():
    linhas = [linha(maquina="A"), linha(maquina="B")]
    assert saude.escolher(linhas, "B")["maquina"] == "B"
    assert saude.escolher(linhas, "C") is None


# -------------------------------------------------------------- códigos -----
def test_os_cinco_codigos_sao_distintos():
    """O código de saída É a resposta — quem vai ler isto um dia é um agendador.
    Dois estados com o mesmo número tornariam o script inútil para automação."""
    codigos = [
        saude.SAUDAVEL,
        saude.SEM_BATIMENTO,
        saude.PROCESSO_PARADO,
        saude.LOOP_TRAVADO,
        saude.NAO_SEI,
    ]
    assert codigos == [0, 1, 2, 3, 4]
    assert len(set(codigos)) == 5


# ------------------------------------------------------------------ CLI -----
@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        supabase_url="https://exemplo.supabase.co",
        supabase_service_role_key="nao-e-uma-chave",
        org_id=ORG,
        poll_seg=POLL,
        orfaos_minutos=45,
        output_dir=tmp_path,
        mpt_url="http://127.0.0.1:8080",
        mpt_timeout_seg=TIMEOUT,
        mpt_voz="pt-BR-AntonioNeural-Male",
        mpt_fonte="MicrosoftYaHeiBold.ttc",
        mpt_video_source="local",
        mpt_video_language="en-US",
        batimento_seg=BATIMENTO,
    )


@pytest.fixture
def cli(monkeypatch, cfg):
    """Monta o `main()` sem Supabase: config dublada e leitura dublada."""
    import config as configmod
    import db
    import log as logmod

    estado = {"linhas": [linha()], "erro": None, "cfg": cfg}

    def carregar():
        if isinstance(estado["cfg"], Exception):
            raise estado["cfg"]
        return estado["cfg"]

    def ler(_sb):
        if estado["erro"] is not None:
            raise estado["erro"]
        return estado["linhas"]

    monkeypatch.setattr(configmod, "carregar", carregar)
    monkeypatch.setattr(db, "criar_cliente", lambda _cfg: object())
    monkeypatch.setattr(db, "ler_batimentos", ler)
    monkeypatch.setattr(logmod, "MAQUINA", "MAQUINA-TESTE")
    return estado


def rodar(monkeypatch, *args) -> int:
    monkeypatch.setattr("sys.argv", ["saude.py", *args])
    return saude.main()


def test_cli_responde_em_uma_linha(monkeypatch, cli, capsys):
    """Criterio 14: uma linha. Health check que exige rolar a tela no celular é
    um health check que ninguém abre duas vezes."""
    codigo = rodar(monkeypatch)
    saida = capsys.readouterr().out

    assert codigo == saude.SAUDAVEL
    assert saida.count("\n") == 1
    assert saida.startswith("[SAUDAVEL]")


def test_cli_devolve_o_codigo_do_veredito(monkeypatch, cli):
    cli["linhas"] = [linha(atraso_seg=PARADO + 1)]
    assert rodar(monkeypatch) == saude.PROCESSO_PARADO


def test_cli_json_e_uma_linha_de_json(monkeypatch, cli, capsys):
    import json

    codigo = rodar(monkeypatch, "--json")
    dados = json.loads(capsys.readouterr().out)

    assert codigo == 0
    assert dados["codigo"] == 0
    assert dados["estado"] == "SAUDAVEL"
    assert set(dados) == {"codigo", "estado", "frase"}


def test_cli_json_nao_carrega_a_linha_crua(monkeypatch, cli, capsys):
    """`dados` fica no `Veredito` para quem chamar `julgar()` de dentro do
    Python; a saída do CLI leva só o que se lê. Menos superfície, e nada que
    alguém copie para um chat sem olhar."""
    rodar(monkeypatch, "--json")
    saida = capsys.readouterr().out
    assert "worker" not in saida
    assert "MAQUINA-TESTE-1234" not in saida


def test_cli_pergunta_pela_maquina_atual(monkeypatch, cli, capsys):
    cli["linhas"] = [linha(maquina="OUTRA-MAQUINA")]
    codigo = rodar(monkeypatch)

    assert codigo == saude.SEM_BATIMENTO
    assert "nunca bateu" in capsys.readouterr().out


def test_cli_aceita_maquina_explicita(monkeypatch, cli, capsys):
    cli["linhas"] = [linha(maquina="OUTRA-MAQUINA")]
    assert rodar(monkeypatch, "--maquina", "OUTRA-MAQUINA") == saude.SAUDAVEL
    assert "OUTRA-MAQUINA" in capsys.readouterr().out


def test_todas_lista_uma_linha_por_maquina(monkeypatch, cli, capsys):
    cli["linhas"] = [linha(maquina="A"), linha(maquina="B")]
    codigo = rodar(monkeypatch, "--todas")
    saida = capsys.readouterr().out

    assert codigo == saude.SAUDAVEL
    assert saida.count("\n") == 2


def test_todas_devolve_o_pior_estado(monkeypatch, cli):
    """Uma frota com uma máquina fora do ar não está saudável, e código 0 diria
    que está."""
    cli["linhas"] = [linha(maquina="A"), linha(maquina="B", atraso_seg=PARADO + 1)]
    assert rodar(monkeypatch, "--todas") == saude.PROCESSO_PARADO


def test_todas_sem_ninguem_e_sem_batimento(monkeypatch, cli):
    cli["linhas"] = []
    assert rodar(monkeypatch, "--todas") == saude.SEM_BATIMENTO


def test_supabase_fora_do_ar_e_nao_sei_e_nao_morto(monkeypatch, cli, capsys):
    """O 4 é o que separa isto de um alarme burro. Chamar falta de informação de
    "worker morto" ensina a ignorar o alarme — e um health check ignorado é pior
    que nenhum."""
    cli["erro"] = ConnectionError("sem rota para o host")
    codigo = rodar(monkeypatch)
    saida = capsys.readouterr().out

    assert codigo == saude.NAO_SEI == 4
    assert "NÃO quer dizer que o worker caiu" in saida


def test_erro_de_rede_nao_vaza_url_nem_chave(monkeypatch, cli, capsys):
    """Mensagem de cliente HTTP carrega a URL da requisição, e a URL do Supabase
    é meio caminho para a chave. Sai o nome do tipo, e só."""
    segredo = "https://projeto.supabase.co/rest/v1/rpc?apikey=eyJhbGciOi.mentira"
    cli["erro"] = ConnectionError(segredo)
    rodar(monkeypatch)
    saida = capsys.readouterr().out

    assert "supabase.co" not in saida
    assert "apikey" not in saida
    assert "ConnectionError" in saida


def test_config_invalida_e_nao_sei(monkeypatch, cli, capsys):
    """Sem `.env` o script não sabe de nada — e "não sei" é a resposta honesta.
    Dizer "worker morto" aqui seria acusar a máquina de um problema que é do
    arquivo de configuração."""
    cli["cfg"] = ConfigInvalida("SUPABASE_URL não está definida.")
    codigo = rodar(monkeypatch)

    assert codigo == saude.NAO_SEI
    assert "config inválida" in capsys.readouterr().out
