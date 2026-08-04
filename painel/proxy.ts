import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";

import { configSupabase } from "@/lib/supabase/env";
import { orgIdDosClaims, repararClaimDeOrg } from "@/lib/supabase/claims";

/**
 * proxy.ts, NÃO middleware.ts.
 *
 * O Next 16 renomeou o arquivo. `middleware.ts` não dá erro nenhum: ele
 * simplesmente não roda. Como o único efeito visível seria "a sessão expira e
 * ninguém é redirecionado", o bug se pareceria com um problema de Supabase.
 * (O runtime aqui é nodejs e não é configurável — `edge` saiu.)
 *
 * Este arquivo existe por um motivo estrutural, não por conveniência: é o
 * ÚNICO lugar do app que consegue escrever cookie em toda request. Server
 * Component não consegue. Sem ele, o refresh do token acontece, o cookie novo é
 * descartado, e a pessoa é deslogada quando o access token vence — de forma
 * intermitente, que é a pior de todas.
 */

const ROTA_DE_ENTRADA = "/entrar";
const ROTAS_PUBLICAS = [ROTA_DE_ENTRADA, "/auth/confirm"];

/**
 * Marca que o claim de org já foi rechecado há pouco.
 *
 * Sem isso, quem entra sem convite força um refresh de token a CADA request —
 * navegação, favicon, prefetch do Next. É uma tempestade de chamadas ao GoTrue
 * disparada por quem justamente não deveria conseguir nada. Dois minutos é
 * curto o bastante para o convite recém-criado valer sozinho.
 */
const COOKIE_RECHECAGEM = "atmosfera_org_rechecada";
const SEGUNDOS_ENTRE_RECHECAGENS = 120;

export async function proxy(request: NextRequest) {
  const { url, chaveAnon } = configSupabase();

  // Duas escritas por cookie, e as duas importam: `request` para que o Server
  // Component logo adiante leia o token NOVO nesta mesma request, `resposta`
  // para que o navegador guarde. Escrever só numa das duas dá o clássico
  // "funciona depois do F5".
  let resposta = NextResponse.next({ request });

  const supabase = createServerClient(url, chaveAnon, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (paraGravar, headers) => {
        for (const { name, value } of paraGravar) {
          request.cookies.set(name, value);
        }
        resposta = NextResponse.next({ request });
        for (const { name, value, options } of paraGravar) {
          resposta.cookies.set(name, value, options);
        }
        // Resposta que carimba Set-Cookie de sessão não pode ficar em cache de
        // CDN. A Vercel serve este app atrás de uma — sem estes headers, o
        // token de uma pessoa pode ser entregue para a próxima que pedir a
        // mesma URL. A lib manda os headers certos justamente por isso.
        for (const [chave, valor] of Object.entries(headers)) {
          resposta.headers.set(chave, valor);
        }
      },
    },
  });

  // Cedo, antes de qualquer decisão: se o refresh terminar depois que a
  // resposta já saiu, o token novo se perde e a próxima request refaz tudo.
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims ?? null;

  const caminho = request.nextUrl.pathname;
  const publica = ROTAS_PUBLICAS.some(
    (rota) => caminho === rota || caminho.startsWith(`${rota}/`),
  );

  if (!claims) {
    if (publica) return resposta;
    const destino = request.nextUrl.clone();
    destino.pathname = ROTA_DE_ENTRADA;
    destino.search = "";
    // O redirect precisa levar junto os cookies que o refresh acabou de gravar;
    // NextResponse.redirect() nasce limpo e jogaria fora a sessão renovada.
    return comCookiesDe(resposta, NextResponse.redirect(destino));
  }

  const jaTemOrg = orgIdDosClaims(claims) !== null;
  const rechecouAgora = request.cookies.has(COOKIE_RECHECAGEM);

  if (!jaTemOrg && !rechecouAgora) {
    await repararClaimDeOrg(supabase);
    resposta.cookies.set(COOKIE_RECHECAGEM, "1", {
      maxAge: SEGUNDOS_ENTRE_RECHECAGENS,
      httpOnly: true,
      sameSite: "lax",
      secure: request.nextUrl.protocol === "https:",
      path: "/",
    });
  }

  // Logado tentando ver /entrar: manda para a fila. Sem isso o botão "voltar"
  // do celular cai numa tela de login que não faz mais sentido.
  if (caminho === ROTA_DE_ENTRADA) {
    const destino = request.nextUrl.clone();
    destino.pathname = "/";
    destino.search = "";
    return comCookiesDe(resposta, NextResponse.redirect(destino));
  }

  return resposta;
}

function comCookiesDe(origem: NextResponse, destino: NextResponse) {
  for (const cookie of origem.cookies.getAll()) {
    destino.cookies.set(cookie);
  }
  return destino;
}

export const config = {
  matcher: [
    // Tudo que não seja estático do Next nem arquivo com extensão. Estáticos
    // não têm sessão para renovar, e passar por aqui só somaria latência a
    // cada ícone.
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|mp4|webmanifest|txt)$).*)",
  ],
};
