# Virar o canal para inglês — mercado internacional

**Rodada 5** · `/ciclo` · fonte: `ATMOSFERA_PIPELINE.md` §7 (limites), `CLAUDE.md`
(document-first) e a decisão do dono: "cria modelos em inglês pra upar na gringa
que dá mais dinheiro" → opção **"virar tudo pra inglês"** (um canal só, o pt-BR
sai).

## 0. Por que esta rodada existe

O dono quer publicar no mercado de língua inglesa, que monetiza mais. A escolha
entre canal separado, bilíngue e "virar tudo" foi do dono: **virar tudo**. Não é
um segundo canal nem uma coluna `idioma` — é o mesmo canal, a mesma org, o mesmo
OAuth, trocando o idioma de ponta a ponta. É a opção mais barata em infra e a que
não toca o schema.

## 1. Escopo

Trocar a produção e o render de pt-BR para inglês (en-US): (1) reescrever
`memory/00_IDENTIDADE.md` como identidade de marca em inglês, com 4 exemplos-ouro
de hook/roteiro em inglês; (2) trocar a voz de narração (`MPT_VOZ`) para uma voz
neural en-US; (3) traduzir o andaime do prompt do gerador (`montar_prompt`) para
inglês, para o modelo local escrever em inglês; (4) reescolher o modelo local
(llama3.1 tende a ganhar em inglês) por teste seco.

## 2. Fora de escopo

- **Coluna `idioma` / bilíngue.** O dono escolheu virar tudo, não coexistir. Sem
  schema novo.
- **Segundo canal / segundo OAuth.** Mesmo canal, mesma credencial do YouTube e
  do TikTok já configurada. O que muda é o conteúdo, não o destino.
- **Reautorizar YouTube/TikTok.** O canal é o mesmo; token vale. (Renomear o
  canal no YouTube Studio, se o dono quiser um nome em inglês, é passo humano —
  vai para `specs/_manual.md`, não é código.)
- **NÃO fora de escopo (o dono pediu junto):** o idioma do vídeo no upload do
  YouTube. `youtube.py` já cravava `defaultLanguage`/`defaultAudioLanguage` como
  `"pt-BR"` (linhas 215-216) — vira `en-US`. Ajuda o algoritmo a entender o
  público. Meia dúzia de caracteres, mais o teste que asserta o valor.
- **Traduzir as pautas pt-BR que já estão na fila.** As 3 em
  `aguardando_aprovacao` são pt-BR e já renderizadas; o dono aprova ou reprova no
  gate como sempre. Esta rodada muda o que nasce daqui pra frente.
- **Hashtags.** As da marca são fixas (`pautas.hashtags` default) e
  language-agnostic o bastante; ajuste fino de tags en-US é outra rodada.

## 3. Origem e decisões que este item honra

- **Decisão do dono (AskUserQuestion): "virar tudo pra inglês".** Registrada aqui
  porque não está em `memory/` — o `/aprender` cataloga.
- **ADR-06 (gate humano).** Intocado: só muda idioma de conteúdo e voz. A corrente
  continua parando em `aguardando_aprovacao`.
- **A assinatura 亡者 é visual, não textual** (§ 3 e § 7.5 da identidade). Ela
  sobrevive à troca de idioma sem mudança — é kanji aplicado pelo render, nunca
  narrado.
- **CLAUDE.md — document-first.** Sem mudança de schema (nenhum estado novo), então
  a regra "começa no schema" não dispara; a regra que vale é documentar antes, e
  é o que este spec faz.

## 4. Arquivos afetados

| Arquivo | O quê |
|---|---|
| `memory/00_IDENTIDADE.md` | **reescrito** em inglês — voz da marca + 4 exemplos-ouro em inglês |
| `worker/pauta_local.py` | `montar_prompt` em inglês (andaime + ordem de idioma) |
| `worker/tests/test_pauta_local.py` | ajustar asserts de substring do prompt (agora em inglês) |
| `worker/.env.example` | `MPT_VOZ` → voz en-US; nota do modelo (llama3.1 forte em inglês) |
| `worker/.env` (local, não commitado) | `MPT_VOZ` en-US, `OLLAMA_MODEL` conforme o teste |
| `specs/_manual.md` | nota: renomear o canal no Studio é opcional e humano |
| `ATMOSFERA_PIPELINE.md` | §4 — o produtor local agora escreve em inglês |

## 5. Critérios de aceite

1. `00_IDENTIDADE.md` está em inglês, autossuficiente, e mantém os limites que
   saem do render: hook ≤ 88 caracteres com o mesmo aviso de corte, roteiro de 5
   linhas obrigatório, 亡者 como assinatura visual não-narrada, sem CTA, sem
   promessa, sem citar pessoa/marca real.
2. A seção de exemplos traz 4 pautas-ouro em inglês, no formato JSON exato de
   saída, cada uma num ângulo diferente, hooks entre ~40 e 60 caracteres, sem
   ponto final, em segunda pessoa.
3. `montar_prompt` instrui saída em inglês e aponta os exemplos como padrão
   ("imite o estilo, gere ângulos novos, não copie"). O teste do prompt passa com
   as substrings novas.
4. `MPT_VOZ` aponta para uma voz neural en-US válida do edge-tts (ex.:
   `en-US-GuyNeural-Male`), com pelo menos uma alternativa citada no `.env.example`.
5. `OLLAMA_MODEL` escolhido por teste seco comparando llama3.1 e qwen2.5 em
   inglês; a evidência (hooks gerados) fica no relato da rodada. Nada é inserido
   no banco no teste.
6. Suíte do worker verde (**≥ 322**). RLS inalterada (**29 ✅**, a rodada não toca
   tabela). `next build` continua limpo (painel não é tocado).
7. Nenhum secret novo; `.env.example` sem secret; `MPT_VOZ`/`OLLAMA_MODEL` são
   config, não credencial.

## 6. Edge cases conhecidos

- **Fonte da legenda cobre inglês?** `MicrosoftYaHeiBold.ttc` (o `MPT_FONTE`
  padrão) cobre latino sem acento e o 亡者 — inglês é ASCII puro, então zero
  risco de tofu. Nenhuma mudança de fonte.
- **A fila atual é pt-BR.** As 3 pautas em `aguardando_aprovacao` seguem pt-BR e
  já renderizadas; o gate humano decide. Esta rodada não as reescreve.
- **Modelo copiando exemplos.** O mesmo risco do pt-BR: o teste seco confere se o
  modelo escolhido gera ângulo novo em vez de repetir os exemplos em inglês.
- **Voz multilíngue vs voz en-US pura.** Se o MPT recusar uma voz multilíngue, a
  `en-US-GuyNeural-Male` é o fallback seguro e conhecido. O worker valida a voz
  no corpo da task, não em runtime — erro aparece cedo.

## 7. Definição de "aprovado sem ressalvas"

Os 7 critérios em **sim** com evidência arquivo:linha; identidade e exemplos em
inglês coerentes com os limites do render; modelo escolhido por evidência de teste
seco; suíte do worker **≥ 322** verde; RLS **29 ✅**; `next build` limpo; nenhum
secret. E a frase da rodada, verificável: **o gerador local escreve pauta em
inglês, no tom da marca, e o worker a narra com voz en-US — o canal virou gringo
sem tocar no schema nem no gate.**
