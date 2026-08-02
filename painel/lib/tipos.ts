/**
 * Estado que as Server Actions devolvem para o useActionState.
 *
 * Vive aqui e não junto das actions porque arquivo com "use server" só pode
 * exportar função async — tipo exportado de lá é uma discussão que não precisa
 * existir.
 */
export type EstadoDaAcao = {
  erro: string | null;
};

export const ACAO_OK: EstadoDaAcao = { erro: null };

export type EstadoDoLink = {
  erro: string | null;
  enviado: boolean;
};

export const LINK_INICIAL: EstadoDoLink = { erro: null, enviado: false };

export type VideoDaFila = {
  id: string;
  created_at: string;
  duracao_seg: number | string | null;
  preview_url: string | null;
  thumb_url: string | null;
  tentativas: number;
  pauta: {
    tema: string;
    hook: string | null;
    titulo: string | null;
    descricao: string | null;
  } | null;
};

export type PautaPronta = {
  id: string;
  tema: string;
  hook: string | null;
  titulo: string | null;
  prioridade: number;
  created_at: string;
};

export type PublicacaoDoHistorico = {
  id: string;
  plataforma: "youtube" | "tiktok";
  status: "pendente" | "enviado" | "publicado" | "erro";
  url: string | null;
  agendado_para: string | null;
  publicado_em: string | null;
  erro_msg: string | null;
  created_at: string;
  video: {
    id: string;
    thumb_url: string | null;
    pauta: { tema: string; titulo: string | null } | null;
  } | null;
};
