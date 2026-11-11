# Changelog

## Unreleased

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
