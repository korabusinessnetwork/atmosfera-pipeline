import { NextResponse, type NextRequest } from "next/server";
import type { EmailOtpType } from "@supabase/supabase-js";

import { clienteServidor } from "@/lib/supabase/server";
import { caminhoInterno, origemDaRequisicao } from "@/lib/origem";

/**
 * Onde o link do e-mail cai.
 *
 * Aceita as DUAS formas, e isso é deliberado:
 *
 *   ?code=...        PKCE — o que o template PADRÃO do Supabase manda hoje.
 *   ?token_hash=...  o que o template customizado ({{ .TokenHash }}) manda.
 *
 * Suportar só a segunda deixaria "editar o template de e-mail no dashboard"
 * como pré-requisito para o login funcionar — um passo manual, invisível, cujo
 * sintoma é um link que abre e não loga. Aceitando as duas, trocar o template
 * vira melhoria opcional em vez de bloqueio.
 */
const TIPOS_ACEITOS: EmailOtpType[] = ["magiclink", "email", "signup", "invite"];

export async function GET(request: NextRequest) {
  const parametros = request.nextUrl.searchParams;
  const destino = caminhoInterno(parametros.get("next"));

  const supabase = await clienteServidor();

  const codigo = parametros.get("code");
  const tokenHash = parametros.get("token_hash");
  const tipo = parametros.get("type") as EmailOtpType | null;

  let entrou = false;

  if (codigo) {
    const { error } = await supabase.auth.exchangeCodeForSession(codigo);
    entrou = !error;
  } else if (tokenHash && tipo && TIPOS_ACEITOS.includes(tipo)) {
    const { error } = await supabase.auth.verifyOtp({
      type: tipo,
      token_hash: tokenHash,
    });
    entrou = !error;
  }

  // Route Handler pode escrever cookie: o setAll do clienteServidor gravou a
  // sessão no cookie store desta request, e o Next a carimba na resposta —
  // inclusive num redirect.
  const base = await origemDaRequisicao();

  if (!entrou) {
    // `?erro=link` e não a mensagem do Supabase: link expirado, já usado e
    // inexistente devem parecer a mesma coisa de fora.
    return NextResponse.redirect(new URL("/entrar?erro=link", base));
  }

  return NextResponse.redirect(new URL(destino, base));
}
