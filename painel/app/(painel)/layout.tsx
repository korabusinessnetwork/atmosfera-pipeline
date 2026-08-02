import { redirect } from "next/navigation";

import { clienteServidor } from "@/lib/supabase/server";
import { sessaoAtual } from "@/lib/supabase/claims";
import NavegacaoInferior from "@/components/NavegacaoInferior";
import AvisoSemOrg from "@/components/AvisoSemOrg";
import { sair } from "@/app/acoes";

/**
 * Grupo (painel): as três telas atrás de login. `/entrar` fica fora dele de
 * propósito — a tela de login não deve carregar a navegação de um app em que
 * ninguém entrou ainda.
 *
 * A checagem de sessão está aqui e também no proxy, e as duas fazem sentido: o
 * proxy decide antes de renderizar (redirect barato), o layout garante que
 * nenhuma tela do grupo consegue existir sem sessão, mesmo que o matcher do
 * proxy mude um dia.
 */
export default async function LayoutDoPainel({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await clienteServidor();
  const sessao = await sessaoAtual(supabase);

  if (!sessao) redirect("/entrar");

  if (!sessao.orgId) {
    return (
      <>
        <Cabecalho email={sessao.email} />
        <AvisoSemOrg email={sessao.email} />
      </>
    );
  }

  const { count } = await supabase
    .from("videos")
    .select("id", { count: "exact", head: true })
    .eq("status", "aguardando_aprovacao");

  return (
    <>
      <Cabecalho email={sessao.email} />
      {/* pb-20: o conteúdo termina acima da navegação fixa. Sem isso o último
          card fica embaixo da barra e o botão Reprovar não é alcançável. */}
      <main className="mx-auto w-full max-w-lg px-4 pb-24 pt-4">{children}</main>
      <NavegacaoInferior aguardando={count ?? 0} />
    </>
  );
}

function Cabecalho({ email }: { email: string | null }) {
  return (
    <header className="sticky top-0 z-10 border-b border-borda bg-fundo/95 backdrop-blur">
      <div className="mx-auto flex max-w-lg items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="text-lg leading-none text-brasa">亡者</span>
          <span className="truncate text-xs text-tinta-fraca">{email}</span>
        </div>
        <form action={sair}>
          <button
            type="submit"
            className="shrink-0 rounded-md border border-borda px-3 py-1.5 text-xs text-tinta-fraca"
          >
            Sair
          </button>
        </form>
      </div>
    </header>
  );
}
