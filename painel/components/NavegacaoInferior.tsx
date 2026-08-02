"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ABAS = [
  { href: "/", rotulo: "Fila" },
  { href: "/pautas", rotulo: "Pautas" },
  { href: "/historico", rotulo: "Histórico" },
] as const;

export default function NavegacaoInferior({
  aguardando,
}: {
  aguardando: number;
}) {
  const caminho = usePathname();

  return (
    // Embaixo, não em cima: a mão segura o celular pela base. Um menu no topo
    // obriga a trocar a pegada para aprovar um vídeo, e aprovar vídeo é a
    // única coisa que se faz aqui com pressa.
    <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-borda bg-superficie/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
      <ul className="mx-auto flex max-w-lg">
        {ABAS.map((aba) => {
          const ativa = caminho === aba.href;
          return (
            <li key={aba.href} className="flex-1">
              <Link
                href={aba.href}
                aria-current={ativa ? "page" : undefined}
                className={`flex min-h-14 items-center justify-center gap-2 text-sm ${
                  ativa ? "text-brasa" : "text-tinta-fraca"
                }`}
              >
                {aba.rotulo}
                {aba.href === "/" && aguardando > 0 && (
                  <span className="rounded-full bg-brasa px-2 py-0.5 text-xs font-medium text-fundo">
                    {aguardando}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
