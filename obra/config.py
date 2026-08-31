"""Config do `obra/`. Offline por construção — nada aqui fala com Supabase.

## Por que este arquivo repete `_binario` do `worker/config.py`

Importar `worker.config` acoplaria um módulo offline a um que exige
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` e `ORG_ID` na primeira linha: o
`obra/` deixaria de rodar em qualquer máquina sem o `.env` do worker — e o
worker inteiro pode ser aposentado sem que este módulo tenha nada com isso.
São ~30 linhas duplicadas contra a independência do módulo. A troca vale, e
está escrita aqui para não ser "consertada" numa limpeza futura.

## Por que `exigir_ffmpeg` existe

`novo` e `listar` são comandos de papel: criam um `projeto.toml` e leem uma
pasta. Falhar neles porque o ffmpeg não está instalado seria falhar cedo demais
— o dono ainda nem tem clipe para processar. Quem exige o binário é quem vai
usá-lo (`proximo`, `checar`, `montar`), e aí a exigência é na largada do
comando, não no meio do trabalho.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# 13 clipes. Não é gosto: é a estrutura do formato de referência (13 × 4-5s ≈
# 60s, que é onde o TikTok e o Shorts ainda entregam o vídeo inteiro). Mudar
# este número muda o roteiro, os prompts e a montagem juntos — por isso é
# constante de módulo e não config de ambiente.
ESTAGIOS = 13


class ConfigInvalida(RuntimeError):
    """Config ausente ou malformada. A mensagem nunca contém valores."""


@dataclass(frozen=True, slots=True)
class Config:
    ffmpeg_bin: Path
    ffprobe_bin: Path
    projetos_dir: Path

    # 9:16. Shorts e TikTok não negociam isso.
    largura: int = 1080
    altura: int = 1920
    fps: int = 30

    # CRF 18 é o do playbook e é alto de propósito: o material já carrega
    # artefato de geração por IA, e comprimir por cima disso empasta o ruído
    # que o modelo produziu. ~60s em 1080x1920 saem em algumas dezenas de MB —
    # irrelevante para um upload manual.
    crf: int = 18

    # Alvo de loudness do TikTok. O YouTube normaliza para ~-14 também, então
    # um número serve às duas plataformas.
    lufs_alvo: float = -14.0
    true_peak: float = -1.5

    # Mixagem. Em dB, negativo é atenuação.
    #
    # NÃO existe ganho de música aqui, e a ausência é decisão (§ 3.6): o módulo
    # não monta trilha. Havia um `ganho_musica_db` sobrevivendo a esta linha, sem
    # nenhum leitor — e junto com ele um comentário descrevendo uma mixagem que
    # não acontece mais, no arquivo que alguém abre para saber o que o módulo
    # faz. Config órfã não é inofensiva: ela é documentação afirmando o falso.
    #
    # O ambiente por estágio vem à frente do leito de fundo porque é ele que
    # marca o corte; o fundo só cola os treze.
    ganho_ambiente_db: float = -3.0
    fade_saida_seg: float = 2.0

    # --- limiares dos dois sinais mecânicos (§ 3.7 da spec) ---
    #
    # ATENÇÃO, e isto é honestidade e não modéstia: os dois números abaixo são
    # PROXY NÃO CALIBRADO. Não existe material real deste formato nesta máquina
    # para calibrá-los — é a mesma ressalva que o `qc_local.py` carrega desde a
    # R16. Por isso o laudo imprime o valor medido AO LADO do rótulo, e por isso
    # nada é apagado ou bloqueado por causa deles. Quem calibra é o dono, com os
    # dois primeiros vídeos, mexendo nestas variáveis.
    #
    # PSNR entre o primeiro e o último frame DO MESMO clipe. Alto = os dois
    # frames são quase o mesmo pixel, ou seja, nada se moveu — e "nenhum clipe
    # é parado" é o item de retenção do playbook.
    psnr_congelado: float = 38.0
    # PSNR entre o último frame do clipe N e o primeiro do N+1. Baixo = a cena
    # trocou entre um clipe e outro (outra caverna, outra luz, outra roupa),
    # que é a falha número um deste formato.
    psnr_descontinuidade: float = 11.0

    # Faixa de duração aceitável por clipe. Fora dela é aviso, nunca recusa:
    # re-gerar um clipe custa um dia de crédito, e 13 clipes desiguais ainda
    # dão um vídeo.
    dur_min_seg: float = 3.5
    dur_max_seg: float = 6.5

    # Quanto do quadro o recorte para 9:16 pode comer antes de virar aviso.
    # 16:9 virando 9:16 descarta ~68% da largura — aí o enquadramento que o
    # modelo compôs não sobrevive, e é melhor saber antes de montar.
    corte_maximo: float = 0.20

    # Teto contra ffmpeg travado (acontece com arquivo corrompido), não
    # expectativa de duração: um encode de 60s sai em menos de um minuto.
    timeout_seg: int = 900


def _inteiro(nome: str, padrao: int) -> int:
    bruto = os.getenv(nome, "").strip()
    if not bruto:
        return padrao
    try:
        valor = int(bruto)
    except ValueError:
        raise ConfigInvalida(f"{nome} precisa ser um número inteiro.") from None
    if valor <= 0:
        raise ConfigInvalida(f"{nome} precisa ser maior que zero.")
    return valor


def _decimal(nome: str, padrao: float) -> float:
    bruto = os.getenv(nome, "").strip()
    if not bruto:
        return padrao
    try:
        return float(bruto)
    except ValueError:
        raise ConfigInvalida(f"{nome} precisa ser um número.") from None


def _binario(nome_var: str, comando: str) -> Path:
    """Resolve um executável: variável de ambiente primeiro, PATH depois.

    Mesma disciplina do worker: o ffmpeg não está no PATH desta máquina (o
    winget instala sob `AppData\\Local\\Microsoft\\WinGet\\Packages\\...` sem
    criar atalho), então "funciona no meu terminal" é exatamente o sintoma que
    não se deve produzir.
    """
    bruto = os.getenv(nome_var, "").strip()
    if bruto:
        caminho = Path(bruto)
        if not caminho.is_file():
            raise ConfigInvalida(f"{nome_var} aponta para um arquivo que não existe.")
        return caminho

    achado = shutil.which(comando)
    if achado:
        return Path(achado)

    raise ConfigInvalida(
        f"{comando} não está no PATH. Defina {nome_var} com o caminho completo "
        f"do executável (o mesmo valor que já está em worker/.env serve)."
    )


def carregar(exigir_ffmpeg: bool = True) -> Config:
    """Monta a Config. `exigir_ffmpeg=False` para os comandos de papel.

    Não lê `.env` de propósito: as variáveis do `obra/` são opcionais e o
    módulo tem de rodar numa pasta limpa, sem arquivo de configuração nenhum.
    Quem quiser fixar o caminho do ffmpeg exporta `FFMPEG_BIN` no ambiente —
    o mesmo nome que o worker usa, para não haver dois nomes para a mesma coisa.
    """
    bruto_dir = os.getenv("OBRA_PROJETOS_DIR", "").strip()
    projetos_dir = Path(bruto_dir) if bruto_dir else RAIZ / "projetos"
    if not projetos_dir.is_absolute():
        projetos_dir = (RAIZ / projetos_dir).resolve()

    if exigir_ffmpeg:
        ffmpeg = _binario("FFMPEG_BIN", "ffmpeg")
        ffprobe = _binario("FFPROBE_BIN", "ffprobe")
    else:
        # Placeholder honesto: quem recebeu `exigir_ffmpeg=False` declarou que
        # não vai chamar processo nenhum. Se chamar, o erro é "executável não
        # encontrado", que é a verdade.
        ffmpeg = Path("ffmpeg")
        ffprobe = Path("ffprobe")

    return Config(
        ffmpeg_bin=ffmpeg,
        ffprobe_bin=ffprobe,
        projetos_dir=projetos_dir,
        largura=_inteiro("OBRA_LARGURA", 1080),
        altura=_inteiro("OBRA_ALTURA", 1920),
        fps=_inteiro("OBRA_FPS", 30),
        crf=_inteiro("OBRA_CRF", 18),
        lufs_alvo=_decimal("OBRA_LUFS", -14.0),
        true_peak=_decimal("OBRA_TRUE_PEAK", -1.5),
        ganho_ambiente_db=_decimal("OBRA_GANHO_AMBIENTE_DB", -3.0),
        fade_saida_seg=_decimal("OBRA_FADE_SAIDA_SEG", 2.0),
        psnr_congelado=_decimal("OBRA_PSNR_CONGELADO", 38.0),
        psnr_descontinuidade=_decimal("OBRA_PSNR_DESCONTINUIDADE", 11.0),
        dur_min_seg=_decimal("OBRA_DUR_MIN_SEG", 3.5),
        dur_max_seg=_decimal("OBRA_DUR_MAX_SEG", 6.5),
        corte_maximo=_decimal("OBRA_CORTE_MAXIMO", 0.20),
        timeout_seg=_inteiro("OBRA_TIMEOUT_SEG", 900),
    )
