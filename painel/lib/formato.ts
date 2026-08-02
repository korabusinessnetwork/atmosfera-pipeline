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

export function duracao(segundos: number | string | null | undefined): string {
  // numeric do Postgres chega como string no PostgREST — não é sempre number.
  const n = typeof segundos === "string" ? Number(segundos) : segundos;
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const total = Math.round(n);
  const min = Math.floor(total / 60);
  const seg = total % 60;
  return min > 0 ? `${min}:${String(seg).padStart(2, "0")}` : `${seg}s`;
}
