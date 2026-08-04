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

/**
 * Estado do formulário de pauta.
 *
 * `criadas` é contador, não booleano — o formulário usa esse número como `key`
 * para se remontar e limpar os campos sem nenhum estado controlado. Com um
 * booleano só a primeira pauta limparia a tela: a segunda seguida ficaria com o
 * texto da primeira nos campos, e a pessoa leria isso como "não enviou".
 *
 * No erro o contador NÃO muda, de propósito: o formulário fica de pé com o que
 * foi digitado. Perder cinco linhas de roteiro por um blip de rede é o tipo de
 * coisa que faz alguém parar de usar o painel.
 */
export type EstadoDaPauta = {
  erro: string | null;
  criadas: number;
};

export const PAUTA_INICIAL: EstadoDaPauta = { erro: null, criadas: 0 };

/**
 * Estado da edição de pauta.
 *
 * `salvo` é contador, não booleano, pelo mesmo motivo do `criadas`: duas edições
 * seguidas da mesma pauta precisam que o número mude para o "Alterações salvas."
 * reaparecer. Diferente do criar, a edição NÃO remonta o formulário — os campos
 * ficam com o texto editado, que é o que a pessoa quer ver depois de salvar.
 */
export type EstadoDaEdicao = {
  erro: string | null;
  salvo: number;
};

export const EDICAO_INICIAL: EstadoDaEdicao = { erro: null, salvo: 0 };

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
  roteiro: string | null;
  hook: string | null;
  titulo: string | null;
  descricao: string | null;
  prioridade: number;
  created_at: string;
};

/**
 * Uma linha de `public.saude_workers()`.
 *
 * O painel só LÊ isto — `batimentos` dá `select` ao `authenticated` e mais nada,
 * e quem escreve é o worker com a service_role. Um painel capaz de carimbar
 * batimento poderia declarar vivo um worker que morreu.
 *
 * `atraso_seg`/`atraso_ciclo_seg` vêm calculados pelo banco. Tem que ser assim:
 * o relógio do celular e o do PC do worker não são o mesmo, e subtrair um do
 * outro daria "sem sinal há 3h" num worker saudável de fuso trocado.
 */
export type Batimento = {
  maquina: string;
  worker: string;
  subiu_em: string;
  visto_em: string;
  ciclo_em: string | null;
  ciclos: number;
  erros_seguidos: number;
  atraso_seg: number | string;
  atraso_ciclo_seg: number | string | null;
};

export type EstadoDoWorker = {
  tom: "ok" | "atencao" | "mudo";
  titulo: string;
  detalhe: string;
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
