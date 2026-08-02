"use server";

import { refresh } from "next/cache";
import { redirect } from "next/navigation";

import { clienteServidor } from "@/lib/supabase/server";
import { sessaoAtual } from "@/lib/supabase/claims";
import { ACAO_OK, type EstadoDaAcao } from "@/lib/tipos";

/**
 * Server Action é um endpoint POST alcançável direto, não só pelo botão.
 * Qualquer pessoa com o id da action pode chamá-la sem passar por tela nenhuma.
 *
 * Por isso a autorização é verificada AQUI DENTRO, e não porque o proxy já
 * redirecionou: o proxy protege URLs, e uma action não é uma URL do app.
 *
 * A tranca de verdade continua sendo a RLS — sem org_id no JWT as RPCs não
 * encontram linha nenhuma, chamadas por quem for. Estas checagens existem para
 * transformar "não aconteceu nada" numa frase que a pessoa entende.
 */
async function exigirSessao() {
  const supabase = await clienteServidor();
  const sessao = await sessaoAtual(supabase);
  if (!sessao) redirect("/entrar");
  return { supabase, sessao };
}

type ErroDoPostgrest = { code?: string; message?: string } | null;

/**
 * Traduz o erro do banco sem repetir o texto dele.
 *
 * Repassar `error.message` cru seria mais simples e é o que quase todo painel
 * faz — e é assim que um dia vaza nome de função, id interno ou o SQL que
 * falhou para dentro da tela. As mensagens abaixo são escritas para quem está
 * segurando o celular, não para quem está lendo o log.
 */
function traduzir(erro: ErroDoPostgrest, padrao: string): string {
  const codigo = erro?.code ?? "";

  // P0002: a linha saiu do estado esperado entre a tela abrir e o toque no
  // botão. Não é falha — é a corrida normal entre worker e gate humano.
  if (codigo === "P0002") {
    return "Isso mudou de estado enquanto a tela estava aberta. Atualize a lista.";
  }
  // 42501 = insufficient_privilege, PGRST301 = JWT inválido/expirado.
  if (codigo === "42501" || codigo === "PGRST301") {
    return "Sua sessão perdeu a permissão. Saia e entre de novo.";
  }
  return padrao;
}

export async function aprovarVideo(
  _anterior: EstadoDaAcao,
  formData: FormData,
): Promise<EstadoDaAcao> {
  const { supabase } = await exigirSessao();
  const videoId = String(formData.get("videoId") ?? "");
  if (!videoId) return { erro: "Vídeo não identificado." };

  const { error } = await supabase.rpc("aprovar_video", { p_video_id: videoId });
  if (error) {
    return { erro: traduzir(error, "Não deu para aprovar agora. Tente de novo.") };
  }

  refresh();
  return ACAO_OK;
}

export async function reprovarVideo(
  _anterior: EstadoDaAcao,
  formData: FormData,
): Promise<EstadoDaAcao> {
  const { supabase } = await exigirSessao();
  const videoId = String(formData.get("videoId") ?? "");
  if (!videoId) return { erro: "Vídeo não identificado." };

  // O motivo é opcional de propósito: exigir texto para reprovar transforma a
  // decisão de 2 segundos numa redação, e o gate deixa de ser usado no ônibus.
  // O corte em 500 é do banco (left(...,500) na RPC) — aqui é só cortesia.
  const motivo = String(formData.get("motivo") ?? "").trim().slice(0, 500);

  const { error } = await supabase.rpc("reprovar_video", {
    p_video_id: videoId,
    p_motivo: motivo.length > 0 ? motivo : null,
  });
  if (error) {
    return { erro: traduzir(error, "Não deu para reprovar agora. Tente de novo.") };
  }

  refresh();
  return ACAO_OK;
}

export async function enfileirarPauta(
  _anterior: EstadoDaAcao,
  formData: FormData,
): Promise<EstadoDaAcao> {
  const { supabase } = await exigirSessao();
  const pautaId = String(formData.get("pautaId") ?? "");
  if (!pautaId) return { erro: "Pauta não identificada." };

  const { error } = await supabase.rpc("enfileirar_pauta", {
    p_pauta_id: pautaId,
  });
  if (error) {
    // P0001 aqui só chega quando a pauta saiu de 'pronta' — o caso "conta sem
    // org" não passa pela tela, que mostra o aviso de convite antes da lista.
    const padrao =
      error.code === "P0001"
        ? "Essa pauta não está mais disponível para render."
        : "Não deu para enfileirar agora. Tente de novo.";
    return { erro: traduzir(error, padrao) };
  }

  refresh();
  return ACAO_OK;
}

export async function sair() {
  const supabase = await clienteServidor();
  await supabase.auth.signOut();
  redirect("/entrar");
}
