# O `obra/` operado pelo painel local

**Pedido do dono (2026-08-31):** *"seta ele pra funcionar dentro daquele painel
controle"*.

Painel correto, e o `CLAUDE.md` já dizia qual: **operação de máquina nasce no
`worker/controle.py`**, nunca no `painel/` da Vercel. Rodar ffmpeg, abrir pasta e
copiar prompt são coisas que só existem ao lado da máquina; a Vercel nem alcança
o PC (ADR-05).

---

## 1. Escopo

Um cartão **OBRA** no `worker/controle.py` que opera o módulo `obra/`:

1. **escolher/criar projeto** — combo dos existentes + `＋ novo` com o cenário;
2. **▶ Próximo estágio** — a janela do dia a dia: o prompt de imagem e o de
   vídeo com **botão de copiar**, o caminho do frame para anexar, e o botão que
   **abre a pasta dos clipes** no Explorer;
3. **🔍 Checar** — o laudo numa janela rolável;
4. **🎬 Montar** — roda a montagem e oferece abrir o `final.mp4`.

---

## 2. A decisão que define tudo: processo separado, nunca import

O painel **não importa** nada do `obra/`. Chama `montar.py` como subprocesso.

Não é preferência de estilo — é a única forma que funciona, e foi medida:

```python
sys.path.insert(0, str(worker))   # como o controle.py roda
sys.path.insert(0, str(obra))     # "só acrescentar o obra no path"
import config
#  -> obra/config.py     ← o obra VENCEU o nome, e o worker quebra
```

`worker/config.py` e `obra/config.py` têm o mesmo nome de módulo. Qualquer ordem
de `sys.path` faz um dos dois vencer e o outro receber silenciosamente a Config
errada — `AttributeError` num campo que não existe, longe da causa. E não é só
`config`: o `obra/` inteiro usa import flat (`from projeto import ...`) porque o
`pyproject.toml` dele declara `pythonpath = ["."]`.

**Subprocesso resolve os dois de uma vez:** o Python põe o diretório do script em
`sys.path[0]`, então `obra/montar.py` carrega os módulos do `obra/` e ninguém
disputa nome com ninguém.

**E não precisa do `uv`.** O `obra/` tem **zero dependência de runtime** — é a
razão pela qual isso é barato. Medido: o `python.exe` do venv do worker (3.11.15)
roda `obra/montar.py` sem instalar nada. O `sys.executable` do próprio painel
serve, e o `uv` vira fallback, não requisito.

**A direção da dependência é `worker → obra`, e só.** O `obra/` continua sem
saber que o painel existe, sem Supabase e sem `.env` — quem quiser rodá-lo pela
CLI continua podendo, e o dia em que o worker for aposentado ele não leva o
`obra/` junto.

---

## 3. `listar --json`: um contrato, não um parser

O cartão precisa de dados estruturados (quantos clipes, quantos sons, qual o
próximo estágio). Raspar o texto do laudo seria criar um parser que quebra na
primeira vez que alguém melhorar uma frase.

Então `montar.py listar [slug] --json` emite JSON. É a única adição ao `obra/`
nesta rodada, e ela é honesta: saída legível por máquina para um consumidor que é
máquina. O texto humano continua idêntico sem a flag.

**O painel nunca lê a pasta de projetos por conta própria.** Contar `clip_*.mp4`
no `controle.py` duplicaria em Python o que `Projeto.clipes_presentes()` já sabe,
e as duas cópias divergiriam na primeira mudança de nome de arquivo.

---

## 4. O que o cartão faz que a CLI não faz

Se fosse só rodar o mesmo comando, o cartão não valeria o código. O que ele
acrescenta é o que **só existe numa GUI**:

- **copiar o prompt para a área de transferência.** O ciclo inteiro é
  copiar-e-colar numa ferramenta web; num terminal isso é seleção com o mouse,
  que quebra em texto de 20 linhas.
- **abrir a pasta dos clipes no Explorer.** O passo seguinte é salvar um mp4 com
  nome exato naquela pasta — e é o passo em que o dono mais erra o nome.
- **abrir o `final.mp4`** quando a montagem termina.

---

## 5. Restrições que o painel impõe

- **Nada bloqueia a interface.** `checar` roda ffprobe e ffmpeg em 13 clipes;
  `montar` faz duas passadas. Tudo em `threading.Thread` com `raiz.after(0, …)`
  para voltar, no molde de `acao_gerar`/`acao_limpar`.
- **Trava por ação, nunca compartilhada.** É a regra que o cartão de produção já
  segue: uma montagem de 12s não pode deixar o botão de checar mudo sem explicar.
- **Mensagem de erro nunca traz exceção crua** — `type(e).__name__`, como o resto
  do arquivo.
- **O cartão aparece mesmo sem projeto nenhum**, com o `＋ novo` habilitado e os
  outros três desabilitados. Cartão que some quando está vazio ensina que a
  função não existe.
- **O `obra/` ausente não pode derrubar o painel.** Quem clona só o `worker/`
  continua com um painel que sobe; o cartão mostra o motivo e fica inerte.

---

## 6. Critérios de aceite

1. `worker/controle.py` **não importa** `config`, `projeto`, `montagem`,
   `checar`, `prompts`, `cenarios` nem `frames` do `obra/` — nem direta nem
   indiretamente. `grep` prova.
2. `worker/obra_ponte.py` monta os comandos em função **pura** e testada; o que
   fala com processo é separado e dublado nos testes.
3. Nenhum teste do worker precisa do `obra/` instalado, de ffmpeg ou de disco
   real: o subprocesso é dublado.
4. `montar.py listar --json` devolve JSON válido com, no mínimo: `projetos` (a
   lista) e, quando houver slug, `slug`, `clipes_presentes`, `clipes_faltando`,
   `proximo_estagio`, `estagios_com_som`, `estagios_sem_som`, `modo_do_som`,
   `total_estagios`, `tem_final`.
5. `montar.py listar` **sem** `--json` emite exatamente o texto de hoje, byte a
   byte (teste de não-regressão).
6. O painel resolve o interpretador por `sys.executable` e cai para o `uv` só se
   precisar — e a escolha é função pura, testada nos dois caminhos.
7. `obra/` ausente ou sem `montar.py`: o painel sobe, o cartão explica e nenhum
   botão levanta exceção.
8. As quatro ações rodam em thread; nenhuma bloqueia o `mainloop`.
9. A janela do próximo estágio tem botão de copiar para os **dois** prompts, o
   caminho do frame de referência visível e o botão que abre a pasta dos clipes.
10. A suíte do worker cresce e **continua verde** (era 620); a do `obra/`
    continua verde (era 792) e **nenhum** arquivo do `obra/` muda além de
    `montar.py` e do teste dele.
11. `painel/` e `supabase/` intocados; nenhuma migration.

---

## 7. Resultado da review

**Aprovado.** Os 11 critérios em sim. Suítes: **worker 741** (eram 620) e
**obra 799** (eram 792). `painel/` e `supabase/` intocados, nenhuma migration.

### 7.1 Verificado abrindo a janela de verdade, não só em teste

Nenhum teste do repositório abre Tk — e um erro de layout só aparece em runtime.
Então o painel foi construído três vezes com um `mainloop` real, invisível
(`-alpha 0`) e com fechamento agendado, para não pular na tela de ninguém:

| Estado | O que apareceu |
|---|---|
| projeto incompleto | `▶ Próximo estágio (01/13)`, os 4 botões ativos |
| clique no botão principal | a janela abriu com `copiar prompt base`, `copiar prompt de imagem`, `copiar prompt de vídeo`, `📂 abrir pasta dos clipes`, `fechar` |
| `obra/` ausente | **o painel subiu** (`abrir_janela() = 0`), os 4 botões `disabled`, e a frase *"a pasta obra/ não está ao lado do worker/ neste clone"* na tela |

### 7.2 Três defeitos achados nesta rodada, todos meus

**O padrão de argumento congelado no import.** `motivo_da_ausencia(obra: Path =
OBRA)` capturava `OBRA` na definição do módulo, então trocar `obra_ponte.OBRA`
depois não mudava nada. Descoberto **escrevendo o teste do critério 7**: ele
afirmava que o painel sobrevive ao `obra/` ausente e estava, na verdade, medindo
o `obra/` presente e funcionando — veredito verde sobre a pergunta errada. Os
caminhos passaram a ser resolvidos na chamada, e o teste então mostrou os quatro
botões mortos e a frase certa.

**O interpretador caía no `uv` por padrão**, contra o que a própria docstring
dizia. Num painel aberto pelo Task Scheduler — que tem outro PATH, armadilha que
a Sprint 7 já pagou — isso quebraria o cartão inteiro. Passou a ser
`sys.executable` primeiro, com o `uv` como plano B para `sys.executable` vazio.

**`Resultado.resumo` era a última linha**, e o `montar.py` fecha toda ação bem
sucedida com o mesmo lembrete de postagem: o messagebox diria *"o rótulo de IA é
obrigatório nas duas plataformas"* em vez de dizer onde o vídeo foi parar. Virou
o **primeiro parágrafo**, que é o bloco do resultado — `MONTADO — <caminho>` mais
duração e loudness — e que também é a mensagem de erro quando há uma.

### 7.3 O fatiador de prompts pegava prosa por título

`separar_prompts` classificava qualquer linha começada em `PROMPT `, e a saída do
`proximo` tem um passo a passo que diz *"3. … cole o PROMPT DE VÍDEO"*. Medido
contra a saída real: essa linha abria um bloco falso, e só não estragou nada
porque o título de verdade vinha depois e sobrescrevia. Bastaria a prosa mudar de
lugar para o botão de copiar entregar o texto errado, **calado**. O título passou
a valer só imediatamente depois da régua de hifens.

### 7.4 Dois desvios deliberados, e os dois estão certos

- **`ObraIndisponivel` mostra a mensagem própria**, não só `type(e).__name__`. É
  exceção nossa, escrita para o dono ler, e o § 5 pede que o cartão explique o
  motivo. Toda outra exceção segue a regra da casa.
- **`🎬 Montar` recusado manda a saída inteira para a janela**, não o `resumo`:
  numa recusa, a parte acionável é a lista dos clipes que faltam.

### 7.5 O que o cartão deliberadamente NÃO faz

Não entra no tique de 5s do `agendar`. Cada leitura sobe um processo Python, e
doze vezes por minuto seria gastar CPU para reler o mesmo número. Ele relê na
abertura, na troca de projeto e no fim de cada ação — que são os três momentos em
que o número muda.
