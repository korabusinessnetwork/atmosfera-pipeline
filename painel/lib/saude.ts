import { decorrido } from "@/lib/formato";
import type { Batimento, EstadoDoWorker } from "@/lib/tipos";

/**
 * O batimento do worker, traduzido para uma frase de celular.
 *
 * **O painel relata; o `worker/saude.py` julga.** A distinção é o desenho deste
 * arquivo inteiro. Decidir "o loop travou" exige o `MPT_TIMEOUT_SEG`, que é
 * número do `.env` do worker — o painel não tem como saber, e chutar produziria
 * um segundo veredito capaz de discordar do primeiro. Duas respostas para a
 * mesma pergunta é pior que uma resposta incompleta.
 *
 * Por isso toda frase daqui é um FATO lido da linha: "bateu há 6min", "40 ciclos",
 * "nunca bateu". O único número de opinião é o `SEM_SINAL_SEG` abaixo, e ele
 * controla apenas a ênfase (a cor do ponto), nunca o texto. Um limite mal
 * calibrado destaca uma frase verdadeira — não inventa uma falsa.
 */

/**
 * A partir de quantos segundos de silêncio a faixa muda de cor.
 *
 * Deliberadamente mais frouxo que o limite do worker (`BATIMENTO_SEG × 3`, 180s
 * no padrão): quem acusa "processo parado" é o `saude.py`, com o número certo na
 * mão. Aqui, 5 minutos é só o ponto em que vale a pena o olho parar na linha.
 */
export const SEM_SINAL_SEG = 300;

/** `null` = não deu para ler o batimento. Vazio = ninguém bateu ainda. */
export function lerBatimento(
  linhas: Batimento[] | null | undefined,
): EstadoDoWorker {
  if (!linhas) {
    return {
      tom: "mudo",
      titulo: "Não deu para ler o batimento",
      // O mesmo cuidado do código 4 do saude.py: falta de informação não é
      // worker morto, e chamar uma de outra ensina a ignorar o aviso.
      detalhe: "isto não quer dizer que o worker caiu",
    };
  }

  if (linhas.length === 0) {
    return {
      tom: "mudo",
      titulo: "Nenhum worker bateu ainda",
      detalhe: "registre a tarefa no PC para a fila começar a andar",
    };
  }

  // `saude_workers()` já devolve ordenado por `visto_em desc`, mas ordenar de
  // novo custa nada e tira a dependência de uma cláusula que vive noutro
  // arquivo, noutra linguagem.
  const linha = [...linhas].sort(
    (a, b) => segundos(a.atraso_seg) - segundos(b.atraso_seg),
  )[0];

  const atraso = segundos(linha.atraso_seg);
  const partes: string[] = [];

  if (atraso >= SEM_SINAL_SEG) {
    partes.push(`sem sinal há ${decorrido(atraso)}`);
  } else {
    partes.push(`bateu há ${decorrido(atraso)}`);
  }

  if (linha.ciclo_em === null) {
    partes.push("ainda não fechou o 1º ciclo");
  } else {
    partes.push(`ciclo há ${decorrido(linha.atraso_ciclo_seg)}`);
  }

  if (linha.ciclos) partes.push(`${linha.ciclos} ciclos`);
  if (linha.erros_seguidos) {
    // Aparece, mas não muda a cor: worker que erra todo ciclo está de pé e
    // girando. A causa mora no card do vídeo, em `erro_msg`.
    partes.push(`${linha.erros_seguidos} erros seguidos`);
  }
  if (linhas.length > 1) partes.push(`${linhas.length} máquinas`);

  return {
    tom: atraso >= SEM_SINAL_SEG ? "atencao" : "ok",
    titulo: linha.maquina,
    detalhe: partes.join(" · "),
  };
}

/** `numeric` do Postgres chega como string no PostgREST. */
function segundos(valor: number | string | null): number {
  const n = typeof valor === "string" ? Number(valor) : valor;
  return n === null || n === undefined || Number.isNaN(n) ? 0 : n;
}
