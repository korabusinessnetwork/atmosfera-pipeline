export default function Vazio({
  titulo,
  detalhe,
}: {
  titulo: string;
  detalhe: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-borda px-5 py-10 text-center">
      <p className="text-sm text-tinta">{titulo}</p>
      <p className="mt-2 text-sm leading-relaxed text-tinta-fraca">{detalhe}</p>
    </div>
  );
}
