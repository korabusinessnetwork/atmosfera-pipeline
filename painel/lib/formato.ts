/**
 * Fuso fixo, não o do servidor.
 *
 * Na Vercel o servidor é UTC. Sem fixar aqui, um vídeo renderizado às 22h de
 * ontem apareceria como "hoje, 01:00" — e o painel serve para julgar o que
 * acabou de sair da fila. É a mesma lição da cota do YouTube na Sprint 4, com
 * o sinal trocado: lá o fuso certo era o do Pacífico porque quem conta é o
 * Google; aqui é o de São Paulo porque quem lê é você.
 */
const FUSO = "America/Sao_Paulo";

const dataCurta = new Intl.DateTimeFormat("pt-BR", {
  timeZone: FUSO,
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function quando(iso: string | null | undefined): string {
  if (!iso) return "—";
  const data = new Date(iso);
  if (Number.isNaN(data.getTime())) return "—";
  return dataCurta.format(data);
}

/**
 * Um intervalo em algo que se lê de relance: "45s", "12min", "3h07".
 *
 * Mesma forma do `_humano()` do `worker/saude.py`, de propósito — as duas telas
 * que respondem "o worker está vivo?" não podem falar dialetos diferentes de
 * tempo. Isto aqui é apresentação, não julgamento: o que decide se um número é
 * alarmante mora em `lib/saude.ts`, e a autoridade final é o `saude.py`.
 */
export function decorrido(segundos: number | string | null | undefined): string {
  const n = typeof segundos === "string" ? Number(segundos) : segundos;
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  // Negativo só aconteceria com carimbos divergentes, mas "-3s" na tela faria
  // quem lê duvidar do resto da linha.
  const s = Math.max(0, Math.round(n));
  if (s < 90) return `${s}s`;
  if (s < 5400) return `${Math.floor(s / 60)}min`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h${String(m).padStart(2, "0")}`;
}

export function duracao(segundos: number | string | null | undefined): string {
  // numeric do Postgres chega como string no PostgREST — não é sempre number.
  const n = typeof segundos === "string" ? Number(segundos) : segundos;
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const total = Math.round(n);
  const min = Math.floor(total / 60);
  const seg = total % 60;
  return min > 0 ? `${min}:${String(seg).padStart(2, "0")}` : `${seg}s`;
}
