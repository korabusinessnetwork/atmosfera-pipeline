/**
 * As duas únicas variáveis que o painel conhece.
 *
 * NÃO existe SUPABASE_SERVICE_ROLE_KEY aqui, e a ausência é o desenho: a
 * service_role ignora RLS no banco inteiro. Num app que renderiza no servidor
 * ela até pareceria segura — mas bastaria um `select` sem filtro para servir a
 * fila de outra org, e a proteção deixaria de ser uma política do banco para
 * virar disciplina de quem escreve query. O painel usa a anon key mais o JWT
 * do usuário; a RLS faz o resto.
 *
 * Lidas DENTRO da função, não no topo do módulo: um `throw` em escopo de módulo
 * quebraria `next build` numa máquina sem .env.local, e o build não precisa das
 * chaves — nenhuma página deste app é estática, todas dependem do cookie.
 */
export type ConfigSupabase = {
  url: string;
  chaveAnon: string;
};

export function configSupabase(): ConfigSupabase {
  // Referência literal a process.env.NEXT_PUBLIC_*: é assim que o Next
  // substitui o valor no bundle. Ler por variável (env[nome]) devolve undefined
  // no navegador.
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const chaveAnon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !chaveAnon) {
    throw new Error(
      "Faltam NEXT_PUBLIC_SUPABASE_URL e/ou NEXT_PUBLIC_SUPABASE_ANON_KEY. " +
        "Local: copie painel/.env.local.example para painel/.env.local. " +
        "Vercel: Settings > Environment Variables.",
    );
  }

  return { url, chaveAnon };
}
