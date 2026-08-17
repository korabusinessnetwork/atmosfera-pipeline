/**
 * O contrato de duração, do lado do celular.
 *
 * **Este arquivo é um ESPELHO de `worker/duracao.py`, não uma segunda opinião.**
 * A R31 criou aquele módulo para que os quatro consumidores em Python dessem a
 * mesma resposta; o gate do texto, porém, tem dois lados — o painel local
 * (Tkinter, Python, que já importa `duracao.py`) e este, que roda no navegador e
 * não alcança Python nenhum. Sem o espelho, quem enfileira pelo celular é o
 * único do sistema que decide **sem ver** o número, e manda para o render um
 * roteiro que o `main.py` vai reprovar sozinho depois de 2,5 min de MPT.
 *
 * Os números abaixo são cópia, e cópia é dívida: se `PALAVRAS_POR_SEG` mudar lá
 * (o cabeçalho de `worker/duracao.py` explica como recalibrar com `duracao_seg ÷
 * palavras(roteiro)` na primeira dúzia de vídeos), muda aqui no mesmo commit.
 * São duas constantes e uma divisão — o custo de sincronizar é menor que o de um
 * gate cego, que foi o que existiu até aqui.
 *
 * O que este arquivo **não** faz: reprovar, bloquear o botão, ou esconder a
 * pauta. Ele relata, como o `lib/saude.ts` ao lado — a estimativa é pessimista
 * de propósito (ponta rápida do intervalo medido), então um roteiro que ela
 * chama de curto ainda pode render acima do mínimo. Quem decide é o dono.
 */

/** Ponta rápida do intervalo medido (2,5–2,8). Ver `worker/duracao.py:59`. */
export const PALAVRAS_POR_SEG = 2.8;

/** Decisão editorial do dono (2026-08-08), não limite de plataforma. */
export const DURACAO_MINIMA_SEG = 30;

/** Quantas palavras a voz de fato pronuncia. `split` colapsa qualquer branco. */
export function palavras(roteiro: string | null | undefined): number {
  const limpo = (roteiro ?? "").trim();
  return limpo === "" ? 0 : limpo.split(/\s+/).length;
}

/** Estimativa pessimista da narração, em segundos. */
export function duracaoEstimadaSeg(roteiro: string | null | undefined): number {
  return palavras(roteiro) / PALAVRAS_POR_SEG;
}

/** O roteiro é curto demais para alcançar o mínimo? */
export function roteiroCurtoDemais(roteiro: string | null | undefined): boolean {
  return duracaoEstimadaSeg(roteiro) < DURACAO_MINIMA_SEG;
}

/**
 * `≈34s · 95 palavras` — a mesma frase que o painel local mostra na revisão.
 *
 * Roteiro ausente devolve `null` em vez de "≈0s": uma pauta sem roteiro é uma
 * pauta sobre a qual não se sabe nada, e um zero na tela afirmaria o contrário.
 */
export function fraseDaDuracao(
  roteiro: string | null | undefined,
): { texto: string; curto: boolean } | null {
  const n = palavras(roteiro);
  if (n === 0) return null;
  const curto = roteiroCurtoDemais(roteiro);
  const aviso = curto ? ` ⚠ abaixo de ${DURACAO_MINIMA_SEG}s` : "";
  return {
    texto: `≈${Math.round(duracaoEstimadaSeg(roteiro))}s · ${n} palavras${aviso}`,
    curto,
  };
}
