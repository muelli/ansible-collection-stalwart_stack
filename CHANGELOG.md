# Changelog

## Unreleased

## 0.2.0

- `certificate: acme` on a `stalwart_domains` entry lets Stalwart order the certificates of that domain itself
  (DNS-01 through the domain's DNS management) instead of copying them from Caddy. `acme_names` lists the
  names explicitly (they end up in one multi-SAN certificate; an empty list did not issue on the Stalwart
  version tested), `stalwart_acme_providers` defines the ACME accounts, and caddy_front neither serves nor
  copies certificates for such a domain. An `AcmeRenewal` task is created for names without a certificate.
  Not allowed together with `serve_http: true`.
- `fallback` on a `caddy_user_instances` entry adds a catch-all `http://` block to the account's Caddyfile:
  the answer for every host of the instance that no site names.
- `caddy_user_instances`: the front socket no longer hits systemd's trigger limit (a Caddy that cannot start
  made it fail for good), a failed or half-restarted socket is recovered by stopping the lingering proxy
  and clearing the failed state, and every task names the account it works on.
- `stalwart_webhooks` has a healthchecks.io example in the defaults.
- caddy_front: `certificate` need not be set on `stalwart_domains` entries (an Ansible filter failed on a
  missing attribute).
- stalwart_config creates a DnsManagement task for each automatically managed domain whose published MX or CNAME records name another host than Stalwart's zone file (`stalwart_dns_republish`).
- `stalwart_check_mail_healthcheck_uuid` pings healthchecks.io after the mail check (`/fail` with the problems when there are any).
- `stalwart_check_mail_only: true` runs only the mail check and ends stalwart_config before anything is applied.
- After the apply, stalwart_config checks that every DNS record Stalwart wants for a domain exists in
  public DNS (`dig` on the controller) and that each published MX host answers STARTTLS on port 25
  with a certificate valid for its name; an MX that differs from what Stalwart wants is reported too.
  Problems are printed, `stalwart_check_mail_fatal: true` fails the run, `stalwart_check_mail: false`
  turns it off.
  The check also covers DMARC report authorization (`_report._dmarc`), the MTA-STS policy over HTTPS,
  MX hosts without addresses or behind a CNAME, and the reverse names of the server's addresses.
  `stalwart_check_mail_send: true` additionally sends a test mail from every domain to a throwaway
  mail.tm mailbox and validates DKIM, SPF (with its DNS lookup count) and DMARC (`files/mail_probe.py`,
  a uv script; without uv the check names the Python packages it needs and installs nothing).
- `stalwart_webhooks` manage Stalwart webhooks (matched by `url`): bearer or basic auth, HMAC
  signature key, headers, level, timeouts; the default events (`stalwart_webhook_default_events`)
  are the DNS, ACME and certificate failures, because registry sets take event names, not
  wildcards. `state: absent` deletes by id (a webhook cannot be filtered by URL).
- `stalwart_enforce_from_header: true` makes Stalwart refuse submitted mail whose From address
  differs from the envelope sender (which Stalwart already forces to be the user's own address),
  or that has several From addresses: a DATA-stage Sieve script `from-check`, run for
  authenticated sessions except `stalwart_enforce_from_header_except`. Tested on a real host
  with SMTP submission; JMAP submission (Bulwark) was not tested. `false` removes the hook.
- Stalwart 1.1.1 (checksums for x86_64 and aarch64) and Bulwark 1.21.3 are the new defaults.
  stalwart-cli is 2.0.0 (released the same day; checksums for x86_64 and aarch64). Its output
  changed (`Linked by:  Account <id>` instead of `Account#<id>`); the roles read the group
  members of a failed group deletion in both forms. Checked on a real host: apply, apply failures
  with the hints, deletes, queries and gets, the TLS reload action, and the recovery fallback.
- `stalwart_enforce_from_header` also holds for JMAP submission (webmail): Stalwart sends it
  through the same DATA stage, and a spoofed From is refused with `forbiddenToSend`.

- `stalwart_install` installs `/usr/local/bin/stalwart-env`: `stalwart-env stalwart-cli ...` (or
  `vandelay ...`) runs a command with the administrator login of `cli.env`, from any shell,
  including fish, which cannot source that file. Root only.
- `stalwart_collections` entries take `properties` (JMAP properties such as `color` or
  `isSubscribed`, compared before writing) and `rename_from` (rename in place; fails when
  both names exist).
- `stalwart_recipient_policies` decides per recipient address (or glob) whether mail is filed as
  junk (`spam`), accepted and dropped (`discard`) or refused after DATA (`reject`), for explicit
  aliases and for addresses a catch-all accepts. It is built from a lookup list, an `Email`-variant
  spam rule (`RCPT-POLICY`) and three spam tags; entries accept `state: absent`. The whole message
  gets the verdict, so a mail to a listed and an unlisted address is affected for both.
- Aliases of accounts, groups and lists may be written `{address: ..., enabled: false}`: the
  alias stays but Stalwart refuses mail to it at RCPT TO.

- `stalwart_groups` manage Stalwart group accounts (a shared mailbox, calendar and address
  book with its own address); accounts join them with `groups`. `stalwart_collections` manage
  folders, calendars and address books of accounts and groups and who they are shared with
  (`share_with`, JMAP rights), as the administrator through the new module
  `stalwart_collection`. A group cannot be removed while an account is a member; the failure
  names the member. Tested on a VM and on a real host.

- Breaking: the rules of `sender_domain_routing` use `sender` instead of `domain`.
  `user@example.org` routes one envelope sender, `@example.org` a whole domain (as in
  Postfix's `sender_dependent_relayhost_maps`); address rules are tried before domain
  rules whatever their order. A `sender` that is neither fails the play. Change
  `domain: example.org` to `sender: '@example.org'`.

- `stalwart_accounts` and `stalwart_lists` manage Stalwart accounts (name, domain,
  description, aliases, no credentials) and mailing lists, with `state: absent` to
  delete them (before the domains, so a domain can go in the same run). An account
  can set `forward_to` (and `forward_keep_copy`): a Sieve `redirect`, installed as the
  administrator through the new module `stalwart_sieve_forward`, that sends the
  mail with the account's own address as envelope sender. A failed apply is explained
  afterwards with stalwart-cli's output and a hint when a domain is missing; nothing is
  checked beforehand.

- `stalwart_domains[].catch_all` sets Stalwart's catch-all address
  (`Domain.catchAllAddress`) for a domain. Leaving it out keeps the server's
  value; `null` or `""` clears it.
- caddy_front runs `caddy validate` before restarting or reloading Caddy. A bad
  config now fails the play with Caddy's own error and leaves the running Caddy
  alone; `caddy run` only exits with status 1 and the journal shows no reason.
- caddy_front's name-clash check names the clashing hostnames in its failure
  message.
- Stalwart 1.1.0 (checksums for x86_64 and aarch64), Bulwark 1.21.0 and Caddy
  v2.11.9 are the new defaults; stalwart-cli stays at 1.0.14, its latest release.
  Stalwart 1.1.0 adds passkeys, which need the new `sysPasskey*` permissions in
  default roles created by an earlier version: start the server once with
  `STALWART_UPDATE_ROLE_PERMISSIONS=true` to add them. Nothing in these roles
  needs them.
- Breaking: the name of a mail domain is no longer forwarded to Stalwart. Only
  `stalwart_hostname` and the subdomains (`mta-sts`, `autoconfig`, `autodiscover`
  and the new `ua-auto-config`) are. The domain's own name is free for a
  `caddy_domains` or `caddy_user_instances` site, and answers 404 when there is
  none. `stalwart_domains[].serve_http: true` (or `stalwart_serve_http`) brings
  the old behaviour back for a domain.
- Breaking: `stalwart_hostname` gets its own Caddy site and certificate and needs
  no `stalwart_domains` entry, so it can be `mail.example.org` without being a
  mail domain. Stalwart gets a Certificate object for it in the plan.
- Breaking: `stalwart_root_site` is gone, and so is the `www.` site it created.
  `stalwart_redirect_root` is empty by default; set it to redirect `/` of the host
  name.
- After the apply, stalwart_config compares the CNAME records Stalwart wants for
  each domain with the subdomain sites Caddy serves and fails on a difference
  (`stalwart_check_zone`).
- The `state` of `stalwart_domains` and `caddy_domains` entries defaults to
  `present`.
- Every role in the playbook carries its name as a tag: `--tags caddy_front` runs
  one role.
- `bulwark_hostname` names the host of Bulwark. caddy_front serves it (forwarding
  to the container, `caddy_bulwark_directive`) and allows it to call Stalwart across
  origins, so neither a `caddy_domains` entry nor `stalwart_cors_origins` is needed
  for Bulwark any more. The site follows `bulwark_enabled`.

- Every role has a `meta/argument_specs.yml`: Ansible checks the types and the keys
  of list entries (`stalwart_domains`, `caddy_domains`, `stalwart_relay_hosts`, ...)
  when the role starts and a misspelled or renamed key fails with its name.
- Breaking: a user instance of `caddy_user_instances` is a bare Caddyfile that
  imports `~/.config/caddy/conf.d/*.conf`. Each entry of `sites` is written to
  `conf.d/<name>.conf` (`name` defaults to the first host; `state: absent` removes
  the file); other files in `conf.d` belong to the account and are not touched.
  The `caddyfile:` key and the default hello page are gone. A site whose state is
  `absent` also removes its front site. The role's tasks are split into
  `account.yml`, `config.yml`, `units.yml` and `smoke.yml`.
- Breaking: the hosts a user's Caddy receives are set on the instance
  (`caddy_user_instances[].hosts`), not derived from its sites: the root decides
  which names go to which account and forwards everything on them. A site's own
  `hosts` default to all of them and select what that conf.d file answers; its
  `dns:` is gone (use the Stalwart domain or a `caddy_domains` entry).
- `caddy_directive` of `caddy_domains` entries is now `directive`, as in the
  sites of `caddy_user_instances`.
- `stalwart_install_vandelay: true` installs Vandelay 1.0.15, Stalwart's account
  migration tool (off by default; checksums for x86_64 and aarch64).

## 0.1.1

- Stalwart 1.0.2 (checksums for x86_64 and aarch64) and Bulwark 1.20.0 are the
  new defaults; upgrades from 1.0.1 and 1.18.0 tested on a VM and on a real host.
- `stalwart_relay_hosts[].manages_spf: true` skips the SPF/`dns:` check for relays
  that send with their own return-path domain (SMTP2GO). The check no longer
  fails on routing rules without a `state`.
- Applications marked `state: absent` are removed by id.
- Documented relays and sender routing in the defaults of `stalwart_config`.
- Role READMEs, which Galaxy's import requires.

## 0.1.0

First release. Pre-release quality: tested on Ubuntu 26.04 only; push
notifications through the Bulwark relay and relays/sender routing against real
servers are untested.
