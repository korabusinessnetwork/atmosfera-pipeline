/**
 * A tela de quem entrou mas não foi convidado.
 *
 * Sem `app_metadata.org_id` no JWT, `public.current_org_id()` devolve null e a
 * RLS não entrega uma linha sequer — a pessoa veria três telas vazias e
 * concluiria que o sistema está quebrado. Este aviso é a diferença entre
 * "não tem nada aqui" e "você não faz parte disto ainda".
 */
export default function AvisoSemOrg({ email }: { email: string | null }) {
  return (
    <div className="mx-auto max-w-lg px-5 py-10">
      <div className="rounded-lg border border-borda bg-superficie p-5">
        <h2 className="text-base font-medium">Conta sem acesso</h2>
        <p className="mt-3 text-sm leading-relaxed text-tinta-fraca">
          {email ? (
            <>
              Você entrou como <span className="text-tinta">{email}</span>, mas
              esse e-mail não está na lista de membros — então não há nada para
              mostrar.
            </>
          ) : (
            <>
              Esta sessão não está ligada a nenhuma org, então não há nada para
              mostrar.
            </>
          )}
        </p>
        <p className="mt-3 text-sm leading-relaxed text-tinta-fraca">
          Se o convite acabou de ser criado, saia e entre de novo: o vínculo
          entra no token no próximo login.
        </p>
      </div>
    </div>
  );
}
