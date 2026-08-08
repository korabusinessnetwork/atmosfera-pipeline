"""Testes do produtor de pauta local. Nenhum toca rede nem sobe Ollama.

O que está sob teste é o que quebra calado: o parser de JSON de LLM (o modelo
devolve fence, prosa em volta, objeto quando se pediu lista), a regra de
backpressure (teto inclusivo) e a orquestração que não pode inserir nada quando
a fila está cheia nem quando o Ollama caiu.
"""

from __future__ import annotations

import json
import re
import types
from pathlib import Path

import pytest
import requests

import db
import duracao
import pauta_local as pl

# A identidade e o produtor vivem lado a lado: worker/tests → ../../memory.
IDENTIDADE = Path(__file__).resolve().parents[2] / "memory" / "00_IDENTIDADE.md"


# ---------------------------------------------------------------- fakes ----
class _RespFake:
    def __init__(self, corpo=None, *, status=200):
        self._corpo = corpo
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f"HTTP {self._status}")

    def json(self):
        if self._corpo is None:
            raise ValueError("sem corpo json")
        return self._corpo


_AUSENTE = object()   # sentinela: distingue "não passei" de "passei None de propósito"


class SessaoFake:
    """Dublê de `requests.Session` que devolve um conteúdo fixo do Ollama."""

    def __init__(self, conteudo=_AUSENTE, *, corpo=_AUSENTE, erro=None):
        if corpo is not _AUSENTE:
            self._resp = _RespFake(corpo)
        elif conteudo is not _AUSENTE:
            self._resp = _RespFake({"message": {"content": conteudo}})
        else:
            self._resp = _RespFake({"message": {}})
        self._erro = erro
        self.chamadas: list[dict] = []

    def post(self, url, json=None, **_kwargs):
        self.chamadas.append({"url": url, "json": json})
        if self._erro:
            raise self._erro
        return self._resp


class SbFake:
    """Dublê mínimo do cliente Supabase para o db.py, encadeável."""

    def __init__(self, *, count=0):
        self._count = count
        self.inserido: dict | None = None
        self._filtros: dict = {}
        self._in: tuple | None = None

    def table(self, _nome):
        return self

    def insert(self, linha):
        self.inserido = linha
        return self

    def select(self, _cols, count=None):
        self._count_mode = count
        return self

    def eq(self, k, v):
        self._filtros[k] = v
        return self

    def in_(self, k, vals):
        self._in = (k, vals)
        return self

    def execute(self):
        if self.inserido is not None:
            return types.SimpleNamespace(data=[{"id": "pauta-nova-1"}], count=None)
        return types.SimpleNamespace(data=[], count=self._count)


# ---------------------------------------------------------------- fila_cheia
def test_fila_cheia_e_inclusiva():
    assert pl.fila_cheia(20, 20) is True     # no teto já barra
    assert pl.fila_cheia(19, 20) is False
    assert pl.fila_cheia(21, 20) is True


# ---------------------------------------------------------------- hook_longo
def test_hook_longo_no_limite():
    assert pl.hook_longo("a" * 88) is False
    assert pl.hook_longo("a" * 89) is True
    assert pl.hook_longo(None) is False
    assert pl.hook_longo("") is False


# ------------------------------------------------------------ linhas_do_roteiro
def test_linhas_do_roteiro_conta_as_com_conteudo():
    assert pl.linhas_do_roteiro("a\nb\nc\nd\ne") == 5


def test_linhas_do_roteiro_ignora_branco():
    # `"a\n\n\nb"` são DUAS falas, não quatro. Contar as brancas faria um roteiro
    # de duas linhas passar por cinco — e o defeito medido é falta de linha.
    assert pl.linhas_do_roteiro("a\n\n\nb") == 2
    assert pl.linhas_do_roteiro("a\n   \nb") == 2


def test_linhas_do_roteiro_sem_texto_nao_estoura():
    assert pl.linhas_do_roteiro(None) == 0
    assert pl.linhas_do_roteiro("") == 0
    assert pl.linhas_do_roteiro("   \n  ") == 0


# -------------------------------------------------------- roteiro_fora_de_forma
def _linhas(n: int) -> str:
    return "\n".join(f"linha {i}" for i in range(n))


def test_roteiro_no_alvo_esta_em_forma():
    # O alvo virou 16 linhas na R31, quando o mínimo de duração subiu para 30s. A
    # linha continua sendo a CURVA (a cadência de ~2s por batida); quem responde por
    # segundo passou a ser a contagem de palavras.
    assert pl.roteiro_fora_de_forma(_linhas(pl.LINHAS_DO_ROTEIRO)) is False


def test_roteiro_com_menos_linhas_e_flagrado():
    # O defeito medido na R26: gerações vinham com menos linhas que o alvo. Falta
    # batida do meio, e o fecho aterrissa antes de a consequência acontecer.
    assert pl.roteiro_fora_de_forma(_linhas(pl.LINHAS_DO_ROTEIRO - 1)) is True
    assert pl.roteiro_fora_de_forma(_linhas(8)) is True   # o alvo anterior
    assert pl.roteiro_fora_de_forma(_linhas(5)) is True   # o alvo de antes dele
    assert pl.roteiro_fora_de_forma("só o hook") is True


def test_roteiro_mais_longo_nao_e_flagrado():
    # Nenhum dos 18 ouros passa do alvo. Flagrar o mais longo seria inventar um
    # problema que ninguém tem, e flag falso ensina a ignorar o aviso.
    assert pl.roteiro_fora_de_forma(_linhas(pl.LINHAS_DO_ROTEIRO + 1)) is False


def test_forma_e_duracao_sao_perguntas_DIFERENTES():
    # O erro que custou duas rodadas, agora com teste: contar linha NÃO mede
    # duração. Dezesseis linhas de duas palavras têm a forma perfeita e rendem um
    # vídeo de 11 segundos — que é justamente o que o dono relatou. Se algum dia
    # alguém reunificar os dois critérios, este caso cai.
    magro = _linhas(pl.LINHAS_DO_ROTEIRO)
    assert pl.roteiro_fora_de_forma(magro) is False
    assert duracao.roteiro_curto_demais(magro) is True


def test_roteiro_vazio_e_flagrado_sem_estourar():
    # `limpar_pauta` já descarta antes de chegar aqui; o contrato é não explodir.
    assert pl.roteiro_fora_de_forma(None) is True
    assert pl.roteiro_fora_de_forma("") is True


# ------------------------------------------------------------- abertura do fecho
def test_abertura_do_fecho_normaliza():
    assert pl.abertura_do_fecho("l1\nl2\nSame door. Still closed.") == "same"
    assert pl.abertura_do_fecho("l1\n\"Until\" it ends") == "until"


def test_abertura_do_fecho_sem_texto():
    assert pl.abertura_do_fecho(None) == ""
    assert pl.abertura_do_fecho("  \n  ") == ""


def _com_roteiro(*fechos: str) -> list[dict]:
    return [{"roteiro": f"h\nl2\nl3\nl4\n{fecho}"} for fecho in fechos]


def test_conta_fechos_que_abrem_igual():
    # O caso real medido na R26: quatro dos seis fechos abriam com "Same".
    pautas = _com_roteiro(
        "Same door. Still closed.",
        "Same calendar. Still empty.",
        "No decision. Still waiting.",
        "Same heart. Still alone.",
    )
    assert pl.fechos_com_mesma_abertura(pautas) == 3


def test_lote_variado_nao_acusa_repeticao():
    pautas = _com_roteiro("Same door. Still closed.", "There when the battery dies")
    assert pl.fechos_com_mesma_abertura(pautas) == 0


def test_par_isolado_nao_e_molde():
    # Dois abrindo igual é coincidência — os próprios exemplos-ouro fazem isso duas
    # vezes. Flagrar o par ensinaria a ignorar o contador.
    pautas = _com_roteiro("The alarm rings. Nothing answers.", "The silence stays")
    assert pl.fechos_com_mesma_abertura(pautas) == 0


def test_roteiro_truncado_nao_entra_na_contagem():
    # Dois roteiros vazios teriam abertura "" e contariam como "mesma abertura" —
    # o número mentiria sobre um defeito que não existe.
    assert pl.fechos_com_mesma_abertura([{"roteiro": ""}, {"roteiro": None}]) == 0


def test_os_18_exemplos_ouro_nao_acusam_repeticao():
    # Régua da casa desde a R26: critério mecânico novo passa antes pelos 18.
    assert pl.fechos_com_mesma_abertura(_exemplos_da_identidade()) == 0


# ---------------------------------------------------------- cópia literal do prompt
def test_pega_fecho_copiado_do_exemplo():
    # Aconteceu de verdade na medição da R26 — o modelo devolveu o exemplo do
    # prompt intacto. Publicar isso é publicar o nosso próprio few-shot no canal.
    assert pl.fechos_copiados_do_prompt(_com_roteiro("Same door. Still closed.")) == 1


def test_copia_disfarcada_de_pontuacao_e_caixa_tambem_conta():
    assert pl.fechos_copiados_do_prompt(_com_roteiro("same door, still closed")) == 1


def test_fecho_proprio_nao_conta_como_copia():
    assert pl.fechos_copiados_do_prompt(_com_roteiro("Same bed. Still asleep.")) == 0
    assert pl.fechos_copiados_do_prompt([{"roteiro": ""}]) == 0


# ---------------------------------------------------------------- extrair
def test_extrai_objeto_com_lista_pautas():
    texto = '{"pautas": [{"tema": "t1", "roteiro": "r1"}, {"tema": "t2", "roteiro": "r2"}]}'
    assert len(pl.extrair_pautas(texto)) == 2


def test_extrai_array_puro():
    texto = '[{"tema": "t1", "roteiro": "r1"}]'
    assert pl.extrair_pautas(texto)[0]["tema"] == "t1"


def test_extrai_objeto_unico_de_pauta():
    texto = '{"tema": "t1", "roteiro": "r1", "hook": "h"}'
    saida = pl.extrair_pautas(texto)
    assert len(saida) == 1 and saida[0]["hook"] == "h"


def test_extrai_com_fence_de_markdown():
    texto = '```json\n{"pautas": [{"tema": "t1", "roteiro": "r1"}]}\n```'
    assert len(pl.extrair_pautas(texto)) == 1


def test_extrai_com_prosa_em_volta():
    texto = 'Claro! Aqui estão:\n[{"tema": "t1", "roteiro": "r1"}]\nEspero ter ajudado.'
    assert pl.extrair_pautas(texto)[0]["tema"] == "t1"


def test_extrai_descarta_itens_nao_dict():
    texto = '{"pautas": [{"tema": "t1", "roteiro": "r1"}, "lixo", 42]}'
    assert len(pl.extrair_pautas(texto)) == 1


def test_extrai_vazio_levanta():
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_pautas("   ")


def test_extrai_texto_sem_json_levanta():
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_pautas("desculpe, não consegui gerar nada hoje")


def test_extrai_json_sem_pautas_levanta():
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_pautas('{"resultado": "ok"}')


# ---------------------------------------------------------------- limpar
def test_limpa_apara_e_normaliza():
    limpa = pl.limpar_pauta(
        {"tema": "  t  ", "roteiro": "  r  ", "hook": "  h  ", "titulo": "", "descricao": None}
    )
    assert limpa == {"tema": "t", "roteiro": "r", "hook": "h", "titulo": None, "descricao": None}


def test_limpa_recusa_roteiro_so_com_branco():
    assert pl.limpar_pauta({"tema": "t", "roteiro": "   "}) is None


def test_limpa_recusa_tema_ausente():
    assert pl.limpar_pauta({"roteiro": "r"}) is None


# ---------------------------------------------------------------- separar
def test_separa_conta_descartadas():
    brutos = [
        {"tema": "t1", "roteiro": "r1"},
        {"tema": "  ", "roteiro": "r2"},   # tema vazio
        {"tema": "t3", "roteiro": ""},     # roteiro vazio
        {"tema": "t4", "roteiro": "r4"},
    ]
    validas, descartadas = pl.separar_validas(brutos)
    assert len(validas) == 2 and descartadas == 2


# ---------------------------------------------------------------- prompt
def test_prompt_embute_identidade_e_limites():
    prompt = pl.montar_prompt("VOZ DA MARCA AQUI", 15)
    assert "VOZ DA MARCA AQUI" in prompt
    assert "15 pautas" in prompt
    assert str(pl.HOOK_MAX) in prompt
    assert '"pautas"' in prompt   # o formato exato pedido
    assert "Reference examples" in prompt   # o few-shot da identidade (canal EN)
    assert "NEW angles" in prompt           # e a ordem de não copiá-los


def _exemplos_da_identidade() -> list[dict]:
    """Extrai o bloco JSON de exemplos-ouro de memory/00_IDENTIDADE.md."""
    texto = IDENTIDADE.read_text(encoding="utf-8")
    bloco = re.search(r"```json\s*(.*?)```", texto, re.S)
    assert bloco, "não achei o bloco ```json``` de exemplos na identidade"
    return json.loads(bloco.group(1))["pautas"]


def test_identidade_tem_18_exemplos_bem_formados():
    # Guarda o few-shot contra uma edição futura que quebre em silêncio: um
    # exemplo com hook > 88 ou roteiro fora do alvo de linhas ENSINA o modelo a
    # errar (o render corta o hook longo sem avisar, e a duração do vídeo é o
    # comprimento do roteiro — exemplo curto encurta o vídeo), e JSON torto
    # quebra o parser do gerador na primeira execução real.
    pautas = _exemplos_da_identidade()
    assert len(pautas) == 18
    for i, p in enumerate(pautas):
        for campo in ("tema", "hook", "roteiro", "titulo", "descricao"):
            assert p.get(campo), f"exemplo {i} sem {campo}"
        assert len(p["hook"]) <= pl.HOOK_MAX, f"exemplo {i}: hook > {pl.HOOK_MAX}"
        linhas = p["roteiro"].split("\n")
        assert len(linhas) == pl.LINHAS_DO_ROTEIRO, (
            f"exemplo {i}: roteiro com {len(linhas)} linhas"
        )
        assert linhas[0].strip() == p["hook"].strip(), f"exemplo {i}: 1ª linha ≠ hook"


def test_nenhum_exemplo_ouro_e_flagrado_como_fora_de_forma():
    # Os 18 exemplos são a definição operacional de "bom" neste projeto. Critério
    # mecânico que reprova um deles está errado por definição — foi assim que a
    # heurística de "fecho começando por conjunção" morreu antes do build (ela
    # flagraria "Until the outline changes" e "So it waits"). O teste é a régua.
    for i, p in enumerate(_exemplos_da_identidade()):
        assert not pl.roteiro_fora_de_forma(p["roteiro"]), f"exemplo {i} flagrado"


def test_teto_do_fecho_cabe_nos_18_exemplos():
    # O número no prompt é lido dos exemplos, não inventado: o fecho mais longo
    # dos 18 tem 7 palavras. Um teto menor mandaria o modelo bater uma régua que
    # o próprio few-shot desmente, e o few-shot ganha essa briga.
    for i, p in enumerate(_exemplos_da_identidade()):
        fecho = [ln for ln in p["roteiro"].split("\n") if ln.strip()][-1]
        assert len(fecho.split()) <= pl.FECHO_MAX_PALAVRAS, f"exemplo {i}: {fecho}"


def test_prompt_ensina_a_fechar_o_roteiro():
    # O defeito da R26: o prompt descrevia o roteiro em uma frase e gastava todo
    # o resto com o hook. As regras de fecho existiam só na identidade, na linha
    # 93 de um documento de 326 — e num modelo pequeno isso some.
    prompt = pl.montar_prompt("VOZ", 6)
    assert pl.bloco_do_fecho() in prompt
    assert str(pl.FECHO_MAX_PALAVRAS) in prompt
    assert "CLOSES; it does not " in prompt      # fecha, não resume
    assert "IMAGE or a concrete fact" in prompt  # imagem, não lição


def test_prompt_manda_contar_PALAVRAS_e_diz_a_consequencia():
    # O coração da R31. As duas rodadas anteriores puseram o alvo em linhas e
    # erraram; aqui o prompt carrega o número que de fato governa a duração, a taxa
    # que o converte em segundos e o que acontece com quem ficar abaixo. Sem a
    # consequência escrita, o limite vira sugestão — a mesma lição que a identidade
    # já registra sobre o teto do hook.
    prompt = pl.montar_prompt("VOZ", 6)
    assert f"{duracao.PALAVRAS_ALVO_MIN} to {duracao.PALAVRAS_ALVO_MAX} words" in prompt
    assert str(duracao.palavras_minimas()) in prompt
    assert "REJECTED" in prompt
    assert "WORD COUNT IS THE HARD RULE" in prompt


def test_prompt_nomeia_a_curva_em_movimentos():
    # "N lines" sozinho produziu menos linhas que o alvo em gerações medidas. Dar
    # função a cada batida é o que torna a contagem verificável pelo próprio modelo.
    # Com o alvo em 16 (R31), a curva vira MOVIMENTOS: nomear dezesseis papéis um a
    # um encheria o comando de texto concreto, e a R30 mediu que texto concreto
    # demais num modelo pequeno vira gabarito em vez de instrução.
    prompt = pl.montar_prompt("VOZ", 6)
    assert f"EXACTLY {pl.LINHAS_DO_ROTEIRO} lines" in prompt
    for papel in ("line 1 = the hook", "lines 2-4 = the discomfort",
                  "lines 5-7 = the turn", "lines 8-10 = the consequence",
                  "lines 11-13 = press the same truth further",
                  "lines 14-15 = the tension",
                  f"line {pl.LINHAS_DO_ROTEIRO} = the close"):
        assert papel in prompt, f"falta o papel: {papel}"


def _fechos_da_identidade() -> set[str]:
    """Só as últimas linhas dos 18 exemplos-ouro."""
    return {
        [ln for ln in p["roteiro"].split("\n") if ln.strip()][-1].strip()
        for p in _exemplos_da_identidade()
    }


def test_prompt_ancora_o_fecho_com_exemplo_real_da_identidade():
    # As frases citadas no bloco de fecho saíram dos 18 exemplos-ouro. Se alguém
    # reescrever a identidade e elas sumirem, o prompt passa a ensinar com exemplo
    # que o few-shot não confirma — e este teste avisa.
    fechos = _fechos_da_identidade()
    citados = [c for c in fechos if c and c in pl.bloco_do_fecho()]
    assert citados, "o bloco de fecho não cita nenhum fecho real dos exemplos"


# ------------------------------------------------- R27: rodízio e formas por índice
def test_fechos_ouro_saem_todos_da_identidade():
    # A lista do módulo é cópia; a identidade é a fonte. Se divergirem, o prompt
    # ensina com um exemplo que o few-shot logo abaixo não confirma — e o modelo
    # recebe dois padrões conflitantes sem ninguém perceber.
    fechos = _fechos_da_identidade()
    for forma, par in pl.FECHOS_OURO:
        for fecho in par:
            assert fecho in fechos, f"'{fecho}' ({forma}) não é fecho de nenhum ouro"


def test_fechos_ouro_nao_repetem_exemplo():
    exemplos = [fecho for _forma, par in pl.FECHOS_OURO for fecho in par]
    assert len(set(exemplos)) == len(exemplos)
    formas = [forma for forma, _par in pl.FECHOS_OURO]
    assert len(set(formas)) == len(formas)


def test_fechos_ouro_cobrem_os_18_da_identidade():
    # Invariante mais forte que "todo exemplo é real": a lista é uma REORGANIZAÇÃO
    # dos 18, não uma seleção. Se a identidade ganhar um exemplo, este teste cobra
    # que ele seja classificado numa forma em vez de ficar de fora em silêncio.
    citados = {fecho for _forma, par in pl.FECHOS_OURO for fecho in par}
    assert citados == _fechos_da_identidade()


def test_ha_formas_suficientes_para_as_chamadas_do_pool():
    # Três chamadas (18 candidatos ÷ lote de 6) × três âncoras por bloco = nove
    # formas. Com menos, a terceira chamada repete a janela da primeira.
    from math import ceil

    chamadas = ceil(18 / pl.LOTE_GERACAO)
    assert len(pl.FECHOS_OURO) >= chamadas * pl.ANCORAS_POR_BLOCO


def test_cada_forma_tem_dois_exemplos():
    # O bloco cita só o primeiro; o segundo existe para ampliar a mira do detector de
    # cópia, já que a identidade leva os 18 exemplos ao prompt como few-shot.
    for forma, par in pl.FECHOS_OURO:
        assert len(par) == 2, f"a forma '{forma}' precisa de dois exemplos"


def test_detector_de_copia_mira_os_dois_exemplos_de_cada_forma():
    for _forma, (um, outro) in pl.FECHOS_OURO:
        assert pl.fechos_copiados_do_prompt(_com_roteiro(um)) == 1
        assert pl.fechos_copiados_do_prompt(_com_roteiro(outro)) == 1


def test_bloco_do_fecho_roda_o_exemplo():
    # A mecânica da rodada: duas chamadas seguidas não miram o mesmo alvo.
    assert pl.bloco_do_fecho(0) != pl.bloco_do_fecho(1)


def test_bloco_do_fecho_da_a_volta():
    # Índice maior que a lista não estoura — `gerar_pool` pode fazer mais chamadas
    # que o número de âncoras no dia em que PAUTA_LOCAL_CANDIDATOS subir.
    voltas = len(pl.FECHOS_OURO)   # passo × voltas é múltiplo do tamanho
    assert pl.bloco_do_fecho(voltas) == pl.bloco_do_fecho(0)
    assert pl.bloco_do_fecho(voltas * 3 + 1) == pl.bloco_do_fecho(1)


def test_janelas_consecutivas_nao_compartilham_ancora():
    # Com passo 1, duas das três âncoras se repetiam entre chamadas e a do meio
    # aparecia em todas — o rodízio virava enfeite. Medido: seis de dezoito fechos
    # de um pool abriram com "A", herdado da âncora que nunca saía de cena.
    def ancoras(rodada):
        bloco = pl.bloco_do_fecho(rodada)
        return {fecho for _f, par in pl.FECHOS_OURO if (fecho := par[0]) in bloco}

    assert not ancoras(0) & ancoras(1)


@pytest.mark.parametrize("rodada", range(len(pl.FECHOS_OURO)))
def test_bloco_do_fecho_e_concreto_em_toda_rodada(rodada):
    # O que compra o "fecho em imagem" (0/6 → 6/6 na R26) é o exemplo concreto MAIS
    # o par Good/Bad — as duas variantes medidas sem eles zeraram o critério. Uma
    # rodada que perdesse qualquer um dos dois seria regressão silenciosa.
    bloco = pl.bloco_do_fecho(rodada)
    assert bloco.count('"') >= pl.ANCORAS_POR_BLOCO * 2
    assert "Good, and each a DIFFERENT shape:" in bloco
    assert 'Bad: "So remember' in bloco
    assert str(pl.FECHO_MAX_PALAVRAS) in bloco


def test_prompt_sem_rodada_e_igual_a_rodada_zero():
    # Critério 4: nenhum chamador existente muda de comportamento por engano.
    assert pl.montar_prompt("VOZ", 6) == pl.montar_prompt("VOZ", 6, None, None, 0)


def test_prompt_juiz_cita_a_regua_nomeada():
    # A régua vai INLINE no comando, não só enterrada na identidade — senão um
    # modelo pequeno a perde no meio dos 18 exemplos. As 8 dimensões nomeadas têm
    # de aparecer no texto do prompt.
    candidatos = [{"hook": "hook A"}, {"hook": "hook B"}]
    prompt = pl.montar_prompt_juiz("IDENTIDADE AQUI", candidatos)
    assert pl.RUBRICA_HOOK in prompt
    for termo in (
        "Specificity",
        "Self-contradiction",
        "Gap size",
        "Concreteness",
        "Pattern break",
        "Open loop",
        "Angle originality",
        "Economy",
    ):
        assert termo in prompt
    assert "IDENTIDADE AQUI" in prompt          # a identidade continua junto (voz + exemplos)
    assert "hook A" in prompt and "hook B" in prompt


def test_prompt_juiz_pede_nota_unica_nao_oito_subnotas():
    # A nota continua ÚNICA por candidato — o formato que `extrair_notas` entende.
    # Pedir 8 sub-notas quebraria o parser e um modelo pequeno erraria o formato.
    prompt = pl.montar_prompt_juiz("ID", [{"hook": "h"}])
    assert '"scores"' in prompt
    assert '"nota"' in prompt
    assert "ONE overall 0-10 score per candidate" in prompt
    assert "not one per dimension" in prompt


# ---------------------------------------------------------------- chamar_ollama
def test_chamar_ollama_devolve_conteudo():
    sessao = SessaoFake(conteudo='{"pautas": []}')
    assert pl.chamar_ollama("http://x", "m", "p", sessao) == '{"pautas": []}'
    assert sessao.chamadas[0]["json"]["format"] == "json"
    assert sessao.chamadas[0]["json"]["stream"] is False


def test_chamar_ollama_inalcancavel():
    sessao = SessaoFake(erro=requests.ConnectionError("recusou"))
    with pytest.raises(pl.OllamaIndisponivel):
        pl.chamar_ollama("http://x", "m", "p", sessao)


def test_chamar_ollama_resposta_nao_json():
    sessao = SessaoFake(corpo=None)   # .json() levanta ValueError
    with pytest.raises(pl.OllamaIndisponivel):
        pl.chamar_ollama("http://x", "m", "p", sessao)


def test_chamar_ollama_sem_conteudo_levanta():
    sessao = SessaoFake(conteudo=None)   # message sem content
    with pytest.raises(pl.RespostaInvalida):
        pl.chamar_ollama("http://x", "m", "p", sessao)


# ---------------------------------------------------------------- db
def test_inserir_pauta_carimba_status_e_origem():
    sb = SbFake()
    ident = db.inserir_pauta(sb, "org-1", "tema", "roteiro", hook="h")
    assert ident == "pauta-nova-1"
    assert sb.inserido["status"] == "pronta"
    assert sb.inserido["origem"] == "ollama"
    assert sb.inserido["hook"] == "h"
    assert "titulo" not in sb.inserido   # opcional vazio não entra


def test_inserir_pauta_aceita_origem_gemini():
    # A assinatura real (não o monkeypatch) tem de aceitar origem sobrescrito — é
    # o que o pauta_gemini (Rodada 20) usa. status segue carimbado 'pronta'.
    sb = SbFake()
    db.inserir_pauta(sb, "org-1", "tema", "roteiro", origem="gemini")
    assert sb.inserido["origem"] == "gemini"
    assert sb.inserido["status"] == "pronta"


def test_contar_fila_viva_filtra_estados_e_org():
    sb = SbFake(count=7)
    assert db.contar_fila_viva(sb, "org-1") == 7
    assert sb._filtros["org_id"] == "org-1"
    assert sb._in[0] == "status"
    assert set(sb._in[1]) == {"na_fila", "renderizando", "aguardando_aprovacao"}


# ------------------------------------------------------------- extrair_notas
def test_extrai_notas_lista_de_objetos():
    texto = '{"scores": [{"indice": 0, "nota": 7}, {"indice": 1, "nota": 9}]}'
    assert pl.extrair_notas(texto, 2) == [7.0, 9.0]


def test_extrai_notas_array_de_numeros():
    assert pl.extrair_notas("[3, 8, 5]", 3) == [3.0, 8.0, 5.0]


def test_extrai_notas_contagem_errada_levanta():
    # Menos notas que candidatos = alinhamento torto — melhor cair no fallback.
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_notas('{"scores": [{"nota": 7}]}', 3)


def test_extrai_notas_nao_numerica_levanta():
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_notas('[{"nota": "otimo"}]', 1)


# ------------------------------------------------------------- selecionar_top
def test_seleciona_os_melhores_por_nota():
    cand = [{"hook": "a"}, {"hook": "b"}, {"hook": "c"}]
    top = pl.selecionar_top(cand, [1.0, 9.0, 5.0], 2)
    assert [p["hook"] for p in top] == ["b", "c"]


def test_seleciona_empate_mantem_ordem_de_geracao():
    # sorted é estável; empate não pode virar TypeError comparando dicts.
    cand = [{"hook": "a"}, {"hook": "b"}, {"hook": "c"}]
    top = pl.selecionar_top(cand, [5.0, 5.0, 5.0], 2)
    assert [p["hook"] for p in top] == ["a", "b"]


def test_seleciona_top_maior_que_pool_devolve_tudo():
    cand = [{"hook": "a"}, {"hook": "b"}]
    assert len(pl.selecionar_top(cand, [1.0, 2.0], 5)) == 2


def test_seleciona_top_zero_devolve_vazio():
    assert pl.selecionar_top([{"hook": "a"}], [5.0], 0) == []


# ------------------------------------------------------- deméritos da seleção (R28)
# Uma linha de enchimento com palavras suficientes para o roteiro no alvo passar do
# mínimo de duração. NÃO é detalhe de fixture: com linhas de duas palavras, um
# roteiro de 16 linhas renderia 11s e carregaria o DEMERITO_DURACAO_CURTA — todo
# caso desta seção mediria o demérito errado, calado.
_ENCHIMENTO = "uma linha de roteiro com seis"


def _roteiro(fecho: str, linhas: int = pl.LINHAS_DO_ROTEIRO) -> str:
    """Um roteiro em forma e com duração suficiente, terminando no `fecho` pedido."""
    return "\n".join([f"{_ENCHIMENTO} {i}" for i in range(1, linhas)] + [fecho])


def _pauta(hook: str, fecho: str, linhas: int = pl.LINHAS_DO_ROTEIRO) -> dict:
    return {"hook": hook, "roteiro": _roteiro(fecho, linhas)}


def test_pauta_sa_nao_tem_demerito():
    assert pl.demeritos_da_pauta(_pauta("a", "Quiet ending here")) == 0.0


def test_demeritos_intrinsecos_somam():
    # Roteiro curto E fecho copiado é pior que qualquer um sozinho — um não absorve
    # o outro. Com 4 linhas de enchimento o roteiro erra a forma E a duração, então
    # os três deméritos intrínsecos somam.
    ruim = _pauta("a", "Same door. Still closed.", linhas=4)
    assert pl.demeritos_da_pauta(ruim) == pytest.approx(
        pl.DEMERITO_FECHO_COPIADO
        + pl.DEMERITO_ROTEIRO_CURTO
        + pl.DEMERITO_DURACAO_CURTA
    )


def test_forma_certa_e_duracao_curta_pesa_so_o_da_duracao():
    # A separação da R31, medida no demérito: dezesseis linhas magras têm a curva
    # certa e o vídeo curto. Só o demérito de duração entra.
    magra = {"hook": "a", "roteiro": "\n".join(["duas palavras"] * pl.LINHAS_DO_ROTEIRO)}
    assert pl.roteiro_fora_de_forma(magra["roteiro"]) is False
    assert pl.demeritos_da_pauta(magra) == pytest.approx(pl.DEMERITO_DURACAO_CURTA)


def test_duracao_curta_demove_mas_nao_veta():
    # Mesma regra da casa desde a R4: sinal mecânico ORDENA, não descarta. Com o
    # pool inteiro curto todos levam o mesmo desconto, a ordem volta a ser a da nota
    # e o lote sai do tamanho pedido — vetar mataria a fila de fome num dia ruim.
    magro = "\n".join(["duas palavras"] * pl.LINHAS_DO_ROTEIRO)
    pool = [{"hook": f"h{i}", "roteiro": magro} for i in range(5)]
    top = pl.selecionar_top(pool, [1.0, 5.0, 2.0, 4.0, 3.0], 3)
    assert len(top) == 3
    assert [p["hook"] for p in top] == ["h1", "h3", "h4"]


def test_duracao_curta_pesa_tanto_quanto_o_fecho_copiado():
    # Os dois são "esta pauta não pode virar vídeo como está", por motivos
    # diferentes: um publica o nosso few-shot, o outro garante um render jogado
    # fora. Nenhum hook redime nenhum dos dois, então os dois passam da faixa útil
    # do juiz (~3 pontos).
    assert pl.DEMERITO_DURACAO_CURTA > 3.0
    assert pl.DEMERITO_DURACAO_CURTA == pl.DEMERITO_FECHO_COPIADO
    assert pl.DEMERITO_ROTEIRO_CURTO < pl.DEMERITO_DURACAO_CURTA


def test_fecho_copiado_pesa_mais_que_a_faixa_util_do_juiz():
    # A régua do juiz diz "usável ~7, publicável 8+": a faixa que decide tem ~3
    # pontos. O demérito de cópia é deliberadamente maior que ela inteira.
    assert pl.DEMERITO_FECHO_COPIADO > 3.0
    assert pl.DEMERITO_ROTEIRO_CURTO < pl.DEMERITO_FECHO_COPIADO
    assert pl.DEMERITO_ABERTURA_REPETIDA < pl.DEMERITO_ROTEIRO_CURTO


def test_fecho_copiado_perde_para_hook_pior():
    copiada = _pauta("hook excelente", "Same door. Still closed.")
    limpa = _pauta("hook mediano", "Quiet ending here")
    top = pl.selecionar_top([copiada, limpa], [9.0, 6.0], 1)
    assert top[0]["hook"] == "hook mediano"


def test_roteiro_curto_demove_mas_nao_veta():
    # Pool inteiro fora de forma: todos levam o mesmo desconto, a ordem volta a ser
    # a da nota e o lote NÃO encolhe.
    pool = [_pauta(f"h{i}", f"fecho {i}", linhas=3) for i in range(5)]
    top = pl.selecionar_top(pool, [1.0, 5.0, 2.0, 4.0, 3.0], 3)
    assert len(top) == 3
    assert [p["hook"] for p in top] == ["h1", "h3", "h4"]


def test_repeticao_e_medida_contra_as_ja_selecionadas():
    # Três com a mesma abertura de fecho: a melhor entra sem demérito (ainda não
    # repete nada), as outras duas caem atrás de uma limpa de nota menor.
    pool = [
        _pauta("molde-alto", "Same finish. Still missed."),
        _pauta("molde-medio", "Same finish. Still behind."),
        _pauta("molde-baixo", "Same finish. Still trapped."),
        _pauta("limpa", "Quiet, the whole way there"),
    ]
    top = pl.selecionar_top(pool, [9.0, 8.5, 8.0, 7.5], 2)
    assert [p["hook"] for p in top] == ["molde-alto", "limpa"]


def test_abertura_vazia_nao_conta_como_repeticao():
    # Dois roteiros vazios não podem se penalizar mutuamente por um defeito que é
    # outro: quem responde por eles são os deméritos intrínsecos (forma + duração,
    # 2 + 4), uma vez cada.
    #
    # As notas separam os dois comportamentos: a 2ª vazia vale 10 - 6 = 4 e vence a
    # sã de nota 3. Se a abertura vazia contasse como repetida, ela cairia para 2,5
    # e a sã entraria no lugar — é esse cenário que este teste exclui.
    pool = [
        {"hook": "vazia-a", "roteiro": ""},
        {"hook": "vazia-b", "roteiro": ""},
        _pauta("sa", "Quiet ending here"),
    ]
    top = pl.selecionar_top(pool, [10.0, 10.0, 3.0], 2)
    assert [p["hook"] for p in top] == ["vazia-a", "vazia-b"]


def test_nota_falha_afunda_mesmo_com_demeritos_em_jogo():
    # NOTA_FALHA (-1) somada a demérito só afunda mais — nunca vira exceção. Com as
    # duas sãs, a pontuada ganha; com a pontuada carregando a cópia, ela ainda ganha
    # se a nota cobrir o demérito (5 - 4 = 1 > -1).
    sem_nota = _pauta("juiz engasgou", "Quiet ending here")
    copiada = _pauta("pontuada", "Same door. Still closed.")
    top = pl.selecionar_top([sem_nota, copiada], [pl.NOTA_FALHA, 5.0], 1)
    assert top[0]["hook"] == "pontuada"

    sa = _pauta("pontuada sã", "Another quiet ending")
    top = pl.selecionar_top([sem_nota, sa], [pl.NOTA_FALHA, 0.0], 1)
    assert top[0]["hook"] == "pontuada sã"


def test_fecho_copiado_custa_quase_o_mesmo_que_nao_ter_sido_julgado():
    # Calibração que caiu de uma medição acidental e vale fixar: uma pauta MEDIANA
    # (3, abaixo do "usável ~7" do juiz) com fecho copiado empata com uma pauta que o
    # juiz não conseguiu pontuar. Ou seja: copiar o few-shot custa aproximadamente
    # toda a credibilidade de um julgamento. Se algum peso mudar, isto avisa.
    assert 3.0 - pl.DEMERITO_FECHO_COPIADO == pytest.approx(pl.NOTA_FALHA)


# ------------------------------------------------------------- aplicar_reescrita
def test_reescrita_funde_hook_mais_forte():
    orig = {"tema": "t", "roteiro": "velho", "hook": "fraco", "titulo": "x"}
    nova = pl.aplicar_reescrita(orig, {"hook": "forte", "roteiro": "forte\nmais"})
    assert nova["hook"] == "forte" and nova["roteiro"] == "forte\nmais"
    assert nova["tema"] == "t" and nova["titulo"] == "x"   # resto intacto


def test_reescrita_vazia_mantem_original():
    orig = {"tema": "t", "roteiro": "r", "hook": "bom"}
    assert pl.aplicar_reescrita(orig, {"hook": "", "roteiro": ""}) is orig


def test_reescrita_hook_longo_mantem_original():
    # A reescrita não pode INTRODUZIR um hook que o render vai cortar.
    orig = {"tema": "t", "roteiro": "r", "hook": "bom curto"}
    longo = {"hook": "x" * 89, "roteiro": "x" * 89}
    assert pl.aplicar_reescrita(orig, longo) is orig


# ---------------------------------------------------------------- gerar_pool
class SessaoRoteada:
    """Roteia o POST por marca no prompt: geração, juiz e reescrita têm respostas
    próprias. Assim um único dublê cobre o fluxo best-of-N inteiro.

    Cada resposta pode ser uma string (conteúdo do Ollama) ou um callable
    `(prompt, chamadas) -> str | Exception`; devolver uma Exception a levanta.
    """

    def __init__(self, *, geracao=None, juiz=None, reescrita=None):
        self._rotas = {"geracao": geracao, "juiz": juiz, "reescrita": reescrita}
        self.chamadas: list[tuple[str, str]] = []

    def post(self, url, json=None, **_kwargs):
        prompt = json["messages"][0]["content"]
        # Marcadores estáveis do papel de cada prompt (o texto exato do comando
        # muda; o papel, não): "quality judge" só existe no prompt do juiz,
        # "hook doctor" só no da reescrita.
        if "quality judge" in prompt:
            tipo = "juiz"
        elif "hook doctor" in prompt:
            tipo = "reescrita"
        else:
            tipo = "geracao"
        self.chamadas.append((tipo, prompt))
        resp = self._rotas[tipo]
        conteudo = resp(prompt, self.chamadas) if callable(resp) else resp
        if isinstance(conteudo, Exception):
            raise conteudo
        return _RespFake({"message": {"content": conteudo}})

    def tipos(self):
        return [t for t, _ in self.chamadas]


def _pool_json(n):
    itens = ",".join(
        f'{{"tema": "t{i}", "roteiro": "l1\\nl2", "hook": "h{i}"}}' for i in range(n)
    )
    return f'{{"pautas": [{itens}]}}'


def _juiz_por_indice(notas):
    """Juiz per-candidato: pontuar julga um hook por chamada, na ordem do pool,
    então a k-ésima chamada do juiz devolve a k-ésima nota. Cada resposta é o
    JSON de nota ÚNICA que `montar_prompt_juiz([cand])` pede — não o lote."""

    def resp(_prompt, chamadas):
        # esta chamada já foi anexada a `chamadas` antes do callable rodar.
        k = sum(1 for t, _ in chamadas if t == "juiz") - 1
        return f'{{"scores": [{{"nota": {notas[k]}}}]}}'

    return resp


def _cfg(tmp_path, *, teto=20, n=2, candidatos=6, refinar=True, vencedores=5):
    ident = tmp_path / "id.md"
    ident.write_text("identidade da marca", encoding="utf-8")
    return types.SimpleNamespace(
        org_id="org-1",
        pauta_local_teto=teto,
        pauta_local_n=n,
        pauta_local_candidatos=candidatos,
        pauta_local_refinar=refinar,
        pauta_local_vencedores=vencedores,
        ollama_url="http://x",
        ollama_model="m",
        identidade=ident,
    )


def test_gerar_pool_faz_ceil_chamadas(tmp_path):
    # 13 candidatos, lote 6 → ceil(13/6) = 3 chamadas de geração.
    sessao = SessaoRoteada(geracao=_pool_json(pl.LOTE_GERACAO))
    cfg = _cfg(tmp_path, candidatos=13)
    pool, _invalidas = pl.gerar_pool(cfg, "identidade", sessao)
    assert sessao.tipos() == ["geracao", "geracao", "geracao"]
    assert len(pool) == 3 * pl.LOTE_GERACAO


def test_gerar_pool_roda_a_ancora_do_fecho_por_chamada(tmp_path):
    # A mecânica da R27, verificada nos prompts REALMENTE enviados: até aqui as três
    # chamadas recebiam texto idêntico, e o pool inteiro mirava um exemplo só.
    sessao = SessaoRoteada(geracao=_pool_json(pl.LOTE_GERACAO))
    pl.gerar_pool(_cfg(tmp_path, candidatos=13), "identidade", sessao)

    prompts = [prompt for tipo, prompt in sessao.chamadas if tipo == "geracao"]
    assert len(prompts) == 3
    assert len(set(prompts)) == 3, "as chamadas mandaram o mesmo prompt"
    for i, prompt in enumerate(prompts):
        assert pl.bloco_do_fecho(i) in prompt


# ---------------------------------------------------------------- gerar_pautas
def _capturar_insercoes(monkeypatch):
    inseridas = []
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 0)
    monkeypatch.setattr(db, "contar_pautas_prontas", lambda _sb, _org: 0)
    # Sem métrica por padrão: o few-shot de vencedores degrada para vazio, e os
    # testes de orquestração best-of-N seguem exercitando só a espinha.
    monkeypatch.setattr(db, "hooks_por_retencao", lambda _sb, _org, _lim: [])
    monkeypatch.setattr(
        db, "inserir_pauta", lambda _sb, _org, **campos: inseridas.append(campos) or "x"
    )
    return inseridas


def test_gerar_para_quando_fila_cheia(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 20)
    monkeypatch.setattr(db, "contar_pautas_prontas", lambda _sb, _org: 0)
    inseriu = []
    monkeypatch.setattr(db, "inserir_pauta", lambda *a, **k: inseriu.append(k) or "x")
    sessao = SessaoRoteada(geracao=_pool_json(6))

    resumo = pl.gerar_pautas(_cfg(tmp_path), sb=object(), sessao=sessao)

    assert resumo["gerou"] == 0 and resumo["motivo"] == "fila_cheia"
    assert inseriu == [] and sessao.chamadas == []   # nem chamou o Ollama


def test_backpressure_conta_pauta_esperando_revisao(tmp_path, monkeypatch):
    """Teto atingido só por pautas na revisão: não gera (R25).

    Desde que o trigger de auto-enfileirar saiu, pauta gerada não vira vídeo — fica
    `pronta` esperando o dono ler o roteiro. Um freio que contasse só vídeo veria
    zero para sempre e a automática empilharia pauta três vezes por dia, calada. É o
    caso que prova que a conta virou fila viva + prontas.
    """
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 0)
    monkeypatch.setattr(db, "contar_pautas_prontas", lambda _sb, _org: 20)
    inseriu = []
    monkeypatch.setattr(db, "inserir_pauta", lambda *a, **k: inseriu.append(k) or "x")
    sessao = SessaoRoteada(geracao=_pool_json(6))

    resumo = pl.gerar_pautas(_cfg(tmp_path), sb=object(), sessao=sessao)

    assert resumo["motivo"] == "fila_cheia"
    assert inseriu == [] and sessao.chamadas == []


def test_gerar_ranqueia_e_insere_top_n(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    # per-candidato: uma nota por chamada do juiz, na ordem do pool.
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita='{"hook": "H-forte", "roteiro": "H-forte\\nl2"}',
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    assert resumo["gerou"] == 2 and resumo["ranqueou"] is True and resumo["pool"] == 6
    # o juiz foi chamado uma vez por candidato (6), não em lote.
    assert sessao.tipos().count("juiz") == 6
    # top 2 por nota são os índices 4 (9) e 1 (8) — tema sobrevive à reescrita.
    assert [p["tema"] for p in inseridas] == ["t4", "t1"]
    assert [p["hook"] for p in inseridas] == ["H-forte", "H-forte"]   # reescrito


def test_gerar_conta_roteiro_fora_de_forma_e_insere_assim_mesmo(tmp_path, monkeypatch):
    # Roteiro curto é FRACO, não quebrado: renderiza e publica. Descartar com 4
    # em 6 fora de forma mataria a fila de fome. Vira contador, como o hook longo.
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita='{"hook": "H", "roteiro": "H\\nl2"}',   # 2 linhas — fora de forma
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    assert resumo["fora_de_forma"] == 2
    assert resumo["gerou"] == 2 and len(inseridas) == 2


def test_gerar_conta_roteiro_curto_demais_e_insere_assim_mesmo(tmp_path, monkeypatch):
    # Contador, não portão — a regra da casa desde a R4. O que a pauta curta perde é
    # ordem (o DEMERITO_DURACAO_CURTA); o que ela não perde é existir, porque com o
    # pool inteiro curto vetar deixaria a fila vazia. Quem decide é o dono, na
    # revisão, com o número de palavras na tela.
    _capturar_insercoes(monkeypatch)
    magro = "\\n".join(["duas palavras"] * pl.LINHAS_DO_ROTEIRO)
    sessao = SessaoRoteada(
        geracao=_pool_com(magro, magro),
        juiz=_juiz_por_indice([7, 7]),
        reescrita="",
    )

    resumo = pl.gerar_pautas(
        _cfg(tmp_path, n=2, candidatos=2, refinar=False), sb=object(), sessao=sessao
    )

    assert resumo["curto_demais"] == 2
    assert resumo["fora_de_forma"] == 0   # a forma está certa; a duração não
    assert resumo["gerou"] == 2


def test_gerar_conta_variedade_de_fecho_e_insere_assim_mesmo(tmp_path, monkeypatch):
    # A reescrita devolve o mesmo fecho para todos os selecionados: abertura
    # repetida em 2, e o fecho é cópia literal do exemplo do prompt. Os dois
    # contadores acusam; nenhuma pauta é descartada por causa disso.
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita='{"hook": "H", "roteiro": "H\\nl2\\nl3\\nl4\\nSame door. Still closed."}',
    )

    # n=3 e não 2: molde é a partir de três repetições (`MOLDE_MINIMO`).
    resumo = pl.gerar_pautas(_cfg(tmp_path, n=3), sb=object(), sessao=sessao)

    assert resumo["abertura_repetida"] == 3
    assert resumo["fecho_copiado"] == 3
    assert resumo["gerou"] == 3 and len(inseridas) == 3


def test_juiz_falha_degrada_para_primeiros(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz="isto não é json de nota",   # extrair_notas levanta
        reescrita=lambda _p, _c: '{"hook": "R", "roteiro": "R\\nl2"}',
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    assert resumo["ranqueou"] is False and resumo["gerou"] == 2
    # Sem ranking, todo o pool empata em nota; como neste fixture todos carregam
    # exatamente os mesmos deméritos, a ordem de geração sobrevive (t0, t1).
    assert [p["tema"] for p in inseridas] == ["t0", "t1"]


def _pool_com(*roteiros):
    """Pool com roteiros escolhidos a dedo — para exercitar deméritos diferentes."""
    itens = ",".join(
        f'{{"tema": "t{i}", "roteiro": "{r}", "hook": "h{i}"}}'
        for i, r in enumerate(roteiros)
    )
    return f'{{"pautas": [{itens}]}}'


# Roteiros no alvo de forma E de duração, para o único demérito em jogo aqui ser o
# fecho. O `\\n` é escapado porque estas strings entram num JSON de mentira.
_MEIO = "\\n".join(f"uma linha de roteiro com seis {i}" for i in range(1, pl.LINHAS_DO_ROTEIRO))
_COPIADO = f"{_MEIO}\\nSame door. Still closed."
_SA_A = f"{_MEIO}\\nQuiet ending here"
_SA_B = f"{_MEIO}\\nAnother way out"


def test_juiz_falha_e_o_mecanico_ainda_evita_fecho_copiado(tmp_path, monkeypatch):
    # O ganho que a R28 traz onde antes não havia critério nenhum: com o juiz fora,
    # a seleção era `pool[:n]` — ordem de geração — e a pauta de fecho copiado
    # entrava por estar na frente. Agora o demérito a empurra para trás sozinho.
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_com(_COPIADO, _SA_A, _SA_B),
        juiz="isto não é json de nota",
        reescrita="",
    )

    resumo = pl.gerar_pautas(
        _cfg(tmp_path, n=2, candidatos=3, refinar=False), sb=object(), sessao=sessao
    )

    assert resumo["ranqueou"] is False and resumo["gerou"] == 2
    assert [p["tema"] for p in inseridas] == ["t1", "t2"]
    assert resumo["fecho_copiado"] == 0 and resumo["demovidas"] == 0


def test_demovidas_conta_quando_o_pool_nao_tem_substituta_sa(tmp_path, monkeypatch):
    # Sem folga (n = tamanho do pool), a defeituosa entra assim mesmo — demérito
    # ORDENA, nunca veta — e o contador diz que foi isso que aconteceu.
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_com(_COPIADO, _SA_A, _SA_B),
        juiz=_juiz_por_indice([9, 1, 2]),   # a copiada é a de melhor hook
        reescrita="",
    )

    resumo = pl.gerar_pautas(
        _cfg(tmp_path, n=3, candidatos=3, refinar=False), sb=object(), sessao=sessao
    )

    assert resumo["gerou"] == 3 and len(inseridas) == 3
    # 9 - 4 = 5 ainda vence 2 e 1, então a copiada entra — mas por último, e contada.
    assert [p["tema"] for p in inseridas] == ["t0", "t2", "t1"]
    assert resumo["demovidas"] == 1


def test_a_folga_do_pool_e_gasta_com_a_defeituosa(tmp_path, monkeypatch):
    # Com folga de 1 (pool 3, fila 2), a copiada é justamente quem fica de fora,
    # mesmo tendo o melhor hook do lote.
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_com(_COPIADO, _SA_A, _SA_B),
        juiz=_juiz_por_indice([9, 6, 7]),
        reescrita="",
    )

    resumo = pl.gerar_pautas(
        _cfg(tmp_path, n=2, candidatos=3, refinar=False), sb=object(), sessao=sessao
    )

    assert [p["tema"] for p in inseridas] == ["t2", "t1"]
    assert resumo["demovidas"] == 0 and resumo["fecho_copiado"] == 0


def test_reescrita_falha_mantem_original(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)

    def reescrita(_prompt, chamadas):
        # falha na 1ª reescrita, sucesso na 2ª
        quantas = sum(1 for t, _ in chamadas if t == "reescrita")
        if quantas == 1:
            return requests.ConnectionError("caiu")
        return '{"hook": "R-ok", "roteiro": "R-ok\\nl2"}'

    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita=reescrita,
    )
    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    assert resumo["gerou"] == 2
    # 1º (t4) manteve o hook original; 2º (t1) foi reescrito.
    assert inseridas[0]["hook"] == "h4"
    assert inseridas[1]["hook"] == "R-ok"


def test_refinar_desligado_nao_reescreve(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita="NUNCA CHAMADO",
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2, refinar=False), sb=object(), sessao=sessao)

    assert "reescrita" not in sessao.tipos()   # zero chamadas de reescrita
    assert [p["hook"] for p in inseridas] == ["h4", "h1"]   # hooks originais
    assert resumo["gerou"] == 2


def test_pool_vazio_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 0)
    monkeypatch.setattr(db, "contar_pautas_prontas", lambda _sb, _org: 0)
    monkeypatch.setattr(db, "hooks_por_retencao", lambda _sb, _org, _lim: [])
    monkeypatch.setattr(db, "inserir_pauta", lambda *a, **k: "x")
    # modelo devolve só lixo sem tema/roteiro → pool vazio.
    sessao = SessaoRoteada(geracao='{"pautas": [{"foo": "bar"}]}')
    with pytest.raises(pl.RespostaInvalida):
        pl.gerar_pautas(_cfg(tmp_path), sb=object(), sessao=sessao)


# ---------------------------------------------------------------- pontuar (per-candidato)
def _candidatos(n):
    return [{"tema": f"t{i}", "roteiro": "l1\nl2", "hook": f"h{i}"} for i in range(n)]


def test_pontuar_faz_uma_chamada_por_candidato(tmp_path):
    # 4 candidatos → 4 chamadas ao juiz, e as notas saem na ordem do pool.
    sessao = SessaoRoteada(juiz=_juiz_por_indice([5, 2, 9, 7]))
    notas = pl.pontuar(_cfg(tmp_path), "identidade", _candidatos(4), sessao)
    assert sessao.tipos() == ["juiz", "juiz", "juiz", "juiz"]
    assert notas == [5, 2, 9, 7]


def test_pontuar_candidato_torto_afunda_sem_perder_os_outros(tmp_path):
    # o juiz engasga no candidato do meio (2ª chamada) → só ele vira NOTA_FALHA.
    def juiz(_prompt, chamadas):
        k = sum(1 for t, _ in chamadas if t == "juiz") - 1
        if k == 1:
            return "isto não é json de nota"
        return '{"scores": [{"nota": 8}]}'

    sessao = SessaoRoteada(juiz=juiz)
    notas = pl.pontuar(_cfg(tmp_path), "identidade", _candidatos(3), sessao)
    assert notas == [8, pl.NOTA_FALHA, 8]
    assert pl.NOTA_FALHA < 0   # afunda em qualquer selecionar_top


def test_pontuar_todos_tortos_levanta(tmp_path):
    # nenhum candidato pontuável → levanta, gerar_pautas degrada para first-N.
    sessao = SessaoRoteada(juiz="nada de json aqui")
    with pytest.raises(pl.RespostaInvalida):
        pl.pontuar(_cfg(tmp_path), "identidade", _candidatos(3), sessao)


def test_pontuar_transporte_fora_propaga(tmp_path):
    # Ollama fora do ar em qualquer chamada é o run inteiro degradando, não um
    # candidato ruim — a exceção de transporte propaga, não vira sentinela.
    sessao = SessaoRoteada(juiz=lambda _p, _c: requests.ConnectionError("caiu"))
    with pytest.raises(pl.OllamaIndisponivel):
        pl.pontuar(_cfg(tmp_path), "identidade", _candidatos(3), sessao)


def test_prompt_gerador_limita_o_molde_e_nomeia_alternativas():
    prompt = pl.montar_prompt("IDENT", 5)
    # teto explícito no molde-assinatura "X isn't Y"…
    assert "AT MOST ONE IN THREE" in prompt
    # …e ao menos 3 formas alternativas nomeadas.
    alternativas = ["confession", "compounds", "identity split", "absence"]
    assert sum(1 for a in alternativas if a in prompt) >= 3


# ------------------------------------------------- vencedores por retenção (R13)
def _vencedor_cru(hook, retencao, *, views=100):
    """Uma linha na forma CRUA que `db.hooks_por_retencao` devolve (embed do
    PostgREST) — o mesmo formato que o banco de verdade entrega."""
    return {
        "retencao_media_pct": retencao,
        "views": views,
        "publicacoes": {"url": "u", "videos": {"pautas": {"tema": "tm", "hook": hook}}},
    }


def test_formatar_vencedores_achata_e_filtra():
    linhas = [
        _vencedor_cru("hook forte", 58.4),
        _vencedor_cru("", 40.0),           # sem hook → fora
        _vencedor_cru("hook sem numero", None),  # sem retenção → fora
        _vencedor_cru("hook zerado", 0.0),  # recém-publicado, sem dado ainda → fora
        _vencedor_cru("hook ok", 33.0),
    ]
    saida = pl.formatar_vencedores(linhas)
    assert saida == [
        {"hook": "hook forte", "retencao": 58.4},
        {"hook": "hook ok", "retencao": 33.0},
    ]


def test_formatar_vencedores_embed_faltando_nao_quebra():
    # Publicação/vídeo/pauta nulos na cadeia (dado legado) não podem levantar.
    assert pl.formatar_vencedores([{"retencao_media_pct": 50, "publicacoes": None}]) == []


def test_bloco_vencedores_vazio_e_string_vazia():
    # O pivô da degradação: sem vencedores, o bloco some inteiro.
    assert pl.montar_bloco_vencedores([]) == ""


def test_bloco_vencedores_lista_hooks_com_retencao_e_avisa():
    bloco = pl.montar_bloco_vencedores(
        [{"hook": "You're not lazy", "retencao": 58.4}, {"hook": "Prove it", "retencao": 41.0}]
    )
    assert "PROVEN WINNERS" in bloco
    assert "You're not lazy" in bloco and "Prove it" in bloco
    assert "58% retention" in bloco   # número da tabela, arredondado
    assert "never repeat" in bloco     # o mesmo aviso dos exemplos-ouro


def test_prompt_sem_vencedores_igual_ao_de_hoje():
    # Compatibilidade: sem vencedores, o prompt é byte-a-byte o de antes da R13.
    base = pl.montar_prompt("VOZ", 6)
    assert pl.montar_prompt("VOZ", 6, []) == base
    assert pl.montar_prompt("VOZ", 6, None) == base
    assert "PROVEN WINNERS" not in base


def test_prompt_com_vencedores_injeta_o_bloco():
    prompt = pl.montar_prompt("VOZ", 6, [{"hook": "Winner hook", "retencao": 62.0}])
    assert "PROVEN WINNERS" in prompt
    assert "Winner hook" in prompt
    # a identidade e as regras continuam presentes.
    assert "VOZ" in prompt and str(pl.HOOK_MAX) in prompt


def test_gerar_injeta_vencedores_no_prompt_de_geracao(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    monkeypatch.setattr(
        db, "hooks_por_retencao",
        lambda _sb, _org, _lim: [_vencedor_cru("Proven winner hook", 61.0)],
    )
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita='{"hook": "H", "roteiro": "H\\nl2"}',
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    geracao = [p for t, p in sessao.chamadas if t == "geracao"]
    assert geracao and all("Proven winner hook" in p for p in geracao)
    assert all("PROVEN WINNERS" in p for p in geracao)
    assert resumo["vencedores"] == 1
    assert len(inseridas) == 2   # o resto do fluxo segue normal


def test_bloco_categoria_vazio_e_string_vazia():
    # Mesmo pivô de degradação dos vencedores: sem categoria, o bloco some.
    assert pl.montar_bloco_categoria(None) == ""
    assert pl.montar_bloco_categoria("") == ""
    assert pl.montar_bloco_categoria("   ") == ""


def test_prompt_sem_categoria_igual_ao_de_hoje():
    # Compatibilidade: quem não escolheu categoria gera como sempre gerou.
    base = pl.montar_prompt("VOZ", 6)
    assert pl.montar_prompt("VOZ", 6, None, None) == base
    assert "TOPIC FOCUS" not in base


def test_bloco_categoria_dirige_o_assunto_e_nao_a_voz():
    bloco = pl.montar_bloco_categoria("religion")
    assert "TOPIC FOCUS" in bloco and "religion" in bloco
    # A identidade continua mandando no tom — categoria é o QUE, não o COMO.
    assert "never HOW" in bloco


def test_gerar_com_categoria_injeta_no_prompt_e_carimba_a_pauta(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita='{"hook": "H", "roteiro": "H\\nl2"}',
    )

    resumo = pl.gerar_pautas(
        _cfg(tmp_path, n=2), sb=object(), sessao=sessao, categoria="lifestyle"
    )

    geracao = [p for t, p in sessao.chamadas if t == "geracao"]
    assert geracao and all("lifestyle" in p for p in geracao)
    # A categoria vai junto para o banco: é o snapshot que sobrevive à remoção
    # da categoria depois.
    assert all(c["categoria"] == "lifestyle" for c in inseridas)
    assert resumo["categoria"] == "lifestyle"


def test_gerar_degrada_sem_metricas(tmp_path, monkeypatch):
    # hooks_por_retencao devolve [] (métrica não coletada) → prompt de sempre.
    inseridas = _capturar_insercoes(monkeypatch)   # já patcha hooks_por_retencao → []
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita='{"hook": "H", "roteiro": "H\\nl2"}',
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    geracao = [p for t, p in sessao.chamadas if t == "geracao"]
    assert geracao and all("PROVEN WINNERS" not in p for p in geracao)
    assert resumo["vencedores"] == 0 and resumo["gerou"] == 2 and len(inseridas) == 2


def test_gerar_degrada_se_leitura_de_vencedores_falha(tmp_path, monkeypatch):
    # A tabela `metricas` pode não existir ainda (migration da R11 é passo humano
    # pendente): a leitura levanta, e a geração NÃO pode cair por isso.
    inseridas = _capturar_insercoes(monkeypatch)

    def explode(_sb, _org, _lim):
        raise RuntimeError("relation public.metricas does not exist")

    monkeypatch.setattr(db, "hooks_por_retencao", explode)
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=_juiz_por_indice([3, 8, 2, 1, 9, 4]),
        reescrita='{"hook": "H", "roteiro": "H\\nl2"}',
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    assert resumo["gerou"] == 2 and resumo["vencedores"] == 0
    geracao = [p for t, p in sessao.chamadas if t == "geracao"]
    assert geracao and all("PROVEN WINNERS" not in p for p in geracao)
    assert len(inseridas) == 2


def test_ler_vencedores_usa_org_e_limite_do_cfg(tmp_path, monkeypatch):
    capturado = {}

    def espiao(_sb, org, lim):
        capturado["org"] = org
        capturado["lim"] = lim
        return [_vencedor_cru("h", 50.0)]

    monkeypatch.setattr(db, "hooks_por_retencao", espiao)
    saida = pl.ler_vencedores(_cfg(tmp_path, vencedores=3), sb=object())
    assert capturado == {"org": "org-1", "lim": 3}
    assert saida == [{"hook": "h", "retencao": 50.0}]
