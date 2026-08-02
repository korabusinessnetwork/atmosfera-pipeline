import type { SupabaseClient } from "@supabase/supabase-js";

/**
 * O claim de tenant vive em `app_metadata.org_id`, NÃO na raiz do JWT.
 *
 * É a mesma leitura que public.current_org_id() faz no banco:
 *   auth.jwt() -> 'app_metadata' ->> 'org_id'
 *
 * Ler da raiz devolveria undefined em silêncio, o painel acharia que ninguém
 * tem org e mostraria o aviso de convite pendente para quem está convidado.
 * O projeto já perdeu tempo com esse caminho uma vez.
 */
export function orgIdDosClaims(claims: unknown): string | null {
  if (!claims || typeof claims !== "object") return null;

  const meta = (claims as Record<string, unknown>)["app_metadata"];
  if (!meta || typeof meta !== "object") return null;

  const org = (meta as Record<string, unknown>)["org_id"];
  return typeof org === "string" && org.length > 0 ? org : null;
}

export type Sessao = {
  email: string | null;
  orgId: string | null;
};

/**
 * Quem está logado, e com qual org.
 *
 * `getClaims()` e não `getSession()`: o cookie é meio inseguro por definição —
 * quem o edita escolhe o conteúdo. getClaims verifica a assinatura do token
 * antes de devolver qualquer coisa. Aqui isso é conforto, não tranca (a tranca
 * é a RLS, que revalida o mesmo JWT do lado do Postgres), mas conforto barato:
 * sem ele o painel exibiria o e-mail que o cookie mandasse exibir.
 *
 * Devolve null quando não há sessão. NÃO renova token: Server Component não
 * consegue gravar cookie, então um refresh aqui seria descartado e repetido a
 * cada render. Quem repara o claim é o proxy — ver repararClaimDeOrg().
 */
export async function sessaoAtual(
  supabase: SupabaseClient,
): Promise<Sessao | null> {
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims) return null;

  const claims = data.claims as unknown as Record<string, unknown>;
  const email = typeof claims["email"] === "string" ? claims["email"] : null;

  return { email, orgId: orgIdDosClaims(claims) };
}

/**
 * Repara o claim de org de quem entrou ANTES de existir o convite.
 *
 * O trigger t_carimbar_org (migration 20260802223611) só roda no INSERT de
 * auth.users. Para uma conta que já existia, sincronizar_membros() corrige a
 * linha em auth.users — mas o access token que a pessoa tem na mão continua o
 * antigo, sem org_id, até expirar. Sem este refresh o painel fica vazio por
 * uma hora inteira, sem erro, sem 401 e sem pista nenhuma: a RLS está fazendo
 * exatamente o que foi mandada fazer.
 *
 * Só o proxy chama. É o único lugar do Next que pode escrever cookie em toda
 * request — num Server Component o token novo seria criado e jogado fora.
 */
export async function repararClaimDeOrg(
  supabase: SupabaseClient,
): Promise<string | null> {
  const { data, error } = await supabase.auth.refreshSession();
  if (error) return null;
  return orgIdDosClaims({ app_metadata: data?.session?.user?.app_metadata });
}
