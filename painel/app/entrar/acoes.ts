"use server";

import { clienteServidor } from "@/lib/supabase/server";
import { origemDaRequisicao } from "@/lib/origem";
import { LINK_INICIAL, type EstadoDoLink } from "@/lib/tipos";

const FORMATO_DE_EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export async function enviarLink(
  _anterior: EstadoDoLink,
  formData: FormData,
): Promise<EstadoDoLink> {
  const email = String(formData.get("email") ?? "")
    .trim()
    .toLowerCase();

  if (!FORMATO_DE_EMAIL.test(email)) {
    return { erro: "Digite um e-mail válido.", enviado: false };
  }

  const supabase = await clienteServidor();
  const origem = await origemDaRequisicao();

  const { error } = await supabase.auth.signInWithOtp({
    email,
    options: { emailRedirectTo: `${origem}/auth/confirm` },
  });

  if (error) {
    // Sem eco do erro da API. Ele traz status e às vezes o corpo da resposta —
    // material para descobrir se um e-mail existe, uma pergunta que ninguém
    // deveria conseguir fazer a esta tela.
    return {
      erro: "Não deu para enviar agora. Tente de novo em um minuto.",
      enviado: false,
    };
  }

  // Sempre a mesma resposta, exista a conta ou não.
  //
  // Entrar e cadastrar passam pela mesma porta aqui: um e-mail não convidado
  // recebe link e ganha sessão. Isso não é brecha — sem org_id no JWT,
  // current_org_id() devolve null e a RLS não entrega linha nenhuma. Quem não
  // foi convidado entra numa casa vazia, e é assim que deve ser: a alternativa
  // seria esta tela dizer quem tem conta e quem não tem.
  return { ...LINK_INICIAL, enviado: true };
}
