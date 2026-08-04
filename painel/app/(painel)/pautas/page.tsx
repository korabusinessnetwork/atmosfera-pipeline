import { clienteServidor } from "@/lib/supabase/server";
import BotaoEnfileirar from "@/components/BotaoEnfileirar";
import BotaoDescartar from "@/components/BotaoDescartar";
import FormularioDePauta from "@/components/FormularioDePauta";
import Vazio from "@/components/Vazio";
import { quando } from "@/lib/formato";
import type { PautaPronta } from "@/lib/tipos";

/**
 * Pautas prontas — o que o Cowork escreveu na segunda de manhã, mais o que foi
 * digitado aqui, e que ainda não virou render.
 *
 * Só `pronta` aparece. `em_producao` já tem vídeo na fila e mostrá-la
 * convidaria a enfileirar duas vezes a mesma pauta; a RPC recusaria (P0001),
 * mas recusar é pior do que não oferecer.
 *
 * O formulário fica ACIMA da lista e aparece mesmo com a lista vazia — é o
 * único caso em que a tela vazia não é um beco. Até a Rodada 3 ela mandava a
 * pessoa "inserir à mão no Supabase", que é um painel admitindo não servir para
 * a primeira coisa que alguém quer fazer.
 */
export default async function Pautas() {
  const supabase = await clienteServidor();

  const { data, error } = await supabase
    .from("pautas")
    .select("id, tema, hook, titulo, prioridade, created_at")
    .eq("status", "pronta")
    .order("prioridade", { ascending: false })
    .order("created_at", { ascending: true });

  if (error) {
    return (
      <Vazio
        titulo="Não deu para carregar as pautas."
        detalhe="Puxe a tela para recarregar. Se persistir, saia e entre de novo."
      />
    );
  }

  const pautas = (data ?? []) as PautaPronta[];

  return (
    <div className="flex flex-col gap-3">
      <FormularioDePauta />

      {pautas.length === 0 && (
        <Vazio
          titulo="Nenhuma pauta pronta."
          detalhe="O Cowork escreve as pautas da semana na segunda, 06:00. Até lá — ou quando a ideia não puder esperar — use o formulário acima."
        />
      )}

      {pautas.map((pauta) => (
        <article
          key={pauta.id}
          className="rounded-lg border border-borda bg-superficie p-4"
        >
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-base leading-snug font-medium">{pauta.tema}</h2>
            {pauta.prioridade > 0 && (
              <span className="mt-0.5 shrink-0 rounded-full border border-brasa px-2 py-0.5 text-xs text-brasa">
                p{pauta.prioridade}
              </span>
            )}
          </div>

          {pauta.hook && (
            <p className="mt-3 border-l-2 border-brasa pl-3 text-sm leading-relaxed text-tinta">
              {pauta.hook}
            </p>
          )}

          {pauta.titulo && (
            <p className="mt-3 text-sm leading-relaxed text-tinta-fraca">
              <span className="text-tinta-fraca/70">Título: </span>
              {pauta.titulo}
            </p>
          )}

          <p className="mt-3 text-xs text-tinta-fraca">
            {quando(pauta.created_at)}
          </p>

          <BotaoEnfileirar pautaId={pauta.id} />
          <BotaoDescartar pautaId={pauta.id} />
        </article>
      ))}
    </div>
  );
}
