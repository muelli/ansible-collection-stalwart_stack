#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["dkimpy", "pyspf", "pynacl", "dnspython"]
# ///
"""Send one test mail from every domain of this Stalwart to a throwaway mail.tm mailbox and report
what arrived: DKIM signatures, SPF/auth results, return path, first hop. Nothing is printed that
contains a password. Runs on the Stalwart host with stalwart-env (admin login in the environment).
It also validates what arrived the way a receiver would: every DKIM signature (key from public DNS),
SPF for the sending address (with the number of DNS lookups it took; the limit is 10) and DMARC.
Run it with `uv run --script mail_probe.py ...` and uv installs the dependencies named in the header
(dkimpy, pyspf, pynacl for ed25519 signatures, dnspython); without uv they must be importable.
Environment: STALWART_CLI is the command that runs stalwart-cli (default /usr/local/bin/stalwart-cli;
"ssh host stalwart-env stalwart-cli" works from elsewhere), PROBE_SMTP the host:port of the
submission port (default 127.0.0.1:587), PROBE_DUMP_RAW a directory to keep each received message in.
usage: mail_probe.py [--wait SECONDS] [--resolver IP] name:id [name:id ...]   -> JSON on stdout"""
import email, email.utils, json, os, re, secrets, shlex, smtplib, ssl, subprocess, sys, time, urllib.request, urllib.error
try:
    import dkim, dns.resolver, spf
    import nacl  # noqa: F401  (ed25519 signatures)
except ImportError as e:
    # exit 3 tells the role what is missing; it prints the packages, it installs nothing
    print("missing python module: %s" % e.name, file=sys.stderr)
    sys.exit(3)

API = "https://api.mail.tm"
# The body of the test mails. mail.tm hands back a source with blank lines added around the body, which
# breaks every body hash, so the signatures are checked against the headers received and this body.
BODY = "probe\r\n"
CLI = shlex.split(os.environ.get("STALWART_CLI", "/usr/local/bin/stalwart-cli"))
SMTP_HOST, _, SMTP_PORT = os.environ.get("PROBE_SMTP", "127.0.0.1:587").partition(":")
_last = [0.0]


def call(method, path, body=None, token=None):
    # mail.tm allows 8 requests per second; stay well under it
    wait = 0.25 - (time.monotonic() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + attempt * 2)
                continue
            raise
    raise RuntimeError("mail.tm kept answering 429")


def members(x):
    return x if isinstance(x, list) else x.get("hydra:member", [])


def cli(*args, stdin=None):
    return subprocess.run([*CLI, *args, "--no-color"], input=stdin, capture_output=True, text=True)


def main():
    wait_s = 90
    args = sys.argv[1:]
    while args[:1] in (["--wait"], ["--resolver"]):
        if args[0] == "--wait":
            wait_s = int(args[1])
        else:
            RESOLVER.nameservers = [args[1]]
        args = args[2:]
    domains = [a.rsplit(":", 1) for a in args]
    tag = secrets.token_hex(3)

    doms = members(call("GET", "/domains"))
    mdom = next(d["domain"] for d in doms if d.get("isActive"))
    maddr = "probe-" + secrets.token_hex(5) + "@" + mdom
    mpw = secrets.token_urlsafe(18)
    acc = call("POST", "/accounts", {"address": maddr, "password": mpw})
    token = call("POST", "/token", {"address": maddr, "password": mpw})["token"]
    results = {d: {"domain": d, "sent": False} for d, _ in domains}
    ctx = ssl._create_unverified_context()
    try:
        for name, did in domains:
            r = results[name]
            user = "probe" + secrets.token_hex(3)
            pw = secrets.token_urlsafe(18)
            payload = {"@type": "User", "name": user, "domainId": did,
                       "credentials": {"0": {"@type": "Password", "secret": pw}}}
            c = cli("create", "Account", "--stdin", stdin=json.dumps(payload))  # not on the command line
            if c.returncode != 0:
                r["error"] = "account: " + (c.stderr or c.stdout).strip().replace(pw, "***")[:200]
                continue
            aid = c.stdout.split()[-1]
            addr = f"{user}@{name}"
            subject = f"probe-{tag}-{name}"
            try:
                s = smtplib.SMTP(SMTP_HOST, int(SMTP_PORT or 587), timeout=40)
                s.ehlo(); s.starttls(context=ctx); s.ehlo(); s.login(addr, pw)
                msg = (f"From: Probe <{addr}>\r\nTo: {maddr}\r\nSubject: {subject}\r\n"
                       f"Message-ID: <{tag}.{user}@{name}>\r\nDate: {email.utils.formatdate()}\r\n\r\n" + BODY)
                s.sendmail(addr, [maddr], msg)
                s.quit()
                r["sent"] = True
                r["subject"] = subject
            except Exception as e:
                r["error"] = "send: " + str(e).replace(pw, "***")[:200]
            finally:
                cli("delete", "Account", "--ids", aid)
            time.sleep(1)

        pending = {r["subject"]: r for r in results.values() if r.get("sent")}
        deadline = time.monotonic() + wait_s
        while pending and time.monotonic() < deadline:
            time.sleep(5)
            for m in members(call("GET", "/messages", token=token)):
                r = pending.get(m["subject"])
                if not r:
                    continue
                src = call("GET", "/sources/" + m["id"], token=token)["data"]
                parse(r, src)
                pending.pop(m["subject"])
    finally:
        try:
            call("DELETE", "/accounts/" + acc["id"], token=token)
        except Exception:
            pass
    # a marker, so a caller can tell the result from whatever else lands in the same stream
    sys.stdout.write("@@PROBE-JSON@@")
    json.dump(list(results.values()), sys.stdout, indent=1)


class CountingResolver(dns.resolver.Resolver):
    """Counts the DNS requests of one phase (dkim, spf, dmarc), whoever makes them."""
    phase = "other"
    counts = {}

    def resolve(self, qname, rdtype="A", *a, **k):
        self.counts[self.phase] = self.counts.get(self.phase, 0) + 1
        return super().resolve(qname, rdtype, *a, **k)


RESOLVER = CountingResolver(configure=False)
RESOLVER.nameservers = ["1.1.1.1"]
RESOLVER.lifetime = 6
dns.resolver.default_resolver = RESOLVER


def txt_records(name):
    try:
        return ["".join(p.decode() for p in rr.strings) for rr in RESOLVER.resolve(name, "TXT")]
    except Exception:
        return []


def aligned(a, b, strict):
    a, b = (a or "").lower().rstrip("."), (b or "").lower().rstrip(".")
    if strict:
        return a == b
    # relaxed: the same organizational domain. Without the public suffix list this accepts a
    # name and its parent domains only, not two sibling subdomains.
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def parse(r, raw):
    if os.environ.get("PROBE_DUMP_RAW"):
        with open(os.path.join(os.environ["PROBE_DUMP_RAW"], r["domain"] + ".eml"), "w", newline="") as f:
            f.write(raw)
    m = email.message_from_string(raw)
    r["received"] = True
    r["return_path"] = (m.get("Return-Path") or "").strip()
    r["dkim"] = []
    for h in m.get_all("DKIM-Signature", []):
        tags = dict(t.strip().split("=", 1) for t in " ".join(h.split()).split(";") if "=" in t)
        r["dkim"].append({"d": tags.get("d"), "s": tags.get("s"), "a": tags.get("a")})
    r["auth_results"] = [" ".join(h.split()) for h in m.get_all("Authentication-Results", [])]
    r["received_spf"] = [" ".join(h.split()) for h in m.get_all("Received-SPF", [])]
    r["received_chain"] = [" ".join(h.split())[:300] for h in m.get_all("Received", [])]
    CountingResolver.counts = {}
    try:
        validate(r, m, raw)
    except Exception as e:  # a bug here must not lose the rest of the report
        r["validate_error"] = repr(e)
    r["dns_requests"] = dict(CountingResolver.counts)
    r["dns_requests"]["total"] = sum(CountingResolver.counts.values())


CRLF = chr(13) + chr(10)
LF = chr(10)
RECEIVED_FROM = re.compile(r"from (\S+) \((?:\S+ )?\[([0-9a-fA-F:.]+)\]")


def validate(r, m, raw):
    head = raw.replace(CRLF, LF).split(LF * 2, 1)[0]
    msg = (head.replace(LF, CRLF) + CRLF * 2 + BODY).encode()
    from_domain = email.utils.parseaddr(m.get("From", ""))[1].rsplit("@", 1)[-1].lower()

    # DKIM: each signature on its own, the key comes from public DNS
    def dnsfunc(name, timeout=5):
        n = name.decode() if isinstance(name, bytes) else name
        t = txt_records(n)
        return t[0].encode() if t else None

    RESOLVER.phase = "dkim"
    for i, sig in enumerate(r["dkim"]):
        try:
            sig["ok"] = bool(dkim.DKIM(msg).verify(idx=i, dnsfunc=dnsfunc))
        except Exception as e:
            sig["ok"], sig["error"] = False, str(e)[:160]
        sig["aligned"] = aligned(sig["d"], from_domain, False)

    # SPF: the address that handed the mail to the receiver, as the receiver saw it
    RESOLVER.phase = "spf"
    hop = (r["received_chain"] or [""])[0]
    mm = RECEIVED_FROM.match(hop)
    helo, ip = (mm.group(1), mm.group(2)) if mm else ("", "")
    mailfrom = r["return_path"].strip("<>") or ""
    spf_info = {"ip": ip, "helo": helo, "mailfrom": mailfrom}
    if ip and mailfrom:
        q = spf.query(ip, mailfrom, helo, receiver="mail.tm")
        res, code, expl = q.check()
        spf_info.update(result=res, explanation=expl, lookups=getattr(q, "lookups", None), limit=10,
                        dns_requests=CountingResolver.counts.get("spf", 0))
    else:
        spf_info.update(result="none", explanation="no connecting address or return path found")
    r["spf"] = spf_info
    spf_domain = mailfrom.rsplit("@", 1)[-1].lower()

    # DMARC: record of the From domain, else of its parent domains (no public suffix list)
    RESOLVER.phase = "dmarc"
    labels = from_domain.split(".")
    record, found_at = None, None
    for k in range(len(labels) - 1):
        name = ".".join(labels[k:])
        recs = [t for t in txt_records("_dmarc." + name) if t.lower().startswith("v=dmarc1")]
        if recs:
            record, found_at = recs[0], name
            break
    dm = {"from_domain": from_domain, "record": record, "found_at": found_at}
    if record:
        tags = dict(t.strip().split("=", 1) for t in record.split(";") if "=" in t)
        tags = {k.strip().lower(): v.strip() for k, v in tags.items()}
        policy = tags.get("sp", tags.get("p")) if found_at != from_domain else tags.get("p")
        dkim_ok = any(s.get("ok") and aligned(s["d"], from_domain, tags.get("adkim", "r").lower() == "s")
                      for s in r["dkim"])
        spf_ok = spf_info["result"] == "pass" and aligned(spf_domain, from_domain,
                                                          tags.get("aspf", "r").lower() == "s")
        dm.update(policy=policy, pct=tags.get("pct", "100"), dkim_aligned=dkim_ok, spf_aligned=spf_ok,
                  result="pass" if (dkim_ok or spf_ok) else "fail", rua=tags.get("rua"))
    else:
        dm.update(result="none", policy=None)
    r["dmarc"] = dm


if __name__ == "__main__":
    main()
