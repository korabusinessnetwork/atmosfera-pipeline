import FormularioDeEntrada from "./FormularioDeEntrada";

export default async function Entrar({
  searchParams,
}: {
  // Promise: no Next 16 o acesso síncrono a searchParams foi removido, não
  // depreciado. Tipar como objeto compila e quebra em runtime.
  searchParams: Promise<{ erro?: string }>;
}) {
  const { erro } = await searchParams;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-sm flex-col justify-center px-5 py-10">
      <header className="mb-8">
        <p className="text-3xl leading-none text-brasa">亡者</p>
        <h1 className="mt-4 text-xl font-medium tracking-tight">
          Atmosfera · painel
        </h1>
        <p className="mt-1 text-sm text-tinta-fraca">
          Fila de aprovação. Nada publica sem passar por aqui.
        </p>
      </header>

      <FormularioDeEntrada linkInvalido={erro === "link"} />
    </main>
  );
}
