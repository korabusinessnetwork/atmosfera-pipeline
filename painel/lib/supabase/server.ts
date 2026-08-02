import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

import { configSupabase } from "./env";

/**
 * Cliente do Supabase para Server Components, Server Actions e Route Handlers.
 *
 * Um por request, nunca compartilhado: o cliente carrega a sessão de QUEM está
 * pedindo. Um módulo-singleton serviria a fila de uma pessoa para a próxima.
 *
 * `getAll`/`setAll` e não `get`/`set`/`remove`: o par antigo está deprecado no
 * @supabase/ssr e erra nos casos de token dividido em vários cookies (chunking),
 * que é justamente o que acontece quando o JWT cresce — e o nosso cresce, porque
 * carrega app_metadata.org_id.
 */
export async function clienteServidor(): Promise<SupabaseClient> {
  // `cookies()` ANTES de qualquer outra coisa, e a ordem não é estilo. Ler
  // cookie é uma Dynamic API: é ela que tira a rota do prerender no `build`.
  // Com `configSupabase()` na frente, uma build sem as variáveis de ambiente
  // estoura durante o prerender de uma página que nunca deveria ser prerendada
  // — e a mensagem que aparece é a do env, não a real.
  const cookiesDoRequest = await cookies();
  const { url, chaveAnon } = configSupabase();

  return createServerClient(url, chaveAnon, {
    cookies: {
      getAll: () => cookiesDoRequest.getAll(),
      setAll: (paraGravar) => {
        try {
          for (const { name, value, options } of paraGravar) {
            cookiesDoRequest.set(name, value, options);
          }
        } catch {
          // Server Component: o cookie store é somente leitura fora de Action e
          // Route Handler. Engolir aqui é o comportamento certo, não preguiça —
          // o proxy.ts já renovou o token e já gravou o cookie nesta mesma
          // request. Deixar estourar derrubaria a página por um efeito colateral
          // que outra camada acabou de cumprir.
        }
      },
    },
  });
}
