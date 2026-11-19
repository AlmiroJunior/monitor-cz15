#!/usr/bin/env python3
"""
Verificador de links — Cabine Zero 15
Roda a cada 15 minutos via GitHub Actions.

O que faz em cada execução:
1. Confere se cada uma das 111 páginas responde HTTP 200.
2. Dentro de cada página, acha o link do botão "Consultar disponibilidade"
   / WhatsApp e confere se ESSE link também funciona (não só a página em si).
3. Mede o tempo de resposta de cada página.
4. Se algo falhar, tenta de novo (até 3 checagens) antes de considerar
   incidente de verdade — evita alarme falso por instabilidade passageira.
   Antes de confirmar uma falha de conexão, testa a internet do próprio
   servidor do GitHub (sites de controle). Se a internet do GitHub caiu
   (ex.: "Network is unreachable"), NÃO é problema do site: nada é
   alertado e incidentes já abertos continuam como estavam.
5. Se confirmar incidentes novos, registra em data/incidents_week.csv e
   manda UM ÚNICO alerta (WhatsApp + e-mail) com a lista de todas as
   falhas confirmadas nesta execução — nunca um alerta por URL.
6. Se incidentes que estavam abertos foram resolvidos, marca a resolução
   no mesmo arquivo e manda UM ÚNICO alerta com a lista de tudo que
   voltou ao normal nesta execução.

Os e-mails de alerta usam sempre o mesmo assunto fixo e são encadeados
via cabeçalhos Message-ID / In-Reply-To / References, então o Gmail
agrupa tudo numa única conversa (o "thread" é reiniciado toda semana,
junto com o reset do incidents_week.csv, pelo weekly_report.py).

O arquivo data/incidents_week.csv é zerado semanalmente pelo weekly_report.py
depois de compilar e enviar o relatório — não vira um histórico permanente.
"""
import csv
import os
import re
import smtplib
import sys
import time
import datetime
import email.utils
import socket
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from email.message import EmailMessage

URLS_FILE = "urls.txt"
SITEMAP_URL = "https://www.cabinezero15.com.br/sitemap.xml"
INCIDENTS_FILE = "data/incidents_week.csv"
THREAD_ID_FILE = "data/thread_id.txt"
TIMEOUT = 15
# Esperas entre as checagens extras de uma página que falhou (segundos).
RETRY_WAITS = [20, 60]
# Endereços de controle: se NENHUM responder, a internet do servidor do
# GitHub caiu — a falha não é do site.
CONTROL_URLS = [
    "https://www.google.com/generate_204",
    "https://cloudflare.com/cdn-cgi/trace",
    "https://www.github.com/",
]
CTA_PATTERN = re.compile(r'href="(https://www\.cabinezero15\.com\.br/solicitar-orcamento\.html)"')

CALLMEBOT_PHONE = os.environ.get("CALLMEBOT_PHONE", "")
CALLMEBOT_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

# Assunto fixo (sem data/hora) — ajuda o Gmail a agrupar por thread mesmo
# quando os cabeçalhos de referência não bastam sozinhos.
SUBJECT_ALERTA = "Cabine Zero 15 — monitoramento de links"


_orig_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_ipv4_first(*args, **kwargs):
    """Tenta IPv4 primeiro: os servidores do GitHub Actions não têm IPv6."""
    res = _orig_getaddrinfo(*args, **kwargs)
    return sorted(res, key=lambda r: 0 if r[0] == socket.AF_INET else 1)


socket.getaddrinfo = _getaddrinfo_ipv4_first


def runner_online():
    """True se a internet do servidor do GitHub está funcionando."""
    for u in CONTROL_URLS:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "CabineZero15-LinkMonitor/2.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                if resp.status < 500:
                    return True
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return True
        except Exception:
            continue
    return False


def fetch(url):
    """Retorna (status_code, tempo_resposta_ms, corpo_texto_ou_None, erro_ou_None)."""
    req = urllib.request.Request(url, headers={"User-Agent": "CabineZero15-LinkMonitor/2.0"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            elapsed_ms = round((time.time() - start) * 1000)
            body = resp.read().decode("utf-8", errors="ignore")
            return resp.status, elapsed_ms, body, None
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.time() - start) * 1000)
        return e.code, elapsed_ms, None, None
    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000)
        return None, elapsed_ms, None, str(e)


def fetch_sitemap_urls():
    """
    Lê as páginas publicadas no sitemap.xml do site (só <loc> de página,
    ignora <image:loc>). Retorna um set vazio se o sitemap não puder ser lido
    — nesse caso o monitor segue só com o urls.txt, sem quebrar.
    """
    try:
        req = urllib.request.Request(SITEMAP_URL, headers={"User-Agent": "CabineZero15-LinkMonitor/2.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            root = ET.fromstring(resp.read())
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        found = {el.text.strip() for el in root.iter(ns + "loc") if el.text and el.text.strip()}
        return found
    except Exception as e:
        print(f"[aviso] Não foi possível ler o sitemap ({e}) — usando só o urls.txt.")
        return set()


def load_urls():
    """
    Lista de páginas monitoradas = urls.txt + tudo que estiver no sitemap.xml.
    Página nova publicada no site entra no monitoramento sozinha.
    Retorna (lista_de_urls, set_do_sitemap).
    """
    with open(URLS_FILE, encoding="utf-8") as f:
        manual = [line.strip() for line in f if line.strip()]
    sitemap = fetch_sitemap_urls()
    seen = set()
    urls = []
    for u in manual + sorted(sitemap):
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls, sitemap


def check_page(url):
    """
    Confere a página em si + o link do CTA dentro dela.
    Retorna um dict com o resultado.
    """
    status, elapsed_ms, body, err = fetch(url)

    result = {
        "url": url,
        "status": status,
        "response_ms": elapsed_ms,
        "ok": False,
        "reason": None,
    }

    if err:
        result["reason"] = f"falha de conexão: {err}"
        return result

    if status != 200:
        result["reason"] = f"HTTP {status}"
        return result

    # Página carregou — agora confere o link do CTA dentro dela (se existir um)
    m = CTA_PATTERN.search(body or "")
    if m:
        cta_url = m.group(1)
        cta_status, _, _, cta_err = fetch(cta_url)
        if cta_err or cta_status != 200:
            result["reason"] = f"página OK, mas o link do botão de orçamento está quebrado ({cta_err or cta_status})"
            return result

    result["ok"] = True
    return result


def send_whatsapp(message):
    if not CALLMEBOT_PHONE or not CALLMEBOT_APIKEY:
        print("[info] CALLMEBOT_PHONE/CALLMEBOT_APIKEY não configurados — pulando WhatsApp (ok, o e-mail cobre isso).")
        return
    import urllib.parse
    encoded = urllib.parse.quote(message)
    api_url = (
        f"https://api.callmebot.com/whatsapp.php?"
        f"phone={CALLMEBOT_PHONE}&text={encoded}&apikey={CALLMEBOT_APIKEY}"
    )
    try:
        urllib.request.urlopen(api_url, timeout=15)
    except Exception as e:
        print(f"[aviso] Falha ao enviar WhatsApp: {e}")


def get_thread_headers():
    """
    Garante que todos os e-mails de alerta da semana fiquem na mesma
    conversa do Gmail. Retorna (message_id_deste_email, in_reply_to, references).
    Na primeira chamada da semana (arquivo ainda não existe), este e-mail
    VIRA a raiz da conversa — os próximos referenciam ele.
    """
    os.makedirs("data", exist_ok=True)
    root_id = ""
    if os.path.exists(THREAD_ID_FILE):
        with open(THREAD_ID_FILE, encoding="utf-8") as f:
            root_id = f.read().strip()

    if root_id:
        new_id = email.utils.make_msgid(domain="cabinezero15.com.br")
        return new_id, root_id, root_id
    else:
        new_id = email.utils.make_msgid(domain="cabinezero15.com.br")
        with open(THREAD_ID_FILE, "w", encoding="utf-8") as f:
            f.write(new_id)
        return new_id, None, None


def send_email_alert(subject, message):
    if not EMAIL_FROM or not EMAIL_APP_PASSWORD or not EMAIL_TO:
        print("[aviso] Variáveis de e-mail não configuradas — não foi possível alertar por e-mail.")
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO

        msg_id, in_reply_to, references = get_thread_headers()
        msg["Message-ID"] = msg_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references

        msg.set_content(message)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_FROM, EMAIL_APP_PASSWORD)
            smtp.send_message(msg)
    except Exception as e:
        print(f"[aviso] Falha ao enviar e-mail de alerta: {e}")


def notify_batch(subject, whatsapp_text, email_text):
    """Manda UM alerta (WhatsApp + e-mail) cobrindo vários itens de uma vez."""
    send_whatsapp(whatsapp_text)
    send_email_alert(subject, email_text)


def rewrite_incidents(all_rows):
    os.makedirs("data", exist_ok=True)
    with open(INCIDENTS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "reason", "opened_at", "resolved_at"])
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)


def main():
    if not runner_online():
        print("[servidor do GitHub sem internet] Nada pode ser verificado agora — "
              "execução encerrada sem alertas e sem mudar o estado.")
        return

    urls, sitemap = load_urls()

    now = datetime.datetime.now().isoformat(timespec="seconds")
    print(f"Verificação iniciada: {now}")
    print(f"Total de páginas: {len(urls)} (sitemap: {len(sitemap)})\n")

    confirmed_broken = {}
    unknown = set()  # não deu pra verificar (internet do GitHub caiu) — estado mantido
    response_times = {}

    for url in urls:
        r = check_page(url)
        response_times[url] = r["response_ms"]
        if r["ok"]:
            print(f"[ok] {url} ({r['response_ms']} ms)")
            continue

        # HTTP 410 (Gone) numa página que NÃO está no sitemap = página
        # removida de propósito do site (ex.: cidades que deixaram de ser
        # atendidas). Não é incidente — só registra no log.
        if r["status"] == 410 and sitemap and url not in sitemap:
            print(f"[removida do site] {url} -> HTTP 410 e fora do sitemap — ignorada.")
            continue

        # Falhou — confirma com mais checagens antes de tratar como incidente real
        r2 = r
        for wait in RETRY_WAITS:
            print(f"[possível falha] {url} -> {r2['reason']} — confirmando de novo em {wait}s...")
            time.sleep(wait)
            r2 = check_page(url)
            if r2["ok"]:
                break
        if r2["ok"]:
            print(f"[falso alarme] {url} voltou ao normal na checagem extra.")
            continue

        # Falha de conexão: antes de culpar o site, confere a internet do GitHub
        if r2["status"] is None and not runner_online():
            print(f"[servidor do GitHub sem internet] {url} não pôde ser verificada — sem alerta.")
            unknown.add(url)
            continue

        print(f"[confirmado] {url} -> {r2['reason']}")
        confirmed_broken[url] = r2["reason"]

    # Reconcilia com o CSV de incidentes abertos
    all_rows = []
    if os.path.exists(INCIDENTS_FILE):
        with open(INCIDENTS_FILE, newline="", encoding="utf-8") as f:
            all_rows = list(csv.DictReader(f))

    urls_already_open = {row["url"] for row in all_rows if row.get("resolved_at", "") == ""}

    # --- Junta tudo que foi resolvido nesta execução (não notifica ainda) ---
    newly_resolved = []
    for row in all_rows:
        if row.get("resolved_at", "") == "" and row["url"] not in confirmed_broken and row["url"] not in unknown:
            row["resolved_at"] = now
            newly_resolved.append(row["url"])

    # --- Junta tudo que é incidente novo nesta execução (não notifica ainda) ---
    newly_broken = []
    for url, reason in confirmed_broken.items():
        if url not in urls_already_open:
            all_rows.append({"url": url, "reason": reason, "opened_at": now, "resolved_at": ""})
            newly_broken.append((url, reason))

    rewrite_incidents(all_rows)

    # --- Um único alerta por execução, juntando falhas E resoluções ---
    if newly_broken or newly_resolved:
        blocos_whatsapp = []
        blocos_email = []

        if newly_broken:
            linhas = [f"• {u}\n  Motivo: {motivo}" for u, motivo in newly_broken]
            blocos_whatsapp.append(f"🚨 {len(newly_broken)} problema(s) detectado(s):\n\n" + "\n\n".join(linhas))
            blocos_email.append(
                f"PROBLEMAS DETECTADOS ({len(newly_broken)})\n" + "\n\n".join(linhas)
            )

        if newly_resolved:
            linhas = [f"• {u}" for u in newly_resolved]
            blocos_whatsapp.append(f"✅ {len(newly_resolved)} página(s) voltaram ao normal:\n\n" + "\n".join(linhas))
            blocos_email.append(
                f"RESOLVIDOS ({len(newly_resolved)})\n" + "\n".join(linhas)
            )

        whatsapp_text = f"Cabine Zero 15 — {now}\n\n" + "\n\n---\n\n".join(blocos_whatsapp)
        email_text = f"Horário da verificação: {now}\n\n" + "\n\n---\n\n".join(blocos_email)
        notify_batch(SUBJECT_ALERTA, whatsapp_text, email_text)

    total_broken_now = len(confirmed_broken)
    extra = f" ({len(unknown)} não verificada(s) por queda de internet do GitHub)" if unknown else ""
    print(f"\nResumo: {len(urls) - total_broken_now - len(unknown)}/{len(urls)} páginas OK{extra}.")

    if total_broken_now:
        sys.exit(1)


if __name__ == "__main__":
    main()
