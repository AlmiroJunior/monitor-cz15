# Monitor de links v2 — Cabine Zero 15

Verifica as 111 páginas do site a cada 15 minutos, incluindo se o link
do botão "Consultar disponibilidade" dentro de cada página funciona
(não só se a página carrega). Manda alerta instantâneo no WhatsApp
quando algo quebra ou é resolvido, e um relatório completo em Excel
por e-mail toda segunda-feira — sem manter histórico permanente no
repositório.

## Passo 1 — Criar o repositório, público desta vez

1. `github.com/new`
2. Nome: `monitor-cz15` (ou outro nome).
3. Marca **Public** (não Private — é o que dá minutos ilimitados de graça).
4. Create repository.

## Passo 2 — Subir os arquivos

1. "uploading an existing file" → arrasta: `check_links.py`,
   `weekly_report.py`, `requirements.txt`, `urls.txt`, `COMO-USAR.md`,
   e a pasta `data` (com `incidents_week.csv` dentro).
2. Commit changes.
3. Depois, os dois arquivos que precisam ficar dentro de pasta —
   criar um de cada vez em **Add file → Create new file**:
   - Nome: `.github/workflows/check-links.yml` → cola o conteúdo do
     arquivo `check-links.yml` que veio junto.
   - Nome: `.github/workflows/weekly-report.yml` → cola o conteúdo do
     arquivo `weekly-report.yml`.

## Passo 3 — Configurar o WhatsApp (CallMeBot) — opcional por enquanto

O CallMeBot é um serviço grátis mantido por uma pessoa só, e de vez em
quando ele fica "cheio" (lotado de novos números) por alguns dias. Se
acontecer isso com você, **não trava nada** — o alerta instantâneo já
vai por e-mail também (configurado no Passo 4), então você continua
recebendo aviso na hora mesmo sem o WhatsApp.

Quando quiser tentar o WhatsApp:
1. Salva no seu celular o número: **+34 644 20 47 56** (contato do CallMeBot).
2. Manda pra esse contato, pelo WhatsApp: `I allow callmebot to send me messages`
3. Espera a resposta automática — ela vem com sua **APIKEY** (um número).
   Se vier "This Bot is full", espera alguns dias e tenta de novo.
4. Renomeia esse contato pra algo como "Monitor Cabine Zero 15" e fixa a conversa.

## Passo 4 — Configurar o e-mail (Gmail)

Já que o e-mail que você usa é do Gmail, precisa gerar uma **Senha de App**
(não é a senha normal da conta):

1. Vai em `myaccount.google.com/apppasswords` (precisa ter verificação em
   duas etapas ativada na conta — se não tiver, ativa primeiro em
   `myaccount.google.com/security`).
2. Cria uma senha de app nova, nome "monitor-cz15".
3. Copia a senha gerada (16 letras, sem espaço).

## Passo 5 — Adicionar os Secrets no GitHub

No repositório: **Settings → Secrets and variables → Actions → New
repository secret**. Cria os 3 de e-mail (obrigatórios) e os 2 do
CallMeBot (só se você já tiver conseguido a apikey — sem eles, o
script funciona normal, só sem o canal WhatsApp):

| Nome | Valor | Obrigatório? |
|---|---|---|
| `EMAIL_FROM` | Seu e-mail Gmail | Sim |
| `EMAIL_APP_PASSWORD` | A senha de app de 16 letras do Passo 4 | Sim |
| `EMAIL_TO` | Pra qual e-mail mandar o relatório (pode ser o mesmo) | Sim |
| `CALLMEBOT_PHONE` | Seu número de WhatsApp, formato `+5515...` | Não |
| `CALLMEBOT_APIKEY` | A apikey que o CallMeBot te mandou | Não |

## Passo 6 — Testar

1. Aba **Actions** do repositório.
2. Clica em **"Verificação de links — Cabine Zero 15"** → **Run workflow**
   → confirma. Espera terminar (bolinha verde ou vermelha).
3. Clica em **"Relatório semanal — Cabine Zero 15"** → **Run workflow**
   → confirma. Se tudo estiver certo, chega um e-mail com o Excel em
   alguns segundos.

Se algum desses passos der erro, me manda o print da mensagem de erro
que aparece na tela do "Actions" — geralmente indica exatamente qual
secret está faltando ou errado.
