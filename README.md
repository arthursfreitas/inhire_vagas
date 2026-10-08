# Vagas InHire

Um buscador de vagas que roda no seu computador. Ele reúne vagas de centenas de empresas que usam a plataforma de recrutamento **InHire** e mostra tudo numa página simples, com filtros por **área** (desenvolvimento e design/UX), **senioridade**, **linguagem de programação**, **modelo de trabalho** e **empresa**.

> Você não precisa saber programar para usar. Basta copiar e colar alguns comandos no Terminal, como explicado abaixo.

---

## Sumário

1. [O que o projeto faz](#1-o-que-o-projeto-faz)
2. [O que você precisa ter](#2-o-que-você-precisa-ter)
3. [Instalação (passo a passo)](#3-instalação-passo-a-passo)
4. [Como usar no dia a dia](#4-como-usar-no-dia-a-dia)
5. [Guia da página de vagas](#5-guia-da-página-de-vagas)
6. [Como atualizar as vagas](#6-como-atualizar-as-vagas)
7. [Opções avançadas](#7-opções-avançadas)
8. [Como o projeto funciona por dentro](#8-como-o-projeto-funciona-por-dentro)
9. [Limitações](#9-limitações)
10. [Problemas comuns](#10-problemas-comuns)
11. [Perguntas frequentes](#11-perguntas-frequentes)

---

## 1. O que o projeto faz

O InHire é uma plataforma que muitas empresas brasileiras usam para publicar vagas. Cada empresa tem sua própria página, o que torna difícil procurar em todas ao mesmo tempo.

Este projeto faz três coisas:

1. **Descobre** as páginas de vagas das empresas, a partir de uma lista pública (o *sitemap* do InHire).
2. **Coleta** as vagas de cada empresa e, para as vagas de tecnologia e design, também a descrição completa, o local, o modelo de trabalho (remoto, híbrido ou presencial), o tipo de contrato, a data de publicação e o logo da empresa.
3. **Mostra** tudo numa página local, em `http://127.0.0.1:8000`, com busca e filtros.

Quando você clica em **Candidatar-se**, a página da vaga abre no site oficial da empresa. A candidatura sempre acontece lá, nunca aqui.

Tudo é salvo no seu computador. Nenhum dado seu é enviado a lugar nenhum.

## 2. O que você precisa ter

- Um computador com **macOS, Windows ou Linux**.
- **Python 3.9 ou mais novo**. É a única exigência.
- **Conexão com a internet**, para coletar as vagas e para carregar a fonte de letra da página.
- Um navegador comum (Chrome, Safari, Firefox, Edge).

Não é preciso instalar bibliotecas extras. O projeto usa só o que já vem com o Python.

## 3. Instalação (passo a passo)

### Passo 1: abrir o Terminal

- **macOS:** aperte `Cmd + Espaço`, digite `Terminal` e tecle Enter.
- **Windows:** clique no menu Iniciar, digite `PowerShell` e abra.
- **Linux:** abra o aplicativo "Terminal".

### Passo 2: conferir se o Python está instalado

Digite o comando abaixo e tecle Enter:

```bash
python3 --version
```

- Se aparecer algo como `Python 3.9.6` (ou número maior), está tudo certo.
- No **Windows**, se der erro, tente `python --version`. Nesse caso, use `python` no lugar de `python3` em todos os comandos deste guia.
- Se o Python não estiver instalado, baixe em <https://www.python.org/downloads/> e instale. No Windows, marque a opção **"Add Python to PATH"** durante a instalação.

### Passo 3: ir até a pasta do projeto

Você precisa "entrar" na pasta onde está o arquivo `inhire_jobs.py`. Se a pasta está em `projects/vagas_inhire`, por exemplo:

```bash
cd ~/projects/vagas_inhire
```

Dica: no macOS, digite `cd ` (com um espaço no final) e **arraste a pasta** do Finder para dentro do Terminal. O caminho é preenchido sozinho. Depois tecle Enter.

Para confirmar que está no lugar certo:

```bash
ls
```

Deve aparecer o arquivo `inhire_jobs.py` na lista. No Windows, use `dir`.

Pronto, a instalação acabou. Não há mais nada para instalar.

## 4. Como usar no dia a dia

### Primeira vez (precisa coletar as vagas)

Se a pasta ainda **não** tem o arquivo `inhire_jobs.json`, rode:

```bash
python3 inhire_jobs.py --collect --serve
```

O que acontece:

1. O programa lê a lista de empresas e testa quais páginas existem.
2. Coleta as vagas de cada uma. Você verá linhas como `[coleta] 120/628 ...`.
3. Busca os detalhes das vagas de tecnologia e design.
4. Salva tudo em `inhire_jobs.json` e liga a página local.

Isso leva **alguns minutos**. Quando aparecer `[frontend] http://127.0.0.1:8000`, abra esse endereço no navegador.

### Das próximas vezes (só abrir a página)

Se o `inhire_jobs.json` já existe, não precisa coletar de novo. Rode apenas:

```bash
python3 inhire_jobs.py --serve
```

E abra <http://127.0.0.1:8000>.

### Para fechar

Volte ao Terminal e aperte `Ctrl + C`. A página deixa de funcionar até você rodar o comando de novo.

> **Importante:** a janela do Terminal precisa ficar aberta enquanto você usa a página.

## 5. Guia da página de vagas

### Barra superior

- **Busca:** procura no cargo, na empresa, no local e nas tecnologias. Exemplo: `python`, `ux`, `curitiba`.
- **Vagas / Salvas / Ocultas:** alterna entre a lista normal, as vagas que você guardou com a estrela e as que você escondeu. O número ao lado mostra quantas há em cada uma.

### Filtros

Clique em cada botão para abrir a lista de opções. Os números ao lado das opções mostram quantas vagas existem *considerando os outros filtros que você já escolheu*.

| Filtro | O que faz |
|---|---|
| **Área** | "Tecnologia e Design" (padrão), só "Desenvolvimento", só "Design / UX" ou "Todas as áreas". |
| **Senioridade** | Estágio, Trainee, Júnior, Pleno, Sênior, Especialista, Liderança. Dá para marcar mais de uma. |
| **Linguagem** | Python, Java, JavaScript, TypeScript, C#/.NET, PHP, Go, React, Angular e outras. Dá para marcar mais de uma e há uma caixa de busca. |
| **Modelo** | Remoto, Híbrido ou Presencial. |
| **Empresa** | Mostra só as vagas de uma empresa. |

Outros controles:

- **Limpar filtros:** aparece quando há algum filtro ativo.
- **Ordenar:** mais recentes, empresa (A–Z) ou cargo (A–Z).

### Lista e detalhes

- **À esquerda**, a lista de vagas com logo, título, empresa, local, modelo, etiquetas e há quanto tempo foi publicada. A etiqueta **Nova** marca vagas que apareceram desde a sua última visita.
- **À direita**, os detalhes da vaga selecionada: resumo, descrição completa (quando disponível) e outras vagas da mesma empresa.
- **Candidatar-se** abre a vaga no site da empresa.
- **Salvar** (estrela) guarda a vaga na aba *Salvas*.
- **Ocultar** tira a vaga da lista. Você pode restaurá-la na aba *Ocultas*.
- Vagas que você já abriu ficam com o título mais claro.

### Atalhos do teclado

| Tecla | Ação |
|---|---|
| `/` | Ir para a busca |
| `j` ou seta para baixo | Próxima vaga |
| `k` ou seta para cima | Vaga anterior |
| `s` | Salvar ou remover a vaga atual |
| `Esc` | Fechar o filtro aberto |

### No celular

A lista ocupa a tela toda. Ao tocar numa vaga, os detalhes abrem por cima, com o botão **Voltar para a lista**.

### Compartilhar uma busca

Os filtros ficam no endereço da página. Copie e guarde o link para voltar à mesma busca depois.

### Onde ficam as vagas salvas?

As vagas salvas, ocultas e visitadas ficam guardadas **no seu navegador** (no próprio computador). Isso significa que:

- elas **não** passam para outro computador ou navegador;
- se você limpar os dados do navegador, elas somem.

## 6. Como atualizar as vagas

Vagas novas aparecem e outras fecham com frequência. Para atualizar, rode de novo a coleta:

```bash
python3 inhire_jobs.py --collect --serve
```

Uma boa rotina é atualizar uma vez por dia ou por semana. O arquivo `inhire_jobs.json` é substituído pela versão nova.

Se a página já estiver aberta, recarregue com `F5`. As vagas que não existiam antes ganham a etiqueta **Nova**.

## 7. Opções avançadas

Você pode combinar as opções abaixo ao rodar `python3 inhire_jobs.py`.

| Opção | Para que serve |
|---|---|
| `--collect` | Descobre as empresas e coleta as vagas. |
| `--discover` | Só descobre e valida as páginas das empresas, sem salvar vagas. Serve para conferir se a lista é lida. |
| `--serve` | Liga a página local. |
| `--port 9000` | Muda a porta (padrão: 8000). Útil se a 8000 estiver ocupada. |
| `--host 0.0.0.0` | Permite acessar de outros aparelhos da mesma rede. Use só em redes de confiança. |
| `--details tech` | Busca descrição, local e modelo só das vagas de tecnologia e design e de títulos parecidos (padrão). |
| `--details all` | Busca os detalhes de **todas** as vagas. Gera milhares de requisições e demora bem mais. |
| `--details none` | Não busca detalhes. É mais rápido, mas as vagas ficam sem descrição, local e modelo. |
| `--workers 8` | Quantas coletas acontecem ao mesmo tempo (padrão: 8). Aumentar acelera, mas sobrecarrega mais os servidores. Mantenha um valor moderado. |
| `--cache arquivo.json` | Usa outro arquivo para guardar as vagas. |
| `--source URL` | Usa outra fonte de lista de empresas (padrão: sitemap público do InHire). |
| `--local-source arquivo` | Usa um arquivo seu com a lista de endereços das empresas. |

Exemplos:

```bash
# Coleta rápida, sem detalhes, e abre em outra porta
python3 inhire_jobs.py --collect --details none --serve --port 9000

# Coleta tudo, com detalhes de todas as vagas
python3 inhire_jobs.py --collect --details all
```

## 8. Como o projeto funciona por dentro

Tudo está em um único arquivo, o `inhire_jobs.py`, dividido em partes:

1. **Descoberta:** lê o sitemap público do InHire, tira os nomes das empresas e testa se cada página `empresa.inhire.app/vagas` existe.
2. **Coleta:** para cada empresa, consulta a API pública que o próprio site do InHire usa e obtém a lista de vagas.
3. **Detalhes:** para as vagas de tecnologia e design, consulta os dados completos de cada vaga.
4. **Classificação:** olha o **título** da vaga e define:
   - se é de **desenvolvimento** ou **design/UX**, usando listas de palavras como "desenvolvedor", "engenheiro de software", "designer", "UX";
   - a **senioridade** ("júnior", "pleno", "sênior", "estágio", e também "I", "II" e "III" no fim do título);
   - as **linguagens**, a partir do título e da descrição.
5. **Servidor local:** entrega a página e os dados para o navegador, sem enviar nada para fora.
6. **Frontend:** é a própria página (HTML, CSS e JavaScript), embutida dentro do `inhire_jobs.py`.

Arquivos da pasta:

| Arquivo | O que é |
|---|---|
| `inhire_jobs.py` | O programa inteiro: coleta, classificação, servidor e página. |
| `inhire_jobs.json` | As vagas coletadas. É criado pela coleta e pode ser apagado a qualquer momento. |
| `README.md` | Este guia. |

### Conduta com os servidores

O programa usa apenas páginas e endereços públicos, identifica-se com um nome próprio (`User-Agent`), limita a quantidade de pedidos simultâneos e tenta novamente com intervalo crescente em caso de falha. Use com bom senso: não aumente demais o `--workers` e não rode a coleta em sequência a cada poucos minutos.

## 9. Limitações

- **A classificação é uma estimativa.** Ela se baseia no título e em listas de palavras. Vagas com títulos genéricos (como "Analista") podem ficar sem senioridade ou sem área. Algumas vagas podem ser classificadas de forma errada.
- **Linguagens vêm do texto.** Uma vaga que cita "Python" só como diferencial também recebe a etiqueta Python.
- **Vagas fora de tecnologia e design** normalmente não têm descrição, local nem modelo coletados. Para elas, use o link para o site da empresa ou rode `--details all`.
- **O programa só enxerga empresas listadas no sitemap público do InHire.** Empresas que usam o InHire, mas não aparecem lá, ficam de fora.
- **Os dados são uma foto do momento da coleta.** Uma vaga pode ter fechado depois. Se o link mostrar que ela não existe mais, é por isso.
- **Depende da estrutura atual do InHire.** Se a plataforma mudar o site ou a API, a coleta pode parar de funcionar e o script precisaria ser ajustado.

## 10. Problemas comuns

**`python3: command not found` (ou "não reconhecido")**
O Python não está instalado ou não está no PATH. Instale pelo site oficial. No Windows, tente `python` no lugar de `python3`.

**`can't open file ... inhire_jobs.py`**
Você não está na pasta certa. Volte ao [Passo 3](#passo-3-ir-até-a-pasta-do-projeto).

**A página abre, mas mostra "Nenhuma vaga carregada"**
A coleta ainda não foi feita. Rode `python3 inhire_jobs.py --collect --serve`.

**Aparece "Dados de demonstração"**
A página não conseguiu falar com o programa. Confirme que o Terminal continua aberto com `--serve` rodando e que você abriu `http://127.0.0.1:8000`.

**`Address already in use`**
A porta 8000 está ocupada, talvez por uma execução anterior. Feche o outro Terminal ou use outra porta: `--port 8001` (e abra `http://127.0.0.1:8001`).

**Não foi possível ler o sitemap**
Verifique sua conexão com a internet e tente de novo. Se persistir, o endereço do sitemap pode ter mudado. Use `--source` ou `--local-source`.

**A coleta está lenta**
É normal levar alguns minutos. Para ficar mais rápida, use `--details none`.

**Os logos ou as fontes não aparecem**
Eles são carregados da internet. Sem conexão, a página funciona, mas com letras e ícones padrão.

**Salvei vagas e elas sumiram**
As vagas salvas ficam no navegador. Se você trocou de navegador, usou janela anônima ou limpou os dados do navegador, elas não estarão lá.

## 11. Perguntas frequentes

**Preciso pagar ou criar conta?**
Não. O projeto é gratuito e não pede login.

**Isso candidata por mim automaticamente?**
Não. O botão **Candidatar-se** só abre a vaga no site da empresa, onde você se candidata normalmente.

**É seguro? Meus dados vão para algum lugar?**
Os dados ficam no seu computador. O programa só faz consultas às páginas públicas do InHire. A página roda em `127.0.0.1`, que é um endereço acessível só por você.

**Posso usar para outras áreas, como marketing ou vendas?**
A coleta traz as vagas de todas as áreas, e o filtro **Área → Todas as áreas** as exibe. Os filtros de senioridade, modelo e empresa funcionam para qualquer área. Os filtros de linguagem e design foram pensados para tecnologia.

**Como adiciono mais palavras para reconhecer vagas?**
No começo do `inhire_jobs.py` há as listas `DEV_TERMS`, `DESIGN_TERMS`, `LANGUAGES` e `SENIORITY_TERMS`. Basta acrescentar termos (em minúsculas e sem acentos) e reiniciar o programa. Como a classificação é refeita ao abrir a página, não é necessário coletar de novo.

**Como desinstalo?**
Apague a pasta do projeto. Não há nada instalado no sistema.
